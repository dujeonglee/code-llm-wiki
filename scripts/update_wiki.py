"""Wiki generate / update / query core.

Three subcommands:

* ``seed-agent`` — fill in a seeded stub page (created by ``seed_pages.sh``)
                   by running an agentic loop via the Claude Agent SDK. The
                   agent uses Read/Grep to navigate the covered sub-tree
                   itself and writes a SOP-formatted page in one final
                   assistant message. Works with Anthropic cloud or any
                   Anthropic-compatible backend (ollama via
                   ``ANTHROPIC_BASE_URL=http://localhost:11434``).
* ``update``     — patch-driven update of existing pages, consuming the
                   JSON from ``patch_router.py``. Only pages whose
                   ``covers`` match files in the manifest are re-synced.
* ``query``      — run a templated question (code-review / porting-guide /
                   feature-impl) using selected wiki pages as grounded
                   context. Output is a query artifact under wiki/queries/
                   with full provenance (template, kernel sha, source
                   pages + their last_synced_sha at query time, LLM
                   profile/model, timestamp). The artifact is for AUDIT
                   TRAIL only — see CLAUDE.md §3.3 on the no-reuse rule.

``update`` and ``query`` use ``scripts.llm_client`` (one-shot HTTP) and
support ``--mock-llm``. ``seed-agent`` uses ``claude-agent-sdk`` (install
separately) and has no mock — the agent loop is exercised by live calls
only.

Examples
--------

::

    # fill an already-stubbed page using a local ollama model
    export ANTHROPIC_BASE_URL=http://localhost:11434
    export ANTHROPIC_AUTH_TOKEN=ollama
    python -m scripts.update_wiki seed-agent \\
        --page raw/pcie_scsc/mlme.md --model qwen3.6:27b-q4_K_M

    # patch-driven update from a routing decision
    python -m scripts.sync_kernel | python -m scripts.patch_router --out r.json
    python -m scripts.update_wiki update --routing r.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts import llm_client
from scripts._meta_io import (
    Coverage,
    KERNEL_ROOT,
    WIKI_ROOT,
    extract_markdown_block,
    now_iso,
    parse_front_matter,
    serialize_page,
)

# ---------------------------------------------------------------------------
# Prompts. The system prompt is intentionally stable so Anthropic prompt
# caching takes effect; per-page details go in the user message.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You maintain a Wikipedia-style code wiki following the Karpathy LLM-Wiki
pattern. The wiki documents one or more source sub-trees under `raw/<top>/`.
Hard rules:

1. The source tree at `raw/<top>/` is IMMUTABLE. You are documenting it, not
   modifying it.
2. Every page begins with YAML front-matter. The schema is:

       ---
       title: <human readable name>
       kind: subsystem | concept | entity | query
       covers:                # globs, relative to KERNEL_ROOT (= raw/)
         - <path>
       last_synced_sha: <sub-tree git sha or null>
       last_synced: <ISO-8601 UTC datetime or null>
       sources:               # files you actually read; may include line refs
         - <path or path#Lstart-Lend>
       ---

3. Cross-link with Obsidian-style [[wiki-links]]. Use the page path relative
   to wiki/ as the link target, e.g. `[[concepts/rcu|RCU]]`.
4. Be concrete. Reference function names, struct names, and file paths.
   Use fenced code blocks for C snippets and Mermaid for diagrams.
5. NEVER fabricate symbols. If unsure, omit rather than invent.
6. For UPDATE tasks: patch only the affected sections, preserve the rest of
   the page verbatim, and keep `covers` unchanged unless coverage genuinely
   shifted. Append a short bullet under "## Recent changes" describing the
   patch.
7. For SEED tasks: 2-3 sentence summary, then "## Key data structures",
   "## Key entry points", "## Related" (with wiki-links), and an empty
   "## Recent changes" section.
8. Output format: respond with the FULL updated page (front-matter + body)
   inside a single ```markdown ... ``` fenced block. No prose outside the
   fence.
"""


# ---------------------------------------------------------------------------
# Mock LLM (offline)
# ---------------------------------------------------------------------------

