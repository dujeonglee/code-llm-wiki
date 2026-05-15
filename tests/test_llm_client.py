"""Unit tests for scripts.llm_client.sdk_env_for_profile.

The helper translates an existing llm.json profile into the env vars
claude-agent-sdk expects. No new schema; rules:
  - provider=anthropic → ANTHROPIC_API_KEY from os.environ[auth_env]
  - provider=openai    → ANTHROPIC_BASE_URL (base_url minus trailing /v1)
                         + ANTHROPIC_AUTH_TOKEN (auth_env value, or "ollama"
                         literal when auth_optional and env var missing)
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import llm_client


class _IsolatedConfig(unittest.TestCase):
    """Point llm_client at a tempdir config so tests don't read llm.local.json."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg_path = Path(self.tmp.name) / "llm.json"
        self._orig_env = os.environ.copy()
        os.environ["LLM_CONFIG"] = str(self.cfg_path)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def _write_config(self, cfg: dict) -> None:
        self.cfg_path.write_text(json.dumps(cfg))


class SdkEnvAnthropic(_IsolatedConfig):
    def test_returns_api_key_from_auth_env(self):
        self._write_config({
            "default_profile": "claude",
            "profiles": {
                "claude": {
                    "provider": "anthropic",
                    "base_url": "https://api.anthropic.com",
                    "auth_env": "MY_ANTHROPIC_KEY",
                    "model": "claude-sonnet-4-5",
                },
            },
        })
        os.environ["MY_ANTHROPIC_KEY"] = "sk-ant-test-123"
        env = llm_client.sdk_env_for_profile("claude")
        self.assertEqual(env, {"ANTHROPIC_API_KEY": "sk-ant-test-123"})

    def test_raises_when_key_missing(self):
        self._write_config({
            "default_profile": "claude",
            "profiles": {
                "claude": {
                    "provider": "anthropic",
                    "base_url": "https://api.anthropic.com",
                    "auth_env": "MISSING_KEY",
                    "model": "claude-sonnet-4-5",
                },
            },
        })
        os.environ.pop("MISSING_KEY", None)
        with self.assertRaises(llm_client.LLMError):
            llm_client.sdk_env_for_profile("claude")


class SdkEnvOpenai(_IsolatedConfig):
    def test_strips_trailing_v1_from_base_url(self):
        self._write_config({
            "default_profile": "ollama",
            "profiles": {
                "ollama": {
                    "provider": "openai",
                    "base_url": "http://localhost:11434/v1",
                    "auth_env": "OLLAMA_API_KEY",
                    "auth_optional": True,
                    "model": "qwen3.6:27b-q4_K_M",
                },
            },
        })
        os.environ.pop("OLLAMA_API_KEY", None)
        env = llm_client.sdk_env_for_profile("ollama")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://localhost:11434")

    def test_auth_optional_uses_literal_token_when_env_missing(self):
        self._write_config({
            "default_profile": "ollama",
            "profiles": {
                "ollama": {
                    "provider": "openai",
                    "base_url": "http://localhost:11434/v1",
                    "auth_env": "OLLAMA_API_KEY",
                    "auth_optional": True,
                    "model": "qwen3.6:27b-q4_K_M",
                },
            },
        })
        os.environ.pop("OLLAMA_API_KEY", None)
        env = llm_client.sdk_env_for_profile("ollama")
        # Value is ignored by the backend but the var must be set.
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "ollama")

    def test_uses_env_token_when_set(self):
        self._write_config({
            "default_profile": "litellm",
            "profiles": {
                "litellm": {
                    "provider": "openai",
                    "base_url": "https://proxy.example.com",
                    "auth_env": "LITELLM_KEY",
                    "model": "claude-sonnet-4-5",
                },
            },
        })
        os.environ["LITELLM_KEY"] = "secret-abc"
        env = llm_client.sdk_env_for_profile("litellm")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://proxy.example.com")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "secret-abc")


class SdkEnvUnknownProvider(_IsolatedConfig):
    def test_raises_for_unsupported_provider(self):
        self._write_config({
            "default_profile": "weird",
            "profiles": {
                "weird": {
                    "provider": "google",
                    "base_url": "https://example.com",
                    "auth_env": "GOOGLE_KEY",
                    "model": "gemini",
                },
            },
        })
        os.environ["GOOGLE_KEY"] = "x"
        with self.assertRaises(llm_client.LLMError):
            llm_client.sdk_env_for_profile("weird")


if __name__ == "__main__":
    unittest.main()
