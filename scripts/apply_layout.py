"""Apply a layout proposal YAML produced by ``scripts.propose_layout``.

Reads a YAML file under ``wiki/_meta/layout-proposals/`` (or any path),
validates each ``subsystems[]`` / ``concepts[]`` entry, and writes one
stub page per entry under ``wiki/raw/<top>/<basename>.md`` plus a merge
into ``wiki/_meta/coverage.json``. Idempotent by default — existing
pages are skipped unless ``--force`` is passed.

This is the **deterministic** half of the propose/apply split. The LLM
already chose the page layout in the YAML; this script's only job is
plumbing — serialise front-matter, merge coverage, never call out.

::

    # apply a proposal
    python -m scripts.apply_layout \\
        wiki/_meta/layout-proposals/pcie_scsc-20260516-101500.yaml

    # see what would happen first
    python -m scripts.apply_layout PROPOSAL.yaml --dry-run

    # rewrite stubs even if they already exist (loses any LLM fill-in!)
    python -m scripts.apply_layout PROPOSAL.yaml --force

After apply, run ``update_wiki seed-agent`` on each new stub to fill its
body — same flow as the entity stubs produced by ``seed_pages.sh``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._meta_io import (
    COVERAGE_PATH,
    WIKI_ROOT,
    parse_front_matter,
    serialize_page,
)


VALID_KINDS = ("subsystem", "concept")


class LayoutError(Exception):
    pass


def _load_proposal(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (front_matter, body_yaml) — the body is parsed via PyYAML."""
    raw = path.read_text()
    fm, body = parse_front_matter(raw)
    try:
        parsed = yaml.safe_load(body) or {}
    except yaml.YAMLError as e:
        raise LayoutError(f"body is not valid YAML: {e}")
    if not isinstance(parsed, dict):
        raise LayoutError("body must be a YAML mapping with "
                          "`subsystems:` and/or `concepts:` keys")
    return fm, parsed


def _normalize_entries(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten subsystems[] + concepts[] into a single ordered list with
    ``kind`` tagged in. Validate shape eagerly so failures surface before
    we write any file."""
    out: list[dict[str, Any]] = []
    seen_basenames: set[str] = set()
    for kind in VALID_KINDS:
        entries = body.get(f"{kind}s") or []
        if not isinstance(entries, list):
            raise LayoutError(f"`{kind}s:` must be a list")
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                raise LayoutError(f"{kind}s[{i}] is not a mapping")
            for key in ("title", "basename", "covers"):
                if key not in e:
                    raise LayoutError(f"{kind}s[{i}] missing `{key}`")
            base = str(e["basename"]).strip()
            if "/" in base or base.endswith(".md"):
                raise LayoutError(
                    f"{kind}s[{i}].basename must be a bare stem "
                    f"(no '/' or '.md'); got {base!r}")
            if base in seen_basenames:
                raise LayoutError(
                    f"duplicate basename across proposal: {base!r}")
            seen_basenames.add(base)
            covers = e["covers"]
            if (not isinstance(covers, list) or not covers
                    or not all(isinstance(c, str) and c for c in covers)):
                raise LayoutError(
                    f"{kind}s[{i}].covers must be a non-empty list of strings")
            out.append({
                "kind": kind,
                "title": str(e["title"]).strip(),
                "basename": base,
                "covers": list(covers),
                "rationale": str(e.get("rationale", "")).strip(),
            })
    return out


def _stub_body(entry: dict[str, Any]) -> str:
    kind = entry["kind"]
    title = entry["title"]
    rationale = entry["rationale"] or "Seed page — LLM이 채울 자리."
    return (
        f"# {title}\n\n"
        f"> Seed page (`kind: {kind}`) — `scripts/apply_layout.py`가 "
        f"생성. {rationale}\n\n"
        f"## Purpose\nTODO\n\n"
        f"## Scope / boundaries\nTODO\n\n"
        f"## Key flows\nTODO\n\n"
        f"## Source files\n"
        + "".join(f"- `{c}`\n" for c in entry["covers"])
    )


def _stub_page(entry: dict[str, Any]) -> str:
    fm = {
        "title": entry["title"],
        "kind": entry["kind"],
        "covers": entry["covers"],
        "last_synced_sha": None,
        "last_synced": None,
        "sources": [],
    }
    return serialize_page(fm, _stub_body(entry))


def _page_rel(top: str, basename: str) -> str:
    return f"raw/{top}/{basename}.md"


def _apply(proposal_path: Path, *, force: bool, dry_run: bool) -> int:
    fm, body = _load_proposal(proposal_path)
    tree_field = fm.get("tree", "")
    if not tree_field.startswith("raw/"):
        raise LayoutError(
            f"proposal front-matter `tree:` must start with 'raw/'; "
            f"got {tree_field!r}")
    top = tree_field.split("/", 2)[1]
    entries = _normalize_entries(body)
    if not entries:
        print("[apply-layout] proposal has zero entries; nothing to do",
              file=sys.stderr)
        return 0

    if COVERAGE_PATH.exists():
        cov = json.loads(COVERAGE_PATH.read_text())
    else:
        cov = {"schema_version": 2, "subtree_shas": {}, "pages": {}}
    cov.setdefault("pages", {})

    created = skipped = overwritten = 0
    for e in entries:
        rel = _page_rel(top, e["basename"])
        path = WIKI_ROOT / rel
        page_exists = path.exists()
        cov_exists = rel in cov["pages"]
        action: str
        if page_exists and not force:
            action = "skip"
            skipped += 1
        elif page_exists and force:
            action = "force"
            overwritten += 1
        else:
            action = "create"
            created += 1
        cov_note = "+cov" if not cov_exists else "~cov"
        print(f"{action:<6} {rel}   [{e['kind']}, covers={e['covers']}] "
              f"{cov_note}")
        if dry_run:
            continue
        if action == "skip":
            # still ensure coverage entry exists (proposal is authoritative
            # for covers when the page was an earlier stub by some other
            # path).
            cov["pages"].setdefault(rel, {
                "kind": e["kind"],
                "covers": e["covers"],
                "last_synced_sha": None,
                "last_synced": None,
            })
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_stub_page(e))
        cov["pages"][rel] = {
            "kind": e["kind"],
            "covers": e["covers"],
            "last_synced_sha": None,
            "last_synced": None,
        }

    if not dry_run:
        COVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        COVERAGE_PATH.write_text(
            json.dumps(cov, indent=2, sort_keys=True) + "\n")

    summary = (
        f"[apply-layout] {proposal_path.name}: "
        f"created={created} overwritten={overwritten} skipped={skipped}"
    )
    if dry_run:
        summary += " (dry-run, no files written)"
    print(summary, file=sys.stderr)
    return 0


def _run(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("proposal", help="path to a layout-proposal YAML file")
    p.add_argument("--force", action="store_true",
                   help="overwrite stub pages that already exist (DESTRUCTIVE "
                        "— loses any LLM-written body)")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="print plan, do not write anything")
    args = p.parse_args(argv)

    path = Path(args.proposal)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    if not path.exists():
        print(f"[apply-layout] proposal not found: {path}", file=sys.stderr)
        return 2

    try:
        return _apply(path, force=args.force, dry_run=args.dry_run)
    except LayoutError as e:
        print(f"[apply-layout] invalid proposal: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv[1:]))