def _mock_llm(messages: list[dict[str, Any]], *, system: str | None,
              profile: str | None, max_tokens: int | None = None,
              temperature: float | None = None,
              cache_system: bool = True) -> llm_client.ChatResult:
    """Deterministic templated response for offline testing of cmd_update."""
    user = messages[-1]["content"]
    cur_block = ""
    if "CURRENT PAGE:" in user:
        after = user.split("CURRENT PAGE:", 1)[1]
        # The page is wrapped in a ```markdown fence in the prompt; strip it.
        after = after.split("```markdown", 1)[-1]
        cur_block = after.split("```", 1)[0]
        # leading whitespace must go so parse_front_matter sees '---' first.
        cur_block = cur_block.lstrip("\n ").rstrip() + "\n"
    sha = "unknown"
    for ln in user.splitlines():
        if ln.startswith("TO SHA:"):
            sha = ln.split(":", 1)[1].strip()
            break
    fm, body = parse_front_matter(cur_block)
    fm["last_synced_sha"] = sha
    fm["last_synced"] = now_iso()
    if "## Recent changes" not in body:
        body += "\n## Recent changes\n"
    body = body.rstrip() + f"\n- {now_iso()}: mock-update at {sha}.\n"
    return llm_client.ChatResult(
        text="```markdown\n" + serialize_page(fm, body) + "```\n",
        usage={"mock": True}, model="mock", raw={})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_page(rel: str) -> tuple[dict[str, Any], str] | None:
    p = WIKI_ROOT / rel
    if not p.exists():
        return None
    return parse_front_matter(p.read_text())


def _write_page(rel: str, fm: dict[str, Any], body: str) -> Path:
    p = WIKI_ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(serialize_page(fm, body))
    return p


def _git_diff(kernel_dir: Path, from_sha: str, to_sha: str,
              paths: list[str], max_bytes: int = 60_000) -> str:
    if not paths:
        return ""
    cmd = ["git", "-C", str(kernel_dir), "diff", "--unified=3",
           f"{from_sha}..{to_sha}", "--"]
    cmd.extend(paths)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return "[no git available]"
    if out.returncode != 0:
        return f"[diff failed rc={out.returncode}: {out.stderr.strip()}]"
    text = out.stdout
    if len(text) > max_bytes:
        text = text[:max_bytes] + "\n... [truncated]\n"
    return text


# ---------------------------------------------------------------------------
# SEED (agentic)
# ---------------------------------------------------------------------------

AGENT_SUFFIX = """

You are now an agent with read-only access to the source tree. Tools:
- Read(file_path, offset, limit) — fetch any line range from any file.
- Grep(pattern, path) — search for symbol uses across the sub-tree.

Do NOT use Edit/Write/Bash. Your output is the final assistant message only.
Explore enough to identify: the module's purpose, its top-level entry points
(function names + signatures), key data structures (struct/enum names), and
how it connects to neighboring modules (which functions it calls, who calls
it). When ready, output the FULL page — front-matter + body — inside ONE
```markdown ... ``` fenced block, and nothing else after the fence.

Wiki layout (IMPORTANT for [[wiki-links]]):
Pages live at `wiki/raw/<top>/<basename>.md`, mirroring the raw/ tree exactly.
The wiki for `raw/pcie_scsc/dev.c` is `wiki/raw/pcie_scsc/dev.md`. Link
targets are page paths relative to `wiki/`, so a cross-link to that page is
`[[raw/pcie_scsc/dev|dev]]` — NOT `[[dev]]`, NOT `[[pcie_scsc/dev]]`, and
NOT `[[subsystems/dev]]`. Only link to pages you can verify exist (Read or
Grep the wiki/raw/ tree if unsure); omit the link rather than invent one.
"""


def cmd_seed_agent(args: argparse.Namespace) -> int:
    """Synchronous wrapper around the async agentic-seed flow."""
    import asyncio
    return asyncio.run(_cmd_seed_agent_async(args))


