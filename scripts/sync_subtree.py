"""Fetch a raw/ sub-tree and emit a manifest of changed files.

Each ``raw/<top>/`` lives in its own local git repo, and this script
diffs the previously-seen sha (stored in ``coverage.json``) against the
current HEAD. The resulting manifest is fed to ``patch_router.py`` which
maps changed files to wiki pages, then to ``update_wiki update`` which
patches those pages.

Daily-sync cron example::

    cd /path/to/code-llm-wiki
    python -m scripts.sync_subtree --tree raw/pcie_scsc --record --out /tmp/m.json
    python -m scripts.patch_router --manifest /tmp/m.json --apply --out /tmp/r.json
    python -m scripts.update_wiki update --routing /tmp/r.json

Specifying the sub-tree
-----------------------

``--tree`` is required and must point at an existing local git repo
under ``raw/``. There's no implicit default — multi-tree setups make a
single default misleading. To pull from a non-``origin`` remote or a
specific branch, pass ``--remote`` / ``--branch``.

How the diff is computed
------------------------

``wiki/_meta/coverage.json`` holds ``subtree_shas[<top>]`` — the commit
each sub-tree was last synced against. On the very first run the entry
is missing, so we record the current ``HEAD`` and emit an empty file
list (no retroactive documentation; ``seed-agent`` and ``anneal`` fill
in pages lazily). On subsequent runs we ``git diff <last>..HEAD`` and
emit the changed files.

Output
------

JSON on stdout, of the form::

    {
      "tree":    "raw/<top>",
      "from":    "<sha or null>",
      "to":      "<sha>",
      "files":   ["pcie_scsc/mlme.c", "pcie_scsc/dev.c", ...],
      "commits": ["<sha> <subject>", ...]   # at most --max-commits
    }

The ``files`` paths are KERNEL_ROOT-relative (i.e. start at the
``<top>/`` segment) so they line up with ``covers`` globs.

Side effects
------------

None by default. With ``--record``, updates
``coverage.subtree_shas[<top>]`` to the new HEAD so the next run picks
up where this one left off.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts._meta_io import KERNEL_ROOT, Coverage


def _git(args: list[str], cwd: Path) -> str:
    res = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed (rc={res.returncode}):\n"
            f"{res.stderr.strip()}"
        )
    return res.stdout


def _ensure_git_repo(path: Path) -> None:
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Clone or place the source sub-tree "
            f"there first."
        )
    if not (path / ".git").exists():
        raise SystemExit(
            f"{path} is not a git repository. Run `cd {path} && git init "
            "&& git add . && git commit -m 'initial import'` (or clone "
            "an upstream into that directory)."
        )


def _top_of(tree_path: Path) -> str:
    """Return the <top> name for a sub-tree path (last segment)."""
    return tree_path.name


def build_manifest(tree: Path, *, remote: str, branch: str,
                   do_fetch: bool, max_commits: int) -> dict:
    _ensure_git_repo(tree)
    if do_fetch:
        try:
            _git(["fetch", remote, branch], tree)
        except SystemExit as e:
            print(f"[sync_subtree] WARN: fetch skipped ({e})", file=sys.stderr)

    head = _git(["rev-parse", "HEAD"], tree).strip()
    cov = Coverage.load()
    top = _top_of(tree)
    last = cov.subtree_shas.get(top)

    manifest = {
        "tree": str(tree),
        "from": last,
        "to": head,
        "files": [],
        "commits": [],
    }
    if not last or last == head:
        return manifest

    # File paths are emitted relative to KERNEL_ROOT (= raw/), so a
    # `git diff` "<file>" line of `mlme.c` becomes `<top>/mlme.c`.
    name_only = _git(
        ["diff", "--name-only", f"{last}..{head}"], tree
    ).strip()
    manifest["files"] = [
        f"{top}/{f}" for f in name_only.split("\n") if f
    ]

    log = _git(
        ["log", "--oneline", f"-{max_commits}", f"{last}..{head}"], tree
    ).strip()
    manifest["commits"] = [c for c in log.split("\n") if c]
    return manifest


def _record_new_sha(top: str, new_sha: str) -> None:
    cov = Coverage.load()
    cov.subtree_shas[top] = new_sha
    cov.save()


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--tree", required=True,
                   help="sub-tree path, e.g. raw/pcie_scsc")
    p.add_argument("--remote", default="origin",
                   help="git remote to fetch (default: origin)")
    p.add_argument("--branch", default="main",
                   help="branch to fetch (default: main)")
    p.add_argument("--no-fetch", action="store_true",
                   help="skip `git fetch`; diff against current local HEAD")
    p.add_argument("--max-commits", type=int, default=200,
                   help="cap on commit subjects included in the manifest")
    p.add_argument("--record", action="store_true",
                   help="update coverage.subtree_shas[<top>] to HEAD after "
                        "emitting the manifest")
    p.add_argument("--out", help="write manifest to this path (in addition "
                                 "to stdout)")
    args = p.parse_args(argv)

    tree = Path(args.tree)
    if not tree.is_absolute():
        # Resolve relative to repo root so cron jobs work from any cwd.
        tree = (KERNEL_ROOT.parent / tree).resolve()

    manifest = build_manifest(
        tree,
        remote=args.remote,
        branch=args.branch,
        do_fetch=not args.no_fetch,
        max_commits=args.max_commits,
    )
    text = json.dumps(manifest, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    if args.record:
        _record_new_sha(_top_of(tree), manifest["to"])
        print(f"[sync_subtree] coverage.subtree_shas[{_top_of(tree)!r}] "
              f":= {manifest['to']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
