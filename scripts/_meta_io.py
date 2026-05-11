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
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_PATH = REPO_ROOT / "wiki" / "_meta" / "coverage.json"
TODO_PATH = REPO_ROOT / "wiki" / "_meta" / "todo.md"
WIKI_ROOT = REPO_ROOT / "wiki"
KERNEL_ROOT = REPO_ROOT / "raw" / "linux"


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


# ---------------------------------------------------------------------------
# Todo backlog
# ---------------------------------------------------------------------------

_HEADER = "# Annealing 백로그\n\n"
_HINT = ("자동 채워집니다. 각 항목은 patch router / `anneal.py`가 추가합니다.\n"
         "해결되면 체크박스를 표시하거나 항목을 지우세요.\n\n")


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