async def _cmd_seed_agent_async(args: argparse.Namespace) -> int:
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )
    except ImportError as e:
        print(f"[seed-agent] missing dependency: {e}", file=sys.stderr)
        print("Install: pip install claude-agent-sdk", file=sys.stderr)
        return 4

    page_rel = args.page
    if not page_rel.endswith(".md"):
        page_rel += ".md"
    page_path = WIKI_ROOT / page_rel
    if not page_path.exists():
        print(f"[seed-agent] page stub not found: {page_rel}",
              file=sys.stderr)
        print("Run scripts/seed_pages.sh first to create stubs.",
              file=sys.stderr)
        return 2
    cur_fm, _ = parse_front_matter(page_path.read_text())
    covers = cur_fm.get("covers") or []
    if not covers:
        print(f"[seed-agent] {page_rel} has no covers in front-matter",
              file=sys.stderr)
        return 2
    if cur_fm.get("last_synced") and not args.overwrite:
        print(f"[seed-agent] {page_rel} already filled "
              f"(last_synced={cur_fm['last_synced']}); use --overwrite",
              file=sys.stderr)
        return 2

    sub_root = f"raw/{covers[0].split('/', 1)[0]}/"
    user_prompt = (
        f"TASK: SEED (agentic)\n"
        f"PAGE PATH: {page_rel}\n"
        f"KIND: {cur_fm.get('kind', 'entity')}\n"
        f"COVERS: {', '.join(covers)}\n"
        f"SUB-TREE ROOT (read paths from here): {sub_root}\n"
        f"\nCURRENT PAGE (stub to overwrite):\n"
        f"```markdown\n{page_path.read_text()}```\n"
        f"\nRead the covered files first, then expand to neighbors via "
        f"Grep on function/struct names you find. Aim for a Wikipedia-"
        f"quality summary with concrete symbols, not generic prose.\n"
    )

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT + AGENT_SUFFIX,
        allowed_tools=["Read", "Grep"],
        model=args.model,
        max_turns=args.max_turns,
        permission_mode="bypassPermissions",
    )

    final_text = ""
    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text, end="", file=sys.stderr, flush=True)
                    final_text += block.text
    print(file=sys.stderr)

    page_text = extract_markdown_block(final_text)
    new_fm, new_body = parse_front_matter(page_text)
    if not new_fm:
        print("[seed-agent] response had no front matter; refusing to write",
              file=sys.stderr)
        print(final_text[:500], file=sys.stderr)
        return 3

    merged = dict(cur_fm)
    merged.update(new_fm)
    # Cover list is owned by seed_pages.sh; the agent must not edit it.
    merged["covers"] = covers
    subtree = _resolve_subtree(covers)
    merged["last_synced_sha"] = _git_head(subtree)
    merged["last_synced"] = now_iso()

    if args.dry_run:
        print(serialize_page(merged, new_body))
        return 0

    _write_page(page_rel, merged, new_body)

    cov = Coverage.load()
    cov.pages.setdefault(page_rel, {})
    cov.pages[page_rel].update({
        "kind": merged.get("kind", "entity"),
        "covers": covers,
        "last_synced_sha": merged["last_synced_sha"],
        "last_synced": merged["last_synced"],
    })
    cov.save()

    print(f"[seed-agent] wrote {page_rel} ({len(new_body)} bytes), "
          f"head={merged['last_synced_sha']}")
    return 0


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

