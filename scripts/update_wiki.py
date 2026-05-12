"""Wiki generate / update / query core.

Three subcommands:

* ``seed``   — create a new page from scratch for an area the wiki doesn't
               yet cover. Triggered manually for the very first pages, and
               by the annealer (D4) for ``todo.md`` entries.
* ``update`` — patch-driven update of existing pages, consuming the JSON
               from ``patch_router.py``. Only pages whose ``covers`` match
               files in the manifest are re-synced.
* ``query``  — run a templated question (code-review / porting-guide /
               feature-impl) using selected wiki pages as grounded
               context. Output is a query artifact under wiki/queries/
               with full provenance (template, kernel sha, source pages
               + their last_synced_sha at query time, LLM profile/model,
               timestamp). The artifact is for AUDIT TRAIL only — see
               CLAUDE.md §3.3 on the no-reuse rule.

Both call the same LLM prompt machinery in ``scripts.llm_client``. Both
support ``--mock-llm`` for offline testing — the mock emits a deterministic
templated page so the rest of the pipeline (parse, validate, write,
coverage update) can be exercised without API keys.

Examples
--------

::

    # one-off seed of the mm subsystem page
    python -m scripts.update_wiki seed \\
        --page subsystems/mm.md --kind subsystem \\
        --covers 'mm/*.c' 'mm/*.h'

    # patch-driven update from a routing decision
    python -m scripts.sync_kernel | python -m scripts.patch_router --out r.json
    python -m scripts.update_wiki update --routing r.json

    # offline rehearsal (no API key, no kernel tree needed)
    python -m scripts.update_wiki seed --page subsystems/mm.md \\
        --kind subsystem --covers 'mm/*.c' --mock-llm
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
You maintain a Wikipedia-style code wiki for the Linux kernel, following the
Karpathy LLM-Wiki pattern. Hard rules:

1. The source tree at `raw/linux/` is IMMUTABLE. You are documenting it, not
   modifying it.
2. Every page begins with YAML front-matter. The schema is:

       ---
       title: <human readable name>
       kind: subsystem | concept | entity | query
       covers:                # globs, relative to raw/linux/
         - <path>
       last_synced_sha: <kernel git sha or null>
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
    """Deterministic templated response for offline testing."""
    user = messages[-1]["content"]
    # crude task detection
    if "TASK: SEED" in user:
        title_line = next((ln for ln in user.splitlines()
                           if ln.startswith("PAGE PATH:")), "")
        page = title_line.split(":", 1)[1].strip() if title_line else "page.md"
        kind_line = next((ln for ln in user.splitlines()
                          if ln.startswith("KIND:")), "KIND: concept")
        kind = kind_line.split(":", 1)[1].strip()
        covers_line = next((ln for ln in user.splitlines()
                            if ln.startswith("COVERS:")), "COVERS:")
        covers = [c.strip() for c in covers_line.split(":", 1)[1].split(",")
                  if c.strip()]
        sha_line = next((ln for ln in user.splitlines()
                         if ln.startswith("KERNEL SHA:")), "KERNEL SHA: null")
        sha = sha_line.split(":", 1)[1].strip()
        title = Path(page).stem
        body = (f"```markdown\n"
                f"---\n"
                f"title: {title}\n"
                f"kind: {kind}\n"
                f"covers:\n" +
                "".join(f"  - {c}\n" for c in covers) +
                f"last_synced_sha: {sha}\n"
                f"last_synced: {now_iso()}\n"
                f"sources: []\n"
                f"---\n\n"
                f"# {title}\n\n"
                f"_(mock-LLM seed: replace this paragraph with a real "
                f"summary of {title}.)_\n\n"
                f"## Key data structures\n\n"
                f"## Key entry points\n\n"
                f"## Related\n\n"
                f"## Recent changes\n\n"
                f"- {now_iso()}: page seeded.\n"
                f"```\n")
        return llm_client.ChatResult(
            text=body, usage={"mock": True}, model="mock", raw={})
    # UPDATE
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


def _list_kernel_files(kernel_dir: Path, globs: list[str],
                        cap: int = 200) -> list[str]:
    """Enumerate kernel-relative files matching any glob. Falls back to an
    empty list if the kernel tree doesn't exist (e.g., offline demo)."""
    if not kernel_dir.exists():
        return []
    from scripts._meta_io import glob_to_regex
    pats = [glob_to_regex(g) for g in globs]
    out: list[str] = []
    for f in kernel_dir.rglob("*"):
        if not f.is_file():
            continue
        if "/.git/" in str(f):
            continue
        rel = str(f.relative_to(kernel_dir))
        if any(p.match(rel) for p in pats):
            out.append(rel)
            if len(out) >= cap:
                break
    return sorted(out)


