"""Batch driver: fill every unfilled wiki page via ``update_wiki seed-agent``.

Reads ``wiki/_meta/coverage.json`` for the page list. Skips pages whose
``last_synced`` is already set (use ``--force`` to refill them). Invokes
``python -m scripts.update_wiki seed-agent --page <P> --model <M>`` per
page as a separate subprocess so a single-page failure or hang doesn't
poison the batch.

Backend selection comes from ``config/llm.local.json`` via
``default_profile`` (see CLAUDE.md §4); this script does NOT touch env
vars itself.

Examples
--------

::

    # fill every unfilled page in the current coverage with the default profile
    python -m scripts.seed_all --model qwen3.6:27b-q4_K_M

    # narrow to one sub-directory
    python -m scripts.seed_all --model qwen3.6:27b-q4_K_M \\
        --filter 'raw/pcie_scsc/osal/*'

    # show the commands without running them
    python -m scripts.seed_all --model claude-sonnet-4-5 --dry-run

    # refill everything (e.g., after a prompt change)
    python -m scripts.seed_all --model claude-sonnet-4-5 --force --continue
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
COVERAGE = REPO_ROOT / "wiki" / "_meta" / "coverage.json"


def _select_pages(cov: dict[str, Any], *,
                  glob: str | None,
                  force: bool) -> list[str]:
    """Return the sorted page paths to process, after filter + filled check."""
    out: list[str] = []
    for page in sorted(cov.get("pages", {}).keys()):
        if glob and not fnmatch.fnmatchcase(page, glob):
            continue
        if not force and cov["pages"][page].get("last_synced"):
            continue
        out.append(page)
    return out


def _build_cmd(page: str, *, model: str, force: bool) -> list[str]:
    cmd = [
        sys.executable, "-m", "scripts.update_wiki", "seed-agent",
        "--page", page,
        "--model", model,
    ]
    if force:
        cmd.append("--overwrite")
    return cmd


def _run(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--model", required=True,
                   help="model name passed through to seed-agent")
    p.add_argument("--filter", dest="glob",
                   help="fnmatch glob on coverage.json page keys "
                        "(e.g. 'raw/pcie_scsc/kunit/*')")
    p.add_argument("--force", action="store_true",
                   help="refill pages even when last_synced is already set "
                        "(passes --overwrite to seed-agent)")
    p.add_argument("--continue", dest="cont", action="store_true",
                   help="on per-page failure, skip and continue with the rest "
                        "(default: stop on first failure)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the commands that would run; do not invoke them")
    args = p.parse_args(argv)

    if not COVERAGE.exists():
        print(f"[seed-all] coverage.json not found at {COVERAGE}",
              file=sys.stderr)
        return 2
    cov = json.loads(COVERAGE.read_text())
    pages = _select_pages(cov, glob=args.glob, force=args.force)
    if not pages:
        print("[seed-all] no matching pages to process", file=sys.stderr)
        return 0

    plan = (
        f"[seed-all] {len(pages)} page(s) to process, model={args.model}"
        + (f", filter={args.glob}" if args.glob else "")
        + (", force" if args.force else "")
        + (", dry-run" if args.dry_run else "")
    )
    print(plan, file=sys.stderr)

    n_ok = n_fail = 0
    failed: list[str] = []
    start = time.monotonic()

    def _summary() -> None:
        elapsed = time.monotonic() - start
        print(
            f"[seed-all] done: ok={n_ok} fail={n_fail} "
            f"of {len(pages)} ({elapsed:.0f}s)",
            file=sys.stderr,
        )
        if failed:
            print(f"[seed-all] failed pages ({len(failed)}):", file=sys.stderr)
            for p in failed:
                print(f"    {p}", file=sys.stderr)

    def _sigint(_signum, _frame):
        print("\n[seed-all] interrupted, aborting batch", file=sys.stderr)
        _summary()
        sys.exit(130)
    signal.signal(signal.SIGINT, _sigint)

    for i, page in enumerate(pages, 1):
        cmd = _build_cmd(page, model=args.model, force=args.force)
        if args.dry_run:
            print(" ".join(cmd))
            continue

        print(f"[seed-all {i}/{len(pages)}] {page} ...",
              file=sys.stderr, flush=True)
        t0 = time.monotonic()
        rc = subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode
        dt = time.monotonic() - t0
        if rc == 0:
            n_ok += 1
            print(f"[seed-all {i}/{len(pages)}] ok ({dt:.0f}s)",
                  file=sys.stderr)
        else:
            n_fail += 1
            failed.append(page)
            print(f"[seed-all {i}/{len(pages)}] FAIL rc={rc} ({dt:.0f}s)",
                  file=sys.stderr)
            if not args.cont:
                print("[seed-all] stopping on first failure "
                      "(pass --continue to skip)", file=sys.stderr)
                _summary()
                return 1

    _summary()
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv[1:]))