def run_update(routing: dict[str, Any], *, kernel_dir: Path,
               profile: str | None, mock_llm: bool, dry_run: bool,
               max_diff_bytes: int = 60_000) -> tuple[int, int]:
    """Programmatic entry point used by ``cmd_update`` and ``anneal.py``.

    Returns ``(written, total)`` — how many pages were actually written and
    how many were attempted.
    """
    from_sha = routing.get("from")
    to_sha = routing.get("to")
    pages = routing.get("affected_pages", [])
    if not pages:
        print("[update] routing has no affected_pages; nothing to do")
        return 0, 0
    cov = Coverage.load()

    written = 0
    for page_rel in pages:
        page = _read_page(page_rel)
        if page is None:
            print(f"[update] WARN: {page_rel} listed but file missing; skip",
                  file=sys.stderr)
            continue
        fm, body = page
        covers = list(fm.get("covers") or
                      cov.pages.get(page_rel, {}).get("covers", []))
        diff = ""
        if from_sha and to_sha and from_sha != to_sha:
            diff = _git_diff(kernel_dir, from_sha, to_sha, covers,
                             max_bytes=max_diff_bytes)

        user_msg = (
            f"TASK: UPDATE\n"
            f"PAGE PATH: {page_rel}\n"
            f"FROM SHA: {from_sha}\n"
            f"TO SHA: {to_sha}\n"
            f"COVERS: {', '.join(covers)}\n"
            f"\nCURRENT PAGE:\n```markdown\n{serialize_page(fm, body)}```\n"
            f"\nCOMMITS:\n" + "\n".join(routing.get("commits", [])[:50])
            + f"\n\nDIFF:\n```diff\n{diff or '(no diff available)'}\n```\n"
        )

        call = _mock_llm if mock_llm else llm_client.chat
        res = call(
            [{"role": "user", "content": user_msg}],
            system=SYSTEM_PROMPT,
            profile=profile,
        )
        page_text = extract_markdown_block(res.text)
        new_fm, new_body = parse_front_matter(page_text)
        if not new_fm:
            print(f"[update] WARN: {page_rel} response missing front matter; "
                  "skip", file=sys.stderr)
            continue
        # Merge: start from the page's current fm so fields the LLM dropped
        # (title, kind, sources, ...) survive. Then overlay the LLM's edits.
        # Then force the fields we always control.
        merged = dict(fm)
        merged.update(new_fm)
        merged["covers"] = covers
        merged["last_synced_sha"] = to_sha
        merged["last_synced"] = now_iso()
        new_fm = merged

        if dry_run:
            print(f"--- {page_rel} ---")
            print(serialize_page(new_fm, new_body))
            continue
        _write_page(page_rel, new_fm, new_body)
        cov.pages.setdefault(page_rel, {})
        cov.pages[page_rel].update({
            "kind": cov.pages.get(page_rel, {}).get("kind",
                                                   new_fm.get("kind", "concept")),
            "covers": covers,
            "last_synced_sha": to_sha,
            "last_synced": new_fm["last_synced"],
        })
        written += 1

    if not dry_run and to_sha:
        cov.last_kernel_sha = to_sha
        cov.save()
    print(f"[update] {written}/{len(pages)} pages updated, "
          f"last_kernel_sha := {to_sha}")
    return written, len(pages)


def cmd_update(args: argparse.Namespace) -> int:
    routing = json.loads(Path(args.routing).read_text())
    run_update(
        routing,
        kernel_dir=KERNEL_ROOT,
        profile=args.profile,
        mock_llm=args.mock_llm,
        dry_run=args.dry_run,
        max_diff_bytes=args.max_diff_bytes,
    )
    return 0


# ---------------------------------------------------------------------------
# QUERY (D7-lite)
# ---------------------------------------------------------------------------
#
# Provenance philosophy (CLAUDE.md §3.3):
# - We RECORD what the LLM saw (template, source pages + their sha at query
#   time, kernel sha, model). This is an audit trail.
# - We DO NOT compute a "freshness" badge or auto-refresh, because doing so
#   risks giving the artifact false authority (a green badge means "sources
#   haven't moved", not "the conclusion is still right").
# - Saved queries are SINGLE-USE for code-review, RESEARCH-STARTING-POINT
#   for porting, and TEMPORARY for feature-impl. If you're unsure, re-run.

TEMPLATE_DIR = WIKI_ROOT / "queries" / "_templates"


def _load_template(template_id: str) -> tuple[dict[str, Any], str]:
    """Return (front_matter, system_prompt_body) for the named template."""
    path = TEMPLATE_DIR / f"{template_id}.md"
    if not path.exists():
        raise SystemExit(
            f"[query] no such template '{template_id}'. Available: "
            f"{[p.stem for p in TEMPLATE_DIR.glob('*.md')]}"
        )
    fm, body = parse_front_matter(path.read_text())
    # The template body has both "# System prompt" and "# User message
    # scaffold" sections. We want only the system-prompt half.
    if "# User message scaffold" in body:
        system = body.split("# User message scaffold", 1)[0]
    else:
        system = body
    # Strip the "# System prompt" heading itself.
    if system.lstrip().startswith("# System prompt"):
        system = system.split("\n", 1)[1] if "\n" in system else system
    return fm, system.strip() + "\n"


def _load_wiki_context(page_rels: list[str], cov: Coverage,
                       max_chars_per_page: int = 6000
                       ) -> tuple[str, list[str]]:
    """Build the WIKI CONTEXT string for the user message, and a parallel
    list of ``"path@sha"`` provenance records (or ``"path@missing"``).
    Kept as plain strings so they serialise cleanly into YAML front-matter
    without needing a full YAML library."""
    chunks: list[str] = []
    sources: list[str] = []
    for rel in page_rels:
        page = _read_page(rel)
        if page is None:
            sources.append(f"{rel}@missing")
            continue
        fm, body = page
        sha = (fm.get("last_synced_sha")
               or cov.pages.get(rel, {}).get("last_synced_sha")
               or "unknown")
        sources.append(f"{rel}@{sha}")
        trimmed = body if len(body) <= max_chars_per_page else (
            body[:max_chars_per_page] + "\n... [page truncated for query]\n")
        chunks.append(
            f"### [[{rel}]] (last_synced_sha={sha})\n\n{trimmed.rstrip()}\n"
        )
    return "\n".join(chunks), sources


