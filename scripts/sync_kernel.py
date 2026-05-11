"""Fetch the kernel tree and emit a manifest of changed files.

Specifying the kernel git repo
------------------------------

The kernel source tree lives **outside** this repo (it's huge and we never
commit it). You point ``sync_kernel.py`` at it in one of three ways, in order
of precedence:

1. **CLI flag** (highest priority, one-off override) ::

       python -m scripts.sync_kernel --kernel-dir /work/linux \\
                                     --remote origin --branch master

2. **Environment variables** (per-shell or CI secret) ::

       export KERNEL_DIR=/work/linux
       export KERNEL_REMOTE=stable          # default: origin
       export KERNEL_BRANCH=linux-6.6.y     # default: master
       python -m scripts.sync_kernel

3. **Default path** ``raw/linux/`` inside this repo. The simplest layout for
   most users — just clone the kernel there::

       # full mainline:
       git clone https://github.com/torvalds/linux raw/linux

       # OR: stable LTS branch only (recommended for cron'd updates):
       git clone -b linux-6.6.y --single-branch \\
           https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git \\
           raw/linux

       # OR: just one or two subsystems (fast, tiny):
       git clone --filter=blob:none --no-checkout \\
           https://github.com/torvalds/linux raw/linux
       cd raw/linux && git sparse-checkout init --cone
       git sparse-checkout set mm net/core
       git checkout master

You can also use a symlink (e.g. ``raw/linux -> /work/linux``) if you already
have a kernel checkout elsewhere on the machine.

How the diff is computed
------------------------

``wiki/_meta/coverage.json`` holds ``last_kernel_sha`` — the commit this wiki
was last synced against. On the very first run it is ``null``, so we record
the current ``HEAD`` and emit an empty file list (no retroactive
documentation of the entire kernel; D3 and the annealer fill in pages
lazily). On subsequent runs we ``git diff last_kernel_sha..HEAD`` and emit
the changed files.

Output
------

JSON on stdout, of the form::

    {
      "from": "<sha or null>",
      "to":   "<sha>",
      "files": ["mm/slab.c", "net/core/dev.c", ...],
      "commits": ["<sha> <subject>", ...]   # at most --max-commits
    }

Side effects
------------

None by default. With ``--record``, updates ``coverage.json``'s
``last_kernel_sha`` to the new HEAD so the next run picks up where this one
left off. The wiki updater (D3) should be the one to call ``--record`` after
it successfully writes the affected pages.
"""
from __future__ import annotations

import argparse
import json
import os
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
            f"{path} does not exist. Place the kernel source tree there "
            "(e.g. `git clone https://github.com/torvalds/linux raw/linux`)."
        )
    if not (path / ".git").exists() and not (path.parent / ".git").exists():
        raise SystemExit(
            f"{path} is not a git repository. The patch router needs git "
            "history to compute incremental diffs."
        )


def build_manifest(kernel_dir: Path, *, remote: str, branch: str,
                   do_fetch: bool, max_commits: int) -> dict:
    _ensure_git_repo(kernel_dir)
    if do_fetch:
        try:
            _git(["fetch", remote, branch], kernel_dir)
        except SystemExit as e:
            # Offline / no remote: warn and continue against local HEAD
            print(f"[sync_kernel] WARN: fetch skipped ({e})", file=sys.stderr)

    head = _git(["rev-parse", "HEAD"], kernel_dir).strip()
    cov = Coverage.load()
    last = cov.last_kernel_sha

    if not last:
        return {"from": None, "to": head, "files": [], "commits": []}
    if last == head:
        return {"from": last, "to": head, "files": [], "commits": []}

    name_only = _git(
        ["diff", "--name-only", f"{last}..{head}"], kernel_dir
    ).strip()
    files = [f for f in name_only.split("\n") if f]

    log = _git(
        ["log", "--oneline", f"-{max_commits}", f"{last}..{head}"], kernel_dir
    ).strip()
    commits = [c for c in log.split("\n") if c]

    return {"from": last, "to": head, "files": files, "commits": commits}


def _record_new_sha(new_sha: str) -> None:
    cov = Coverage.load()
    cov.last_kernel_sha = new_sha
    cov.save()


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    # Where the kernel checkout lives. Resolution: CLI flag > $KERNEL_DIR
    # env var > default raw/linux/ inside this repo. See the module docstring
    # for clone recipes (full mainline / LTS branch / sparse subsystem).
    p.add_argument("--kernel-dir",
                   default=os.environ.get("KERNEL_DIR", str(KERNEL_ROOT)),
                   help=("kernel git tree to read from. "
                         "Defaults to $KERNEL_DIR, then raw/linux/."))
    # Which git remote to fetch updates from. Override when you mirror from
    # stable/, linux-next, or a fork.
    p.add_argument("--remote",
                   default=os.environ.get("KERNEL_REMOTE", "origin"),
                   help="git remote name. Defaults to $KERNEL_REMOTE or 'origin'.")
    # Branch to track. For LTS pinning set this to e.g. 'linux-6.6.y'.
    p.add_argument("--branch",
                   default=os.environ.get("KERNEL_BRANCH", "master"),
                   help="branch to fetch. Defaults to $KERNEL_BRANCH or 'master'.")
    p.add_argument("--no-fetch", action="store_true",
                   help="skip `git fetch`, use whatever is in the tree "
                        "(useful for offline tests and CI replay)")
    p.add_argument("--max-commits", type=int, default=200,
                   help="cap on commit subjects included in the manifest")
    p.add_argument("--record", action="store_true",
                   help="update coverage.last_kernel_sha to HEAD after "
                        "emitting the manifest")
    p.add_argument("--out", help="write manifest to this path (in addition "
                                 "to stdout)")
    args = p.parse_args(argv)

    manifest = build_manifest(
        Path(args.kernel_dir),
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
        _record_new_sha(manifest["to"])
        print(f"[sync_kernel] coverage.last_kernel_sha := {manifest['to']}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
