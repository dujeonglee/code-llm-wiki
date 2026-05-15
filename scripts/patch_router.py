"""Route changed source files to the wiki pages that own them.

Reads a manifest (from ``sync_subtree.py``) plus the coverage index, and
prints which pages need re-syncing and which files no page currently covers.

Usage
-----

::

    # pipe from sync_subtree
    python -m scripts.sync_subtree --tree raw/pcie_scsc --no-fetch \\
        | python -m scripts.patch_router

    # or from a saved manifest
    python -m scripts.patch_router --manifest /tmp/m.json

    # or ad-hoc with explicit file list (useful for tests / demos)
    python -m scripts.patch_router --files pcie_scsc/mlme.c pcie_scsc/hip.c

Flags
-----

``--apply``     append uncovered files to ``wiki/_meta/todo.md`` so the
                annealer (D4) eventually creates pages for them.
``--out PATH``  also write the routing decision to PATH (the wiki updater
                in D3 will consume this).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts._meta_io import Coverage, affected_pages, append_todo


def _read_manifest(args: argparse.Namespace) -> dict:
    if args.files:
        return {"from": None, "to": None, "files": args.files, "commits": []}
    if args.manifest:
        return json.loads(Path(args.manifest).read_text())
    data = sys.stdin.read()
    if not data.strip():
        raise SystemExit(
            "No manifest input. Pipe sync_subtree output, or pass "
            "--manifest or --files."
        )
    return json.loads(data)


def route(manifest: dict, *, apply: bool = False) -> dict:
    cov = Coverage.load()
    files: list[str] = list(manifest.get("files") or [])
    pages, uncovered = affected_pages(cov, files)

    result = {
        "from": manifest.get("from"),
        "to": manifest.get("to"),
        "n_files": len(files),
        "affected_pages": pages,
        "uncovered": uncovered,
        "commits": manifest.get("commits", []),
    }

    if apply and uncovered:
        n = append_todo("uncovered files (router)", uncovered)
        result["todo_added"] = n
    return result


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--manifest", help="path to manifest JSON")
    src.add_argument("--files", nargs="+",
                     help="ad-hoc list of changed paths (kernel-relative)")
    p.add_argument("--apply", action="store_true",
                   help="append uncovered files to wiki/_meta/todo.md")
    p.add_argument("--out", help="also write the routing JSON here")
    args = p.parse_args(argv)

    manifest = _read_manifest(args)
    result = route(manifest, apply=args.apply)
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