def _mock_llm_query(messages: list[dict[str, Any]], *, system: str | None,
                    profile: str | None, max_tokens: int | None = None,
                    temperature: float | None = None,
                    cache_system: bool = True) -> llm_client.ChatResult:
    """Deterministic stub for query tests / offline rehearsal."""
    user = messages[-1]["content"]
    template_line = next((ln for ln in user.splitlines()
                          if ln.startswith("TASK:")), "TASK: unknown")
    template = template_line.split(":", 1)[1].strip()
    body = (
        "## Summary\n"
        f"_(mock-LLM {template} response — replace with a real run.)_\n\n"
        "## Affected wiki areas\n"
        "- (none cited by the mock)\n\n"
        "## Risks\n"
        "- (mock did not analyse risks)\n"
    )
    return llm_client.ChatResult(
        text=body, usage={"mock": True}, model="mock", raw={})


def _git_head(kernel_dir: Path | None) -> str | None:
    if kernel_dir is None or not (kernel_dir / ".git").exists():
        return None
    try:
        return subprocess.check_output(
            ["git", "-C", str(kernel_dir), "rev-parse", "HEAD"],
            text=True).strip()
    except subprocess.CalledProcessError:
        return None


def _resolve_subtree(covers: list[str]) -> Path | None:
    """Resolve the per-sub-tree git root from a page's covers.

    Returns ``KERNEL_ROOT / <first segment>`` if all non-empty covers share
    a common first path segment and that path exists. Returns ``None`` for
    empty covers, covers that span multiple sub-trees, or a missing path.
    Asking git at ``KERNEL_ROOT`` itself walks up to the wiki repo, which
    is the wrong sha to record on a page; this helper keeps sha resolution
    scoped to each raw/<top>/ tree.
    """
    segs = {c.split("/", 1)[0] for c in covers if c}
    if len(segs) != 1:
        return None
    sub = KERNEL_ROOT / segs.pop()
    return sub if sub.exists() else None


