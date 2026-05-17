#!/usr/bin/env bash
# Print seeded-page progress from wiki/_meta/coverage.json.
#
# Designed for `watch`. Defaults are safe for `watch -n5`:
#   watch -n5 bash scripts/seed_progress.sh
#
# "Filled" means the page's last_synced is set — same signal seed_all uses
# to skip pages, so the count matches what the batch would still process.

set -euo pipefail

COVERAGE="${COVERAGE:-wiki/_meta/coverage.json}"
EXCLUDES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --exclude) EXCLUDES+=("$2"); shift 2 ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--exclude GLOB ...]

  --exclude GLOB   fnmatch glob on coverage.json page keys to skip
                   (e.g. 'raw/pcie_scsc/kunit/*'). Repeat to stack.
                   Same semantics as seed_all.py --exclude, so passing
                   the same flags shows the batch's real denominator.
EOF
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -f "$COVERAGE" ]] || { echo "coverage.json not found: $COVERAGE" >&2; exit 1; }

python3 - "$COVERAGE" ${EXCLUDES[@]+"${EXCLUDES[@]}"} <<'PY'
import fnmatch
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

cov_path = sys.argv[1]
excludes = sys.argv[2:]
try:
    with open(cov_path) as f:
        cov = json.load(f)
except json.JSONDecodeError:
    # coverage.json is being rewritten by the batch right now — try again next tick.
    print("coverage.json: mid-write, retry on next tick")
    sys.exit(0)

pages = cov.get("pages", {})
by_top = defaultdict(lambda: {"total": 0, "filled": 0, "skipped": 0})
for page, entry in pages.items():
    parts = page.split("/", 2)
    top = parts[1] if len(parts) >= 2 and parts[0] == "raw" else "(other)"
    if any(fnmatch.fnmatchcase(page, g) for g in excludes):
        by_top[top]["skipped"] += 1
        continue
    by_top[top]["total"] += 1
    if entry.get("last_synced"):
        by_top[top]["filled"] += 1

total = sum(b["total"] for b in by_top.values())
filled = sum(b["filled"] for b in by_top.values())


def bar(f: int, t: int, width: int = 30) -> str:
    if t == 0:
        return "[" + " " * width + "]"
    n = round(width * f / t)
    return "[" + "#" * n + "-" * (width - n) + "]"


header = f"wiki seed progress @ {datetime.now().strftime('%H:%M:%S')}"
if excludes:
    header += f"   (excluded: {', '.join(excludes)})"
print(header)
print()
for top, b in sorted(by_top.items()):
    pct = (b["filled"] / b["total"] * 100) if b["total"] else 0
    skip_note = f"  (+{b['skipped']} skipped)" if b["skipped"] else ""
    print(f"  {top:<20} {b['filled']:>4} / {b['total']:<4}  "
          f"({pct:5.1f}%)  {bar(b['filled'], b['total'])}{skip_note}")
print()
pct = (filled / total * 100) if total else 0
total_skipped = sum(b["skipped"] for b in by_top.values())
skip_note = f"  (+{total_skipped} skipped)" if total_skipped else ""
print(f"  {'TOTAL':<20} {filled:>4} / {total:<4}  ({pct:5.1f}%)  "
      f"{bar(filled, total)}{skip_note}")

mtime = os.path.getmtime(cov_path)
age = (datetime.now() - datetime.fromtimestamp(mtime)).total_seconds()
if age < 60:
    age_s = f"{int(age)}s ago"
elif age < 3600:
    age_s = f"{int(age/60)}m ago"
else:
    age_s = f"{int(age/3600)}h{int((age % 3600)/60)}m ago"
print()
print(f"  coverage.json last updated: {age_s}")
PY