def _excerpt(kernel_dir: Path, rel: str, max_lines: int = 80) -> str:
    p = kernel_dir / rel
    if not p.exists():
        return ""
    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[:max_lines])


# ---------------------------------------------------------------------------
# SEED
# ---------------------------------------------------------------------------

def cmd_seed(args: argparse.Namespace) -> int:
    page_rel = args.page
    if not page_rel.endswith(".md"):
        page_rel += ".md"
    page_path = WIKI_ROOT / page_rel
    if page_path.exists() and not args.overwrite:
        print(f"[seed] {page_rel} already exists; use --overwrite to replace",
              file=sys.stderr)
        return 2

    kernel_dir = KERNEL_ROOT
    head_sha = None
    if kernel_dir.exists():
        try:
            head_sha = subprocess.check_output(
                ["git", "-C", str(kernel_dir), "rev-parse", "HEAD"],
                text=True).strip()
        except subprocess.CalledProcessError:
            head_sha = None
    files = _list_kernel_files(kernel_dir, args.covers, cap=args.max_files)
    excerpts = ""
    for rel in files[:args.max_excerpts]:
        body = _excerpt(kernel_dir, rel, max_lines=args.excerpt_lines)
        if not body.strip():
            continue
        excerpts += f"\n=== {rel} (first {args.excerpt_lines} lines) ===\n{body}\n"

    user_msg = (
        f"TASK: SEED\n"
        f"PAGE PATH: {page_rel}\n"
        f"KIND: {args.kind}\n"
        f"COVERS: {', '.join(args.covers)}\n"
        f"KERNEL SHA: {head_sha or 'null'}\n"
        f"\nFILES IN COVERAGE ({len(files)}):\n"
        + "\n".join(files[:args.max_files])
        + "\n\nKEY FILE EXCERPTS:" + (excerpts or " (none)\n")
    )

    call = _mock_llm if args.mock_llm else llm_client.chat
    res = call(
        [{"role": "user", "content": user_msg}],
        system=SYSTEM_PROMPT,
        profile=args.profile,
    )
    page_text = extract_markdown_block(res.text)
    fm, body = parse_front_matter(page_text)
    if not fm:
        print("[seed] response had no front matter; refusing to write",
              file=sys.stderr)
        print(res.text[:500], file=sys.stderr)
        return 3
    fm["last_synced_sha"] = head_sha
    fm["last_synced"] = now_iso()

    if args.dry_run:
        print(serialize_page(fm, body))
        return 0

    _write_page(page_rel, fm, body)

    cov = Coverage.load()
    cov.pages[page_rel] = {
        "kind": args.kind,
        "covers": list(args.covers),
        "last_synced_sha": head_sha,
        "last_synced": fm["last_synced"],
    }
    if cov.last_kernel_sha is None and head_sha:
        cov.last_kernel_sha = head_sha
    cov.save()

    print(f"[seed] wrote {page_rel} ({len(body)} bytes), "
          f"covers={args.covers}, head={head_sha}")
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


def _git_head(kernel_dir: Path) -> str | None:
    if not (kernel_dir / ".git").exists():
        return None
    try:
        return subprocess.check_output(
            ["git", "-C", str(kernel_dir), "rev-parse", "HEAD"],
            text=True).strip()
    except subprocess.CalledProcessError:
        return None


def cmd_query(args: argparse.Namespace) -> int:
    fm_tpl, system_prompt = _load_template(args.template)
    cov = Coverage.load()
    pages = [p.strip() for p in (args.pages or "").split(",") if p.strip()]
    wiki_context, sources = _load_wiki_context(pages, cov)
    kernel_sha = _git_head(KERNEL_ROOT) or cov.last_kernel_sha

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

    s = sub.add_parser("seed", parents=[common],
                       help="create a new page from scratch")
    s.add_argument("--page", required=True, help="path relative to wiki/")
    s.add_argument("--kind", required=True,
                   choices=["subsystem", "concept", "entity", "query"])
    s.add_argument("--covers", nargs="+", required=True,
                   help="path globs this page is responsible for")
    s.add_argument("--overwrite", action="store_true")
    s.add_argument("--max-files", type=int, default=120,
                   help="cap on file list shown to the LLM")
    s.add_argument("--max-excerpts", type=int, default=8,
                   help="cap on number of source files to excerpt")
    s.add_argument("--excerpt-lines", type=int, default=80)
    s.set_defaults(func=cmd_seed)

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
