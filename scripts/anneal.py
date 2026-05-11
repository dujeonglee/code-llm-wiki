"""Annealing: periodic gap detection + repair for the wiki.

The patch router (D2) only reacts to *new* commits. Annealing covers
everything else — the slow drift between source and documentation that
accumulates even when nobody pushes code:

* a page hasn't been re-read in a long time and may have grown inaccurate;
* a page's ``covers`` patterns now match nothing because files were renamed
  or deleted upstream;
* a page links to ``[[concepts/foo]]`` but ``wiki/concepts/foo.md`` doesn't
  exist;
* files in ``raw/linux/`` that no page documents — already tracked by
  ``patch_router --apply`` in ``wiki/_meta/todo.md``; we surface them here
  so the dashboard is one place.

Workflow (intended for cron) ::

    python -m scripts.anneal scan                  # inventory, prints JSON
    python -m scripts.anneal run --budget 3        # repair top 3 by score
    python -m scripts.anneal run --budget 3 \\
        --mock-llm --dry-run                       # offline rehearsal

Scoring (higher = more urgent):

* coverage_drift  100 + 10 * (# dead covers)
* broken_link      50 + 10 * (# broken targets)
* stale_page         max(0, days_since_sync - max_age)
                   + 30 if last_synced_sha != coverage.last_kernel_sha

Only ``stale_page``, ``broken_link``, and ``coverage_drift`` are auto-repaired
in D4. ``uncovered`` items are reported only — auto-seeding them would
require heuristic decisions about page kind / path that we'd rather a human
or a future, more confident annealer make.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts import update_wiki
from scripts._meta_io import (
    COVERAGE_PATH,
    Coverage,
    KERNEL_ROOT,
    TODO_PATH,
    WIKI_ROOT,
    glob_to_regex,
    now_iso,
    parse_front_matter,
)

DEFAULT_MAX_AGE_DAYS = 14


# ---------------------------------------------------------------------------
# Candidate model
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    page: str                       # wiki-relative md path (or "-" for uncovered)
    reason: str                     # stale_page | coverage_drift | broken_link | uncovered
    score: int
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")


def _iter_wiki_pages(wiki_root: Path) -> list[str]:
    """All wiki pages (md files) as relative paths, excluding _meta and
    the root index."""
    pages: list[str] = []
    for p in wiki_root.rglob("*.md"):
        rel = p.relative_to(wiki_root).as_posix()
        if rel.startswith("_meta/"):
            continue
        pages.append(rel)
    return sorted(pages)


def _enumerate_kernel(kernel_dir: Path) -> list[str]:
    if not kernel_dir.exists():
        return []
    out: list[str] = []
    for f in kernel_dir.rglob("*"):
        if not f.is_file():
            continue
        s = str(f)
        if "/.git/" in s:
            continue
        try:
            out.append(f.relative_to(kernel_dir).as_posix())
        except ValueError:
            continue
    return out


def _days_since(iso_str: str | None) -> int | None:
    if not iso_str:
        return None
    try:
        dt = datetime.strptime(iso_str.rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(iso_str.rstrip("Z"), "%Y-%m-%d")
        except ValueError:
            return None
    dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(tz=timezone.utc) - dt).days


def scan_candidates(coverage: Coverage, wiki_root: Path, kernel_dir: Path,
                    todo_path: Path, *, max_age_days: int
                    ) -> list[Candidate]:
    """Inventory the wiki and return candidates to repair, score-sorted
    descending."""
    kernel_files = _enumerate_kernel(kernel_dir)
    wiki_pages = _iter_wiki_pages(wiki_root)
    wiki_set = set(wiki_pages)
    candidates: list[Candidate] = []

    # 1) drift + stale, driven by coverage.pages
    for page_rel, entry in coverage.pages.items():
        covers = entry.get("covers", []) or []
        dead: list[str] = []
        if kernel_files:  # only check drift if we have a kernel tree
            for pat in covers:
                rx = glob_to_regex(pat)
                if not any(rx.match(f) for f in kernel_files):
                    dead.append(pat)
        if dead:
            candidates.append(Candidate(
                page=page_rel,
                reason="coverage_drift",
                score=100 + 10 * len(dead),
                details={"dead_covers": dead, "kernel_present": True},
            ))

        # stale_page
        days = _days_since(entry.get("last_synced"))
        sha_lag = (entry.get("last_synced_sha") !=
                   coverage.last_kernel_sha and coverage.last_kernel_sha)
        if (days is not None and days > max_age_days) or sha_lag:
            score = max(0, (days or 0) - max_age_days) + (30 if sha_lag else 0)
            if score > 0:
                candidates.append(Candidate(
                    page=page_rel,
                    reason="stale_page",
                    score=score,
                    details={
                        "days_since_sync": days,
                        "page_sha": entry.get("last_synced_sha"),
                        "kernel_sha": coverage.last_kernel_sha,
                    },
                ))

    # 2) broken links: walk every wiki page, parse [[wiki-links]]
    for page_rel in wiki_pages:
        body = (wiki_root / page_rel).read_text()
        broken: list[str] = []
        for m in WIKI_LINK_RE.finditer(body):
            target = m.group(1).strip()
            target_md = target if target.endswith(".md") else target + ".md"
            if target_md not in wiki_set:
                broken.append(target)
        if broken:
            candidates.append(Candidate(
                page=page_rel,
                reason="broken_link",
                score=50 + 10 * len(broken),
                details={"broken_targets": sorted(set(broken))},
            ))

    # 3) uncovered files reported in todo.md (informational only)
    if todo_path.exists():
        body = todo_path.read_text()
        items = re.findall(r"- \[ \] `([^`]+)`", body)
        # ignore the seeded "(없음)" placeholder
        items = [x for x in items if x and x != "(없음)"]
        if items:
            candidates.append(Candidate(
                page="-",
                reason="uncovered",
                score=10,
                details={"files": sorted(set(items))[:50],
                         "count": len(set(items))},
            ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Repair actions
# ---------------------------------------------------------------------------

SYSTEM_BROKEN_LINK = """\
You are repairing broken cross-links in a code wiki. The page below contains
[[wiki-links]] that point to pages which do NOT exist in this wiki. For each
broken link, rewrite it to either:

  (a) plain text (if no equivalent page exists and the link doesn't add
      value), or
  (b) a link to a page that DOES exist (only if a plausible existing target
      is given to you).

