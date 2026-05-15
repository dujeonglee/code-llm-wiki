"""LLM provider abstraction.

Supports two protocols, selected per profile in ``config/llm.json``:

* ``anthropic``  - Claude Messages API (``POST /v1/messages``)
* ``openai``     - OpenAI Chat Completions API (``POST /chat/completions``);
                   also works with any OpenAI-compatible endpoint (Ollama,
                   vLLM, OpenRouter, LM Studio, ...).

Config resolution order (first that exists wins):

1. ``$LLM_CONFIG`` (env, absolute or repo-relative path)
2. ``config/llm.local.json`` (gitignored; per-user keys, recommended)
3. ``config/llm.json``       (committed)
4. ``config/llm.example.json`` (committed template; auth_env is read from env)

Public surface
--------------

``load_config()``               -> dict
``get_profile(name=None)``      -> dict (the resolved profile)
``chat(messages, *, system=None, profile=None, max_tokens=None,
       temperature=None, cache_system=True)``
                                -> ChatResult(text, usage, model, raw)
``probe(profile=None)``         -> bool   (used by ``--probe`` CLI)

CLI
---

    python -m scripts.llm_client --probe                 # default profile
    python -m scripts.llm_client --probe --profile openai
    python -m scripts.llm_client --probe --all           # every profile
    python -m scripts.llm_client --selftest              # offline checks
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_CANDIDATES = (
    "config/llm.local.json",
    "config/llm.json",
    "config/llm.example.json",
)


class LLMError(RuntimeError):
    """Raised for any provider call that cannot be retried into success."""


@dataclass
class ChatResult:
    text: str
    usage: dict[str, Any]
    model: str
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    override = os.environ.get("LLM_CONFIG")
    if override:
        p = Path(override)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if not p.exists():
            raise LLMError(f"LLM_CONFIG points to missing file: {p}")
        return p
    for rel in CONFIG_CANDIDATES:
        p = REPO_ROOT / rel
        if p.exists():
            return p
    raise LLMError(
        "No LLM config found. Copy config/llm.example.json to "
        "config/llm.local.json and fill in keys."
    )


def load_config() -> dict[str, Any]:
    path = _config_path()
    with path.open() as f:
        cfg = json.load(f)
    if "profiles" not in cfg or not isinstance(cfg["profiles"], dict):
        raise LLMError(f"{path}: missing 'profiles' object")
    return cfg


def get_profile(name: str | None = None) -> dict[str, Any]:
    cfg = load_config()
    name = name or cfg.get("default_profile")
    if not name:
        raise LLMError("No profile specified and no default_profile in config")
    if name not in cfg["profiles"]:
        raise LLMError(
            f"Profile '{name}' not in config. Available: "
            f"{sorted(cfg['profiles'])}"
        )
    p = dict(cfg["profiles"][name])
    p.setdefault("provider", "anthropic")
    p.setdefault("max_tokens", 4096)
    p.setdefault("temperature", 0.2)
    p.setdefault("extra_headers", {})
    p.setdefault("timeout", 120)
    p["_name"] = name
    return p


def _resolve_auth(profile: dict[str, Any]) -> str | None:
    env = profile.get("auth_env")
    if not env:
        return None
    val = os.environ.get(env)
    if val:
        return val
    if profile.get("auth_optional"):
        return None
    raise LLMError(
        f"Profile '{profile['_name']}' requires env var {env} but it is unset"
    )


def sdk_env_for_profile(name: str | None = None) -> dict[str, str]:
    """Translate an llm.json profile into env vars for claude-agent-sdk.

    The wiki repo's config is the single source of truth for which backend
    seed-agent (and any other SDK-using script) talks to; callers should
    write the returned dict into ``os.environ`` before invoking the SDK.

    Mapping
    -------

    ``provider == "anthropic"`` — Anthropic cloud. Returns::

        {"ANTHROPIC_API_KEY": <value of profile.auth_env in os.environ>}

    ``provider == "openai"`` — Anthropic-compatible backend (ollama v0.14+,
    LiteLLM, etc.). Returns::

        {"ANTHROPIC_BASE_URL": <profile.base_url with trailing /v1 stripped>,
         "ANTHROPIC_AUTH_TOKEN": <profile.auth_env value, or "ollama" if
                                  auth_optional and the env var is unset>}

    Raises :class:`LLMError` for any other provider or if a required env
    var is missing.
    """
    profile = get_profile(name)
    provider = profile["provider"]
    if provider == "anthropic":
        key = _resolve_auth(profile)
        if not key:
            raise LLMError(
                f"Profile '{profile['_name']}' has no API key resolved "
                f"(set {profile.get('auth_env')!r} in the environment)."
            )
        return {"ANTHROPIC_API_KEY": key}
    if provider == "openai":
        base = profile["base_url"].rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        env = {"ANTHROPIC_BASE_URL": base}
        token = _resolve_auth(profile)
        if token:
            env["ANTHROPIC_AUTH_TOKEN"] = token
        else:
            # The SDK requires ANTHROPIC_AUTH_TOKEN to be set even when the
            # backend (e.g. ollama) ignores its value.
            env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
        return env
    raise LLMError(
        f"Profile '{profile['_name']}' has provider={provider!r}; "
        "only 'anthropic' and 'openai' are supported by sdk_env_for_profile."
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http_post(url: str, headers: dict[str, str], body: dict[str, Any],
               timeout: int = 120) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read().decode("utf-8")
                return json.loads(payload)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            # 4xx (except 408/429) is not worth retrying
            if e.code not in (408, 429) and 400 <= e.code < 500:
                raise LLMError(
                    f"HTTP {e.code} from {url}: {err_body[:500]}"
                ) from e
            last_exc = LLMError(f"HTTP {e.code} from {url}: {err_body[:500]}")
        except (urllib.error.URLError, TimeoutError) as e:
            last_exc = LLMError(f"Network error to {url}: {e}")
        time.sleep(2 ** attempt)
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------

def _anthropic_chat(profile: dict[str, Any], messages: list[dict[str, Any]],
                    system: str | None, max_tokens: int, temperature: float,
                    cache_system: bool) -> ChatResult:
    base = profile["base_url"].rstrip("/")
    url = f"{base}/v1/messages"
    key = _resolve_auth(profile)
    if not key:
        raise LLMError(f"Anthropic profile '{profile['_name']}' has no key")
    headers = {
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }
    headers.update(profile.get("extra_headers", {}))
    body: dict[str, Any] = {
        "model": profile["model"],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if system:
        if cache_system:
            body["system"] = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            body["system"] = system
    raw = _http_post(url, headers, body, timeout=int(profile["timeout"]))
    text = "".join(
        b.get("text", "") for b in raw.get("content", [])
        if b.get("type") == "text"
    )
    return ChatResult(
        text=text,
        usage=raw.get("usage", {}),
        model=raw.get("model", profile["model"]),
        raw=raw,
    )


def _openai_chat(profile: dict[str, Any], messages: list[dict[str, Any]],
                 system: str | None, max_tokens: int, temperature: float,
                 cache_system: bool) -> ChatResult:
    base = profile["base_url"].rstrip("/")
    url = f"{base}/chat/completions"
    key = _resolve_auth(profile)
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    headers.update(profile.get("extra_headers", {}))
    msgs: list[dict[str, Any]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    body = {
        "model": profile["model"],
        "messages": msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    raw = _http_post(url, headers, body, timeout=int(profile["timeout"]))
    choices = raw.get("choices") or []
    if not choices:
        raise LLMError(f"OpenAI-style response had no choices: {raw}")
    text = choices[0].get("message", {}).get("content", "") or ""
    return ChatResult(
        text=text,
        usage=raw.get("usage", {}),
        model=raw.get("model", profile["model"]),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chat(messages: list[dict[str, Any]], *,
         system: str | None = None,
         profile: str | None = None,
         max_tokens: int | None = None,
         temperature: float | None = None,
         cache_system: bool = True) -> ChatResult:
    """Send a chat completion request using the named profile."""
    p = get_profile(profile)
    mt = max_tokens if max_tokens is not None else p["max_tokens"]
    tp = temperature if temperature is not None else p["temperature"]
    provider = p["provider"]
    if provider == "anthropic":
        return _anthropic_chat(p, messages, system, mt, tp, cache_system)
    if provider == "openai":
        return _openai_chat(p, messages, system, mt, tp, cache_system)
    raise LLMError(f"Unknown provider '{provider}' in profile {p['_name']}")


def probe(profile: str | None = None) -> bool:
    """Send a 1-token round-trip to verify auth + reachability."""
    p = get_profile(profile)
    name = p["_name"]
    try:
        res = chat(
            [{"role": "user", "content": "Reply with the single word: pong"}],
            profile=name,
            max_tokens=16,
            temperature=0.0,
        )
    except LLMError as e:
        print(f"[probe] {name}: FAIL  {e}", file=sys.stderr)
        return False
    text = res.text.strip().lower()
    ok = "pong" in text
    status = "OK  " if ok else "WARN"
    print(f"[probe] {name}: {status}  model={res.model}  "
          f"usage={res.usage}  reply={text[:60]!r}")
    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selftest() -> bool:
    """Offline verification: config loads, provider routing builds
    well-formed request bodies for both providers. No network calls."""
    import io
    import unittest.mock as mock

    cfg = load_config()
    assert "profiles" in cfg, "config has no profiles"
    print(f"[selftest] config: {len(cfg['profiles'])} profile(s) "
          f"= {sorted(cfg['profiles'])}")

    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], body: dict[str, Any],
                  timeout: int = 120) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        if "anthropic" in url or "/v1/messages" in url:
            return {"content": [{"type": "text", "text": "pong"}],
                    "model": body["model"], "usage": {"input_tokens": 1}}
        return {"choices": [{"message": {"content": "pong"}}],
                "model": body["model"], "usage": {"prompt_tokens": 1}}

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-anthropic")
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-openai")

    with mock.patch(__name__ + "._http_post", side_effect=fake_post):
        for name, prof in cfg["profiles"].items():
            if prof.get("provider") == "anthropic" \
                    and not os.environ.get(prof.get("auth_env", "")):
                continue
            res = chat(
                [{"role": "user", "content": "ping"}],
                system="you are concise",
                profile=name,
                max_tokens=8,
            )
            provider = prof["provider"]
            body = captured["body"]
            assert body["model"] == prof["model"], (name, body)
            assert body["max_tokens"] == 8, (name, body)
            if provider == "anthropic":
                assert captured["url"].endswith("/v1/messages"), captured["url"]
                assert "x-api-key" in captured["headers"]
                assert isinstance(body["system"], list)
                assert body["system"][0]["cache_control"]["type"] == "ephemeral"
            else:
                assert captured["url"].endswith("/chat/completions"), captured["url"]
                assert body["messages"][0]["role"] == "system"
            assert res.text == "pong"
            print(f"[selftest] {name} ({provider}): body OK, text={res.text!r}")

    print("[selftest] OK")
    return True


def _main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description="LLM client / probe")
    parser.add_argument("--profile", help="profile name (default: per config)")
    parser.add_argument("--probe", action="store_true",
                        help="round-trip test the profile (needs API key)")
    parser.add_argument("--all", action="store_true",
                        help="with --probe: test every configured profile")
    parser.add_argument("--prompt", help="ad-hoc user prompt to send")
    parser.add_argument("--selftest", action="store_true",
                        help="offline checks: config load + body shape")
    args = parser.parse_args(list(argv))

    if args.selftest:
        return 0 if _selftest() else 1

    if args.probe:
        if args.all:
            names = sorted(load_config()["profiles"])
            results = [probe(n) for n in names]
            return 0 if all(results) else 1
        return 0 if probe(args.profile) else 1

    if args.prompt:
        res = chat(
            [{"role": "user", "content": args.prompt}],
            profile=args.profile,
        )
        print(res.text)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