def cmd_query(args: argparse.Namespace) -> int:
    fm_tpl, system_prompt = _load_template(args.template)
    cov = Coverage.load()
    pages = [p.strip() for p in (args.pages or "").split(",") if p.strip()]
    wiki_context, sources = _load_wiki_context(pages, cov)
    # Resolve "kernel sha at query" from the first page's sub-tree. Pages
    # spanning multiple sub-trees still get correct per-page sha via the
    # `sources` provenance field.
    first_covers = next(
        (cov.pages.get(p, {}).get("covers") or [] for p in pages
         if cov.pages.get(p, {}).get("covers")),
        [],
    )
    kernel_sha = _git_head(_resolve_subtree(first_covers)) or cov.last_kernel_sha

    # Build the task-specific user message.
    if args.template == "code-review":
        if not args.input:
            raise SystemExit("[query] code-review needs --input <patch-file>")
        payload = Path(args.input).read_text()
        user_body = (
            f"TASK: code-review\n"
            f"PATCH:\n```diff\n{payload}\n```\n\n"
            f"WIKI CONTEXT ({len(pages)} page(s)):\n{wiki_context}\n\n"
            f"KERNEL SHA AT QUERY: {kernel_sha}\n"
        )
    elif args.template == "porting-guide":
        if not (args.target_os and args.feature):
            raise SystemExit(
                "[query] porting-guide needs --target-os and --feature"
            )
        user_body = (
            f"TASK: porting-guide\n"
            f"TARGET OS: {args.target_os}\n"
            f"FEATURE: {args.feature}\n"
            f"CONSTRAINTS: {args.constraints or '(none)'}\n\n"
            f"WIKI CONTEXT ({len(pages)} page(s)):\n{wiki_context}\n\n"
            f"KERNEL SHA AT QUERY: {kernel_sha}\n"
        )
    elif args.template == "feature-impl":
        if not args.feature:
            raise SystemExit("[query] feature-impl needs --feature")
        user_body = (
            f"TASK: feature-impl\n"
            f"FEATURE: {args.feature}\n"
            f"CONSTRAINTS: {args.constraints or '(none)'}\n\n"
            f"WIKI CONTEXT ({len(pages)} page(s)):\n{wiki_context}\n\n"
            f"KERNEL SHA AT QUERY: {kernel_sha}\n"
        )
    else:
        raise SystemExit(f"[query] unknown template '{args.template}'")

    call = _mock_llm_query if args.mock_llm else llm_client.chat
    res = call(
        [{"role": "user", "content": user_body}],
        system=system_prompt,
        profile=args.profile,
    )

    # Provenance front-matter for the saved artifact.
    # `sources` is the authoritative audit record: each entry is
    # "<wiki path>@<last_synced_sha at query time>" (or "...@missing").
    fm: dict[str, Any] = {
        "title": args.title or f"{args.template} query",
        "kind": "query",
        "template": args.template,
        "produced": now_iso(),
        "kernel_sha_at_query": kernel_sha,
        "llm_profile": args.profile or "(default)",
        "llm_model": res.model,
        "sources": sources,
        "reuse_policy": {
            "code-review":   "single-use audit only — never reuse for a "
                             "different patch",
            "porting-guide": "research starting point only — re-run when "
                             "you actually port",
            "feature-impl":  "valid until the feature lands — archive after",
        }.get(args.template, "single-use audit only"),
    }
    page_text = serialize_page(fm, res.text)

    if args.dry_run:
        print(page_text)
        return 0

    out_path = Path(args.out) if args.out else (
        WIKI_ROOT / "queries" /
        f"{now_iso().replace(':', '').replace('-', '')[:13]}-{args.template}.md"
    )
    if not out_path.is_absolute():
        out_path = WIKI_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page_text)
    rel = out_path.relative_to(WIKI_ROOT).as_posix() if out_path.is_relative_to(WIKI_ROOT) else str(out_path)
    print(f"[query] wrote {rel} ({len(page_text)} bytes) "
          f"template={args.template} sources={len(sources)}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="LLM profile (default: per config)")
    common.add_argument("--mock-llm", action="store_true",
                        help="use deterministic stub (no API call)")
    common.add_argument("--dry-run", action="store_true",
                        help="print result without touching the wiki tree")

    s = sub.add_parser("seed-agent", parents=[common],
                       help="fill a stubbed page via the Claude Agent SDK")
    s.add_argument("--page", required=True,
                   help="path relative to wiki/ (must already exist as a "
                        "stub from seed_pages.sh)")
    s.add_argument("--model", required=True,
                   help="model name (e.g. claude-sonnet-4-5 for the "
                        "Anthropic cloud, qwen3.6:27b-q4_K_M for ollama)")
    s.add_argument("--max-turns", type=int, default=25,
                   help="agent turn cap (default: 25)")
    s.add_argument("--overwrite", action="store_true",
                   help="refill a page even if last_synced is already set")
    s.set_defaults(func=cmd_seed_agent)

    u = sub.add_parser("update", parents=[common],
                       help="patch-driven update from a routing decision")
    u.add_argument("--routing", required=True,
                   help="routing JSON from patch_router.py")
    u.add_argument("--max-diff-bytes", type=int, default=60_000)
    u.set_defaults(func=cmd_update)

    q = sub.add_parser("query", parents=[common],
                       help="run a templated question (code-review / "
                            "porting-guide / feature-impl)")
    q.add_argument("--template", required=True,
                   choices=["code-review", "porting-guide", "feature-impl"])
    q.add_argument("--out", help="path under wiki/queries/ (default: "
                                 "auto-named with timestamp)")
    q.add_argument("--title", help="title for the produced page")
    q.add_argument("--pages",
                   help="comma-separated wiki/ pages to use as context")
    q.add_argument("--input",
                   help="path to the task-specific input (e.g. patch diff "
                        "for code-review)")
    q.add_argument("--target-os", help="porting-guide: target OS / runtime")
    q.add_argument("--feature",
                   help="porting-guide / feature-impl: feature description")
    q.add_argument("--constraints",
                   help="porting-guide / feature-impl: extra constraints")
    q.set_defaults(func=cmd_query)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
