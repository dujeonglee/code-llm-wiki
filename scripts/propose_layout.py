"""LLM-proposed wiki layout for a raw/<top>/ sub-tree.

Runs an agentic loop (claude-agent-sdk with Read/Grep) against the
sub-tree and emits a YAML proposal of `subsystem` and `concept` pages
that should exist alongside the per-translation-unit `entity` stubs
that ``seed_pages.sh`` already creates.

Output is a single YAML file. The body lists the proposed pages; the
front-matter records provenance (template, sha, model, time) so the
proposal itself is auditable. Run ``scripts/apply_layout.py`` on the
file to materialise stubs and update ``coverage.json``.

::

    python -m scripts.propose_layout --tree raw/pcie_scsc \\
        --model qwen3.6:27b-q4_K_M

Defaults emit to
``wiki/_meta/layout-proposals/<top>-<YYYYMMDD-HHMMSS>.yaml``.

Why two scripts (propose + apply)?
----------------------------------

The LLM call decides the **layout** (what pages should exist, with what
covers globs and a one-line rationale). Materialising stubs is
deterministic — front-matter serialisation + coverage.json merge — and
already exists as plumbing. Keeping them separate means:

* The YAML proposal is a reviewable, diff-friendly artifact;
* Idempotency and validation live in one stable place (apply_layout);
* Re-running ``propose_layout`` after a sub-tree restructure produces a
  diff against the previous proposal, not against scattered stub files.

Schema of the body (parsed by ``apply_layout.py``)::

    subsystems:
      - title:     "SCSC MLME Subsystem"
        basename:  _mlme_overview       # → wiki/raw/<top>/_mlme_overview.md
        covers:    [pcie_scsc/mlme*.c, pcie_scsc/sap_mlme.c]
        rationale: "..."

    concepts:
      - title:     "FAPI Signaling Protocol"
        basename:  _fapi
        covers:    [pcie_scsc/fapi.h, pcie_scsc/mlme.c, pcie_scsc/sap_*.c]
        rationale: "..."
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import llm_client
from scripts._meta_io import KERNEL_ROOT, WIKI_ROOT, now_iso, serialize_page


SYSTEM_PROMPT = """\
You are proposing a wiki layout for a single source sub-tree under
`raw/<top>/`. The wiki SOP allows four `kind`s:

* `entity`    — one per translation unit (a .c with its same-name .h),
                already created by `seed_pages.sh`. Do NOT propose these.
* `subsystem` — a cohesive multi-file unit with strong internal
                coupling (e.g., "MLME", "HIP transport"). Covers globs
                span those files.
* `concept`   — a cross-cutting protocol, abstraction, or contract that
                is touched by many files but does not own them
                (e.g., "FAPI signaling protocol", "TWT scheduling").
* `query`     — auto-generated audit artifacts; never propose.

For each `subsystem` and `concept` you identify, output one YAML entry
with these fields:

* `title`     — human-readable page title.
* `basename`  — file stem under `wiki/raw/<top>/`. Prefix with `_` to
                sort it apart from entity pages (e.g. `_mlme_overview`).
* `covers`    — list of glob(s) relative to `raw/` (so
                `pcie_scsc/mlme*.c`, not `mlme*.c`).
* `rationale` — one or two sentences explaining why this grouping is
                a real architectural unit (cite specific functions or
                types if helpful).

Be selective. A typical sub-tree has maybe 3-8 subsystems and 2-5
concepts. Do NOT propose a subsystem for every C file; do NOT propose
concepts that are just "utilities" or "helpers". If unsure whether
something is a subsystem or a concept, prefer omitting it.

Output format: ONE ```yaml ... ``` fenced block, body matching:

    subsystems:
      - title: "..."
        basename: "..."
        covers: ["...", "..."]
        rationale: "..."
    concepts:
      - title: "..."
        basename: "..."
        covers: ["...", "..."]
        rationale: "..."

Nothing outside the fence.
"""


AGENT_SUFFIX = """

You have read-only Read/Grep tools. Read selectively — do not dump
whole files. Aim to:

1. Read the directory listing and the most-included headers first
   (fapi.h, dev.h, the public API headers) to find type / message
   names that recur across files.
2. Grep for those names to see which .c files form a cluster.
3. From the clusters, propose subsystem entries.
4. From the recurring types/protocols that span clusters, propose
   concept entries.

Do NOT use Edit/Write/Bash. Your final assistant message must be the
```yaml ... ``` block and nothing else.
"""


def _git_head_of(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None


def _extract_yaml(text: str) -> str | None:
    """Pull the inner content of the outer ```yaml ... ``` fence."""
    m = re.search(
        r"```(?:yaml|yml)?\s*\n(.*)\n```\s*(?:\n|\Z)",
        text,
        flags=re.DOTALL,
    )
    return m.group(1).rstrip() + "\n" if m else None


async def _propose(tree: Path, *, model: str, max_turns: int) -> str:
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )
    except ImportError as e:
        raise SystemExit(
            f"[propose-layout] missing dependency: {e}\n"
            "Install: pip install claude-agent-sdk"
        )

    top = tree.name
    user_prompt = (
        f"TASK: WIKI LAYOUT PROPOSAL\n"
        f"TREE: {tree}\n"
        f"TOP NAME (for basename hints): {top}\n"
        f"COVERS PREFIX (use this in every cover glob): {top}/\n"
        f"\nExplore the sub-tree, then output the YAML proposal."
    )

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT + AGENT_SUFFIX,
        allowed_tools=["Read", "Grep"],
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
    )

    text = ""
    async for msg in query(prompt=user_prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for blk in msg.content:
                if isinstance(blk, TextBlock):
                    print(blk.text, end="", file=sys.stderr, flush=True)
                    text += blk.text
    print(file=sys.stderr)
    return text


def _run(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--tree", required=True,
                   help="sub-tree path, e.g. raw/pcie_scsc")
    p.add_argument("--model", required=True,
                   help="model name passed to claude-agent-sdk")
    p.add_argument("--profile",
                   help="llm.json profile (default: per config)")
    p.add_argument("--max-turns", type=int, default=20,
                   help="agent turn cap (default: 20)")
    p.add_argument("--out",
                   help="output YAML path (default: wiki/_meta/"
                        "layout-proposals/<top>-<timestamp>.yaml)")
    args = p.parse_args(argv)

    tree = Path(args.tree)
    if not tree.is_absolute():
        tree = (REPO_ROOT / tree).resolve()
    if not tree.exists():
        print(f"[propose-layout] tree not found: {tree}", file=sys.stderr)
        return 2

    # Apply backend env vars from the llm.json profile (same path as
    # cmd_seed_agent), so the wiki repo config drives the SDK call.
    try:
        for k, v in llm_client.sdk_env_for_profile(args.profile).items():
            os.environ[k] = v
    except llm_client.LLMError as e:
        print(f"[propose-layout] backend resolution failed: {e}",
              file=sys.stderr)
        return 4

    text = asyncio.run(_propose(tree, model=args.model,
                                max_turns=args.max_turns))
    yaml_body = _extract_yaml(text)
    if not yaml_body:
        print("[propose-layout] response had no ```yaml fence; aborting",
              file=sys.stderr)
        print(text[:500], file=sys.stderr)
        return 3

    # Provenance front-matter (parsed by our existing _meta_io subset).
    fm = {
        "template": "layout-proposal",
        "produced": now_iso(),
        "tree": str(tree.relative_to(REPO_ROOT)),
        "sha": _git_head_of(tree) or "null",
        "llm_profile": args.profile or "(default)",
        "llm_model": args.model,
    }

    if args.out:
        out_path = Path(args.out)
    else:
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = (WIKI_ROOT / "_meta" / "layout-proposals"
                    / f"{tree.name}-{stamp}.yaml")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(serialize_page(fm, yaml_body))

    print(f"[propose-layout] wrote {out_path.relative_to(REPO_ROOT)} "
          f"({len(yaml_body)} bytes of YAML body)")
    print("Review the file, edit if needed, then run:")
    print(f"  python -m scripts.apply_layout {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv[1:]))
