"""Shared I/O for ``wiki/_meta/`` artifacts.

The coverage index is the single source of truth for "which wiki page owns
which raw source paths". Both the patch router (D2) and the wiki updater
(D3) read it; the wiki updater writes it. Schema:

::

    {
      "schema_version": 1,
      "last_kernel_sha": "abc123" | null,
      "pages": {
        "subsystems/mm.md": {
          "kind": "subsystem" | "concept" | "entity" | "query",
          "covers": ["mm/*.c", "mm/slab*", "mm/Documentation/*"],
          "last_synced_sha": "abc123" | null,
          "last_synced": "2026-05-10T12:00:00Z" | null
        }
      }
    }

Glob semantics (POSIX-style paths, relative to ``raw/linux/``):

* ``*``  matches anything except ``/``
* ``**`` matches any number of path segments (including zero)
* ``?``  matches one char except ``/``

The todo backlog (``wiki/_meta/todo.md``) is a markdown checklist that the
patch router and annealer both append to. Items are deduped on a "tag" prefix.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_PATH = REPO_ROOT / "wiki" / "_meta" / "coverage.json"
TODO_PATH = REPO_ROOT / "wiki" / "_meta" / "todo.md"
WIKI_ROOT = REPO_ROOT / "wiki"
KERNEL_ROOT = REPO_ROOT / "raw"


# ---------------------------------------------------------------------------
# Coverage I/O
# ---------------------------------------------------------------------------

@dataclass
class Coverage:
    schema_version: int = 1
    last_kernel_sha: str | None = None
    pages: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Coverage":
        # Resolve at call time so tests can monkeypatch _meta_io.COVERAGE_PATH.
        p = path if path is not None else _module_coverage_path()
        with p.open() as f:
            data = json.load(f)
        return cls(
            schema_version=data.get("schema_version", 1),
            last_kernel_sha=data.get("last_kernel_sha"),
            pages=data.get("pages", {}),
        )

    def save(self, path: Path | None = None) -> None:
        p = path if path is not None else _module_coverage_path()
        payload = {
            "schema_version": self.schema_version,
            "last_kernel_sha": self.last_kernel_sha,
            "pages": self.pages,
        }
        p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _module_coverage_path() -> Path:
    # Indirection so tests that replace _meta_io.COVERAGE_PATH take effect.
    import sys
    return sys.modules[__name__].COVERAGE_PATH


def _module_todo_path() -> Path:
    import sys
    return sys.modules[__name__].TODO_PATH


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------

def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a path glob to a regex anchored at both ends.

    Used to match ``covers`` patterns against kernel-relative paths.
    """
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # ** -> any number of path segments
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                else:
                    out.append(".*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in r".+()|^$\{}[]":
            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    return re.compile("^" + "".join(out) + "$")


def page_matches(page_entry: dict[str, Any], path: str) -> bool:
    for pat in page_entry.get("covers", []):
        if glob_to_regex(pat).match(path):
            return True
    return False


def affected_pages(coverage: Coverage,
                   changed_files: list[str]) -> tuple[list[str], list[str]]:
    """Split changed files into (pages that cover them, files no page covers).

    Returns (affected_pages_sorted, uncovered_files_sorted).
    """
    affected: set[str] = set()
    uncovered: set[str] = set()
    for f in changed_files:
        matched_any = False
        for page, entry in coverage.pages.items():
            if page_matches(entry, f):
                affected.add(page)
                matched_any = True
        if not matched_any:
            uncovered.add(f)
    return sorted(affected), sorted(uncovered)


_HEADER = "# Annealing 백로그\n\n"
_HINT = ("자동 채워집니다. 각 항목은 patch router / `anneal.py`가 추가합니다.\n"
         "해결되면 체크박스를 표시하거나 항목을 지우세요.\n\n")


# ---------------------------------------------------------------------------
# Page front-matter + body
# ---------------------------------------------------------------------------
#
# We parse a tiny subset of YAML (string scalars, ISO dates, null, and string
# lists either flow [a, b] or block "- item"). Good enough for our schema and
# avoids a PyYAML dependency. Anything fancier is rejected so the LLM can't
# sneak unexpected structure in.

_FM_FENCE = "---"


def _parse_scalar(s: str) -> Any:
    s = s.strip()
    if s == "" or s.lower() in ("null", "~"):
        return None
    if (s.startswith('"') and s.endswith('"')) or \
       (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``text`` into (front_matter dict, body string).

    If no front matter, returns ({}, text).
    """
    if not text.startswith(_FM_FENCE + "\n") and text != _FM_FENCE:
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM_FENCE:
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM_FENCE:
            end = i
            break
    if end is None:
        return {}, text
    fm: dict[str, Any] = {}
    current_key: str | None = None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        # block-style list item
        if current_key is not None and raw.lstrip().startswith("- "):
            item = raw.lstrip()[2:].strip()
            fm[current_key].append(_parse_scalar(item))
            continue
        if ":" not in raw:
            continue
        key, _, rest = raw.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            # next non-empty line(s) starting with '- ' belong here
            fm[key] = []
            current_key = key
            continue
        # flow list: [a, b, c]
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            fm[key] = [_parse_scalar(x) for x in inner.split(",") if x.strip()]
        else:
            fm[key] = _parse_scalar(rest)
        current_key = None
    body = "\n".join(lines[end + 1:])
    if body.startswith("\n"):
        body = body[1:]
    return fm, body


def serialize_front_matter(fm: dict[str, Any]) -> str:
    """Render a front-matter dict back to the YAML subset we parse."""
    out = [_FM_FENCE]
    for k, v in fm.items():
        if v is None:
            out.append(f"{k}: null")
        elif isinstance(v, list):
            if not v:
                out.append(f"{k}: []")
            else:
                out.append(f"{k}:")
                for item in v:
                    out.append(f"  - {item}")
        else:
            s = str(v)
            # Quote if it contains characters that would confuse a re-parse.
            if any(c in s for c in ":#") or s.strip() != s:
                s = '"' + s.replace('"', '\\"') + '"'
            out.append(f"{k}: {s}")
    out.append(_FM_FENCE)
    return "\n".join(out) + "\n"


def serialize_page(fm: dict[str, Any], body: str) -> str:
    body = body if body.endswith("\n") else body + "\n"
    return serialize_front_matter(fm) + "\n" + body


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_markdown_block(response: str) -> str:
    """Pull the inner content of the outer ```markdown ... ``` fence in an
    LLM response. Greedy on the closing fence so inner ```c / ```python code
    blocks inside the page body don't truncate the match. The closing fence
    must be at the start of a line followed by newline or EOF. Falls back to
    the whole response stripped if no fence is present.
    """
    fence = re.search(
        r"```(?:markdown|md)?\s*\n(.*)\n```\s*(?:\n|\Z)",
        response,
        flags=re.DOTALL,
    )
    if fence:
        return fence.group(1).rstrip() + "\n"
    return response.strip() + "\n"


# ---------------------------------------------------------------------------
# Todo backlog
# ---------------------------------------------------------------------------

def append_todo(tag: str, items: list[str], path: Path | None = None) -> int:
    """Append ``items`` under a ``tag`` heading, deduping against existing
    body. Returns the number of newly added items.
    """
    p = path if path is not None else _module_todo_path()
    body = p.read_text() if p.exists() else ""
    if not body.startswith(_HEADER):
        body = _HEADER + _HINT + (body if body.strip() else "")
    existing = set(re.findall(r"- \[ \] `([^`]+)`", body))
    new_items = [x for x in items if x not in existing]
    if not new_items:
        return 0
    section = f"\n## {tag}\n\n"
    for x in new_items:
        section += f"- [ ] `{x}`\n"
    p.write_text(body.rstrip() + "\n" + section)
    return len(new_items)
