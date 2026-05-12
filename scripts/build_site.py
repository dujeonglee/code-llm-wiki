"""Build the static HTML site (D5).

Wraps ``mkdocs build`` with a preflight sanity check, so failures point at
the wiki content rather than at a confusing MkDocs traceback. Output is a
standalone ``site/`` directory whose pages can be opened directly with a
browser via ``file://`` (``mkdocs.yml`` sets ``use_directory_urls: false``
so links resolve as ``foo.html`` rather than ``foo/``). No web server
needed — just double-click ``site/index.html``.

Preflight checks (run without MkDocs needing to be installed):

* ``mkdocs.yml`` exists.
* ``wiki/index.md`` exists (MkDocs requires a home page).
* every wiki page has at most one front-matter block.
* every ``[[wiki-link]]`` target resolves to an existing page (warnings
  only; ``anneal.py`` is the authoritative gap detector).

CLI
---

::

    python -m scripts.build_site                 # mkdocs build -> site/
    python -m scripts.build_site --clean         # rm -rf site/ first
    python -m scripts.build_site --strict        # fail on MkDocs warnings
    python -m scripts.build_site --serve         # mkdocs serve, :8000
    python -m scripts.build_site --preflight     # checks only, no build
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from scripts._meta_io import WIKI_ROOT, parse_front_matter

REPO_ROOT = Path(__file__).resolve().parent.parent
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"
SITE_DIR = REPO_ROOT / "site"


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def _iter_wiki_pages() -> list[Path]:
    pages: list[Path] = []
    for p in WIKI_ROOT.rglob("*.md"):
        if any(part == "_meta" for part in p.relative_to(WIKI_ROOT).parts):
            continue
        pages.append(p)
    return sorted(pages)


def _check_one_front_matter(text: str) -> str | None:
    """Return an error string, or None if OK."""
    if not text.startswith("---\n"):
        return None  # no front matter is fine
    # count '---' lines that *could* close a front-matter block.
    fences = [i for i, ln in enumerate(text.splitlines())
              if ln.strip() == "---"]
    if len(fences) < 2:
        return "front matter opened but not closed"
    # A double front-matter block looks like fences[0]=0, fences[1]=N,
    # fences[2]=N+something (e.g., the D3 bug we already fixed).
    if len(fences) >= 4 and fences[1] - fences[0] < 5:
        return "two front-matter blocks at top — page is corrupt"
    return None


def _resolve_link_target(target: str, wiki_set: set[str]) -> bool:
    target = target.strip().lstrip("/")
    if not target.endswith(".md"):
        target += ".md"
    return target in wiki_set


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def preflight(verbose: bool = True) -> tuple[int, int]:
    """Returns (errors, warnings)."""
    errors = 0
    warnings = 0
    if not MKDOCS_YML.exists():
        print(f"[preflight] ERROR: {_rel(MKDOCS_YML)} missing",
              file=sys.stderr)
        errors += 1
    if not (WIKI_ROOT / "index.md").exists():
        print("[preflight] ERROR: wiki/index.md is required by MkDocs",
              file=sys.stderr)
        errors += 1

    pages = _iter_wiki_pages()
    wiki_set = {p.relative_to(WIKI_ROOT).as_posix() for p in pages}
    if verbose:
        print(f"[preflight] {len(pages)} page(s) under wiki/")

    import re
    link_re = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
    for p in pages:
        rel = p.relative_to(WIKI_ROOT).as_posix()
        text = p.read_text()
        err = _check_one_front_matter(text)
        if err:
            print(f"[preflight] ERROR: {rel}: {err}", file=sys.stderr)
            errors += 1
        fm, _ = parse_front_matter(text)
        for m in link_re.finditer(text):
            tgt = m.group(1)
            if not _resolve_link_target(tgt, wiki_set):
                print(f"[preflight] WARN: {rel}: broken [[{tgt}]]",
                      file=sys.stderr)
                warnings += 1
    if verbose:
        status = "OK" if errors == 0 else "FAIL"
        print(f"[preflight] {status}  errors={errors}  warnings={warnings}")
    return errors, warnings


# ---------------------------------------------------------------------------
# MkDocs invocation
# ---------------------------------------------------------------------------

def _mkdocs_available() -> bool:
    return shutil.which("mkdocs") is not None


def _run_mkdocs(extra: Iterable[str]) -> int:
    if not _mkdocs_available():
        print(
            "[build_site] ERROR: `mkdocs` not found on PATH.\n"
            "             Install it first:\n"
            "                 python -m venv .venv && . .venv/bin/activate\n"
            "                 pip install -r requirements-docs.txt",
            file=sys.stderr,
        )
        return 127
    cmd = ["mkdocs", *extra, "-f", str(MKDOCS_YML)]
    return subprocess.call(cmd, cwd=REPO_ROOT)


def cmd_build(args: argparse.Namespace) -> int:
    errors, warnings = preflight()
    if errors:
        return 2
    if args.clean and SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
        print(f"[build_site] cleaned {_rel(SITE_DIR)}")
    extra = ["build"]
    if args.strict:
        extra.append("--strict")
    return _run_mkdocs(extra)


def cmd_serve(args: argparse.Namespace) -> int:
    errors, _ = preflight()
    if errors:
        return 2
    return _run_mkdocs(["serve", "-a", args.bind])


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--serve", action="store_true",
                   help="live-reload server instead of one-shot build")
    p.add_argument("--bind", default="127.0.0.1:8000",
                   help="address for --serve (default: 127.0.0.1:8000)")
    p.add_argument("--strict", action="store_true",
                   help="fail on MkDocs warnings")
    p.add_argument("--clean", action="store_true",
                   help="remove site/ before building")
    p.add_argument("--preflight", action="store_true",
                   help="run preflight checks only; do not invoke MkDocs")
    args = p.parse_args(argv)

    if args.preflight:
        errors, warnings = preflight()
        return 0 if errors == 0 else 2
    if args.serve:
        return cmd_serve(args)
    return cmd_build(args)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