Leave all other content unchanged. Output the FULL page (front-matter + body)
inside a single ```markdown ... ``` fenced block. Preserve front-matter
exactly as given.
"""


def _refresh_stale_page(candidate: Candidate, coverage: Coverage, *,
                        kernel_dir: Path, profile: str | None,
                        mock_llm: bool, dry_run: bool,
                        max_diff_bytes: int) -> bool:
    """Run update_wiki.update on a single page, using its last_synced_sha as
    'from' and coverage.last_kernel_sha as 'to'."""
    page_rel = candidate.page
    entry = coverage.pages.get(page_rel, {})
    routing = {
        "from": entry.get("last_synced_sha"),
        "to": coverage.last_kernel_sha or entry.get("last_synced_sha"),
        "n_files": 0,
        "affected_pages": [page_rel],
        "uncovered": [],
        "commits": [f"(anneal) stale_page refresh, "
                    f"age={candidate.details.get('days_since_sync')}d"],
    }
    written, _ = update_wiki.run_update(
        routing,
        kernel_dir=kernel_dir,
        profile=profile,
        mock_llm=mock_llm,
        dry_run=dry_run,
        max_diff_bytes=max_diff_bytes,
    )
    return written > 0


def _repair_broken_links(candidate: Candidate, *, profile: str | None,
                         mock_llm: bool, dry_run: bool) -> bool:
    """Send the page to the LLM with the broken-link list and ask for a
    rewrite. In mock mode, simply strip the broken [[...]] to plain text."""
    page_rel = candidate.page
    page_path = WIKI_ROOT / page_rel
    if not page_path.exists():
        return False
    text = page_path.read_text()
    fm, body = parse_front_matter(text)
    broken = candidate.details.get("broken_targets", [])

    if mock_llm:
        new_body = body
        for tgt in broken:
            new_body = re.sub(
                r"\[\[" + re.escape(tgt) + r"(\|[^\]]*)?\]\]",
                lambda m: (m.group(1)[1:] if m.group(1) else tgt),
                new_body,
            )
        if dry_run:
            print(f"--- {page_rel} (broken_link repair) ---")
            print(new_body[:400])
            return True
        from scripts._meta_io import serialize_page
        page_path.write_text(serialize_page(fm, new_body))
        return True

    from scripts import llm_client
    from scripts._meta_io import serialize_page
    user_msg = (
        f"PAGE PATH: {page_rel}\n"
        f"BROKEN LINKS (these targets don't exist):\n"
        + "\n".join(f"- [[{t}]]" for t in broken) + "\n\n"
        f"FULL PAGE:\n```markdown\n{serialize_page(fm, body)}```\n"
    )
    res = llm_client.chat(
        [{"role": "user", "content": user_msg}],
        system=SYSTEM_BROKEN_LINK, profile=profile,
    )
    from scripts._meta_io import extract_markdown_block
    new_text = extract_markdown_block(res.text)
    new_fm, new_body = parse_front_matter(new_text)
    if not new_fm:
        print(f"[anneal] broken_link: {page_rel} response had no fm; skip",
              file=sys.stderr)
        return False
    merged = dict(fm)
    merged.update(new_fm)
    if dry_run:
        print(f"--- {page_rel} (broken_link repair) ---")
        print(new_body[:400])
        return True
    page_path.write_text(serialize_page(merged, new_body))
    return True


def _repair_drift(candidate: Candidate, coverage: Coverage, *,
                  kernel_dir: Path, profile: str | None, mock_llm: bool,
                  dry_run: bool, max_diff_bytes: int) -> bool:
    """For drift, we drop dead covers from the page's fm and coverage.json,
    then run a stale-page refresh so the LLM rewrites the affected sections.
    """
    page_rel = candidate.page
    dead = set(candidate.details.get("dead_covers", []))
    page_path = WIKI_ROOT / page_rel
    if not page_path.exists():
        return False
    fm, body = parse_front_matter(page_path.read_text())
    surviving = [c for c in (fm.get("covers") or []) if c not in dead]
    fm["covers"] = surviving
    if not dry_run:
        from scripts._meta_io import serialize_page
        page_path.write_text(serialize_page(fm, body))
        entry = coverage.pages.setdefault(page_rel, {})
        entry["covers"] = surviving
        coverage.save()
    # Now refresh the page narrative against current code.
    return _refresh_stale_page(candidate, coverage, kernel_dir=kernel_dir,
                               profile=profile, mock_llm=mock_llm,
                               dry_run=dry_run,
                               max_diff_bytes=max_diff_bytes)


REPAIR: dict[str, Callable[..., bool]] = {
    "stale_page": _refresh_stale_page,
    "broken_link": _repair_broken_links,
    "coverage_drift": _repair_drift,
}


def apply_candidate(candidate: Candidate, coverage: Coverage, *,
                    kernel_dir: Path, profile: str | None, mock_llm: bool,
                    dry_run: bool, max_diff_bytes: int) -> bool:
    fn = REPAIR.get(candidate.reason)
    if fn is None:
        # uncovered -> reported only; not auto-repaired in D4
        return False
    if candidate.reason in ("stale_page", "coverage_drift"):
        return fn(candidate, coverage, kernel_dir=kernel_dir, profile=profile,
                  mock_llm=mock_llm, dry_run=dry_run,
                  max_diff_bytes=max_diff_bytes)
    return fn(candidate, profile=profile, mock_llm=mock_llm,
              dry_run=dry_run)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _scan(args: argparse.Namespace) -> int:
    cov = Coverage.load()
    cands = scan_candidates(
        cov,
        WIKI_ROOT,
        Path(args.kernel_dir),
        TODO_PATH,
        max_age_days=args.max_age_days,
    )
    out = [c.as_dict() for c in cands]
    print(json.dumps({"total": len(out), "candidates": out}, indent=2))
    return 0


def _run(args: argparse.Namespace) -> int:
    cov = Coverage.load()
    cands = scan_candidates(
        cov,
        WIKI_ROOT,
        Path(args.kernel_dir),
        TODO_PATH,
        max_age_days=args.max_age_days,
    )
    repairable = [c for c in cands if c.reason in REPAIR]
    picked = repairable[:args.budget]
    print(f"[anneal] {len(cands)} candidate(s), "
          f"{len(repairable)} repairable, picking top {len(picked)}")
    for c in picked:
        print(f"[anneal] {c.reason} score={c.score} page={c.page}")
    n_ok = 0
    for c in picked:
        ok = apply_candidate(
            c, cov,
            kernel_dir=Path(args.kernel_dir),
            profile=args.profile,
            mock_llm=args.mock_llm,
            dry_run=args.dry_run,
            max_diff_bytes=args.max_diff_bytes,
        )
        n_ok += int(ok)
    print(f"[anneal] {n_ok}/{len(picked)} repaired"
          + (" (dry-run)" if args.dry_run else ""))
    return 0


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--kernel-dir", default=str(KERNEL_ROOT),
                        help=f"kernel source tree (default: {KERNEL_ROOT})")
    common.add_argument("--max-age-days", type=int,
                        default=DEFAULT_MAX_AGE_DAYS,
                        help="page is 'stale' beyond this many days "
                             "since last_synced")

    s = sub.add_parser("scan", parents=[common],
                       help="inventory candidates, print JSON; no writes")
    s.set_defaults(func=_scan)

    r = sub.add_parser("run", parents=[common],
                       help="repair the top --budget candidates")
    r.add_argument("--budget", type=int, default=3,
                   help="max pages to repair this run")
    r.add_argument("--profile", help="LLM profile (default: per config)")
    r.add_argument("--mock-llm", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--max-diff-bytes", type=int, default=60_000)
    r.set_defaults(func=_run)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
