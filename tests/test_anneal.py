"""Unit tests for the annealing job (D4)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import _meta_io, anneal, update_wiki
from scripts._meta_io import Coverage


def _days_ago_iso(n: int) -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class _IsolatedWiki:
    def setUp(self):  # noqa: D401
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "wiki" / "_meta").mkdir(parents=True)
        self.cov_path = root / "wiki" / "_meta" / "coverage.json"
        self.todo_path = root / "wiki" / "_meta" / "todo.md"
        self.wiki_root = root / "wiki"
        self.kernel_dir = root / "kernel"
        self.cov_path.write_text(json.dumps({
            "schema_version": 1, "last_kernel_sha": None, "pages": {}}))
        self.todo_path.write_text("# todo\n")
        self._orig = {
            "WIKI_ROOT": _meta_io.WIKI_ROOT,
            "COVERAGE_PATH": _meta_io.COVERAGE_PATH,
            "TODO_PATH": _meta_io.TODO_PATH,
            "uw_wiki": update_wiki.WIKI_ROOT,
            "an_wiki": anneal.WIKI_ROOT,
            "an_todo": anneal.TODO_PATH,
        }
        _meta_io.WIKI_ROOT = self.wiki_root
        _meta_io.COVERAGE_PATH = self.cov_path
        _meta_io.TODO_PATH = self.todo_path
        update_wiki.WIKI_ROOT = self.wiki_root
        anneal.WIKI_ROOT = self.wiki_root
        anneal.TODO_PATH = self.todo_path

    def tearDown(self):
        _meta_io.WIKI_ROOT = self._orig["WIKI_ROOT"]
        _meta_io.COVERAGE_PATH = self._orig["COVERAGE_PATH"]
        _meta_io.TODO_PATH = self._orig["TODO_PATH"]
        update_wiki.WIKI_ROOT = self._orig["uw_wiki"]
        anneal.WIKI_ROOT = self._orig["an_wiki"]
        anneal.TODO_PATH = self._orig["an_todo"]

    def _write_page(self, rel: str, fm: dict, body: str = "body\n"):
        path = self.wiki_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_meta_io.serialize_page(fm, body))

    def _seed_coverage(self, pages: dict, kernel_sha: str | None = None):
        cov = Coverage(last_kernel_sha=kernel_sha, pages=pages)
        cov.save(self.cov_path)


class ScanTests(_IsolatedWiki, unittest.TestCase):
    def test_stale_page_flagged_when_sha_lags(self):
        self._write_page("subsystems/mm.md", {
            "title": "MM", "kind": "subsystem", "covers": ["mm/*.c"],
            "last_synced_sha": "old", "last_synced": _days_ago_iso(1),
        })
        self._seed_coverage({"subsystems/mm.md": {
            "kind": "subsystem", "covers": ["mm/*.c"],
            "last_synced_sha": "old", "last_synced": _days_ago_iso(1),
        }}, kernel_sha="new")
        cands = anneal.scan_candidates(
            Coverage.load(self.cov_path), self.wiki_root, self.kernel_dir,
            self.todo_path, max_age_days=14)
        reasons = [c.reason for c in cands]
        self.assertIn("stale_page", reasons)

    def test_stale_page_flagged_when_old_even_with_matching_sha(self):
        self._write_page("subsystems/mm.md", {
            "title": "MM", "kind": "subsystem", "covers": ["mm/*.c"],
            "last_synced_sha": "same", "last_synced": _days_ago_iso(30),
        })
        self._seed_coverage({"subsystems/mm.md": {
            "kind": "subsystem", "covers": ["mm/*.c"],
            "last_synced_sha": "same", "last_synced": _days_ago_iso(30),
        }}, kernel_sha="same")
        cands = anneal.scan_candidates(
            Coverage.load(self.cov_path), self.wiki_root, self.kernel_dir,
            self.todo_path, max_age_days=14)
        self.assertTrue(any(c.reason == "stale_page" for c in cands))

    def test_drift_only_flagged_when_kernel_tree_present(self):
        # No kernel files exist; drift detection must be disabled to avoid
        # false positives on offline runs.
        self._write_page("subsystems/zz.md", {
            "title": "ZZ", "kind": "subsystem",
            "covers": ["no/such/path/*.c"],
            "last_synced_sha": "x", "last_synced": _days_ago_iso(1),
        })
        self._seed_coverage({"subsystems/zz.md": {
            "kind": "subsystem", "covers": ["no/such/path/*.c"],
            "last_synced_sha": "x", "last_synced": _days_ago_iso(1),
        }}, kernel_sha="x")
        cands = anneal.scan_candidates(
            Coverage.load(self.cov_path), self.wiki_root, self.kernel_dir,
            self.todo_path, max_age_days=14)
        self.assertFalse(any(c.reason == "coverage_drift" for c in cands))

    def test_drift_flagged_with_kernel_tree(self):
        # Populate a fake kernel tree.
        (self.kernel_dir / "mm").mkdir(parents=True)
        (self.kernel_dir / "mm" / "slab.c").write_text("// stub\n")
        self._write_page("subsystems/zz.md", {
            "title": "ZZ", "kind": "subsystem",
            "covers": ["no/such/path/*.c"],
            "last_synced_sha": "x", "last_synced": _days_ago_iso(1),
        })
        self._seed_coverage({"subsystems/zz.md": {
            "kind": "subsystem", "covers": ["no/such/path/*.c"],
            "last_synced_sha": "x", "last_synced": _days_ago_iso(1),
        }}, kernel_sha="x")
        cands = anneal.scan_candidates(
            Coverage.load(self.cov_path), self.wiki_root, self.kernel_dir,
            self.todo_path, max_age_days=14)
        drift = [c for c in cands if c.reason == "coverage_drift"]
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0].details["dead_covers"], ["no/such/path/*.c"])

    def test_broken_link_detected(self):
        self._write_page("subsystems/a.md", {
            "title": "A", "kind": "subsystem", "covers": [],
            "last_synced_sha": None, "last_synced": _days_ago_iso(1),
        }, body="See [[concepts/no_such_page|the page]] for more.\n")
        cands = anneal.scan_candidates(
            Coverage.load(self.cov_path), self.wiki_root, self.kernel_dir,
            self.todo_path, max_age_days=14)
        broken = [c for c in cands if c.reason == "broken_link"]
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0].details["broken_targets"],
                         ["concepts/no_such_page"])

    def test_link_to_existing_page_not_flagged(self):
        self._write_page("subsystems/a.md", {
            "title": "A", "kind": "subsystem", "covers": [],
            "last_synced_sha": None, "last_synced": _days_ago_iso(1),
        }, body="See [[concepts/rcu]].\n")
        self._write_page("concepts/rcu.md", {
            "title": "RCU", "kind": "concept", "covers": [],
            "last_synced_sha": None, "last_synced": _days_ago_iso(1),
        })
        cands = anneal.scan_candidates(
            Coverage.load(self.cov_path), self.wiki_root, self.kernel_dir,
            self.todo_path, max_age_days=14)
        self.assertFalse(any(c.reason == "broken_link" for c in cands))

    def test_uncovered_from_todo_reported_only(self):
        self.todo_path.write_text(
            "# todo\n\n## section\n- [ ] `mm/page_alloc.c`\n- [ ] `fs/foo.c`\n"
        )
        cands = anneal.scan_candidates(
            Coverage.load(self.cov_path), self.wiki_root, self.kernel_dir,
            self.todo_path, max_age_days=14)
        uncov = [c for c in cands if c.reason == "uncovered"]
        self.assertEqual(len(uncov), 1)
        self.assertEqual(uncov[0].details["count"], 2)
        self.assertNotIn("uncovered", anneal.REPAIR)

    def test_score_ordering(self):
        # higher-priority drift should outrank stale_page
        (self.kernel_dir / "mm").mkdir(parents=True)
        (self.kernel_dir / "mm" / "slab.c").write_text("// stub\n")
        self._write_page("a.md", {"title": "A", "kind": "subsystem",
                                  "covers": ["dead/*"],
                                  "last_synced_sha": "old",
                                  "last_synced": _days_ago_iso(15)})
        self._write_page("b.md", {"title": "B", "kind": "subsystem",
                                  "covers": ["mm/*"],
                                  "last_synced_sha": "old",
                                  "last_synced": _days_ago_iso(20)})
        self._seed_coverage({
            "a.md": {"kind": "subsystem", "covers": ["dead/*"],
                     "last_synced_sha": "old",
                     "last_synced": _days_ago_iso(15)},
            "b.md": {"kind": "subsystem", "covers": ["mm/*"],
                     "last_synced_sha": "old",
                     "last_synced": _days_ago_iso(20)},
        }, kernel_sha="new")
        cands = anneal.scan_candidates(
            Coverage.load(self.cov_path), self.wiki_root, self.kernel_dir,
            self.todo_path, max_age_days=14)
        self.assertEqual(cands[0].reason, "coverage_drift")


class ApplyTests(_IsolatedWiki, unittest.TestCase):
    def test_stale_page_refresh_with_mock_llm(self):
        self._write_page("subsystems/mm.md", {
            "title": "MM", "kind": "subsystem", "covers": ["mm/*.c"],
            "last_synced_sha": "old", "last_synced": _days_ago_iso(30),
        })
        self._seed_coverage({"subsystems/mm.md": {
            "kind": "subsystem", "covers": ["mm/*.c"],
            "last_synced_sha": "old", "last_synced": _days_ago_iso(30),
        }}, kernel_sha="new")
        rc = anneal._main([
            "run", "--budget", "5", "--mock-llm",
            "--kernel-dir", str(self.kernel_dir),
        ])
        self.assertEqual(rc, 0)
        page = (self.wiki_root / "subsystems" / "mm.md").read_text()
        self.assertIn("last_synced_sha: new", page)
        self.assertIn("mock-update", page)

    def test_broken_link_repair_with_mock_llm(self):
        self._write_page("subsystems/a.md", {
            "title": "A", "kind": "subsystem", "covers": [],
            "last_synced_sha": None, "last_synced": _days_ago_iso(1),
        }, body="See [[concepts/no_such_page|the page]] for more.\n"
              "Also [[concepts/no_such_page]] here.\n")
        rc = anneal._main([
            "run", "--budget", "5", "--mock-llm",
            "--kernel-dir", str(self.kernel_dir),
        ])
        self.assertEqual(rc, 0)
        page = (self.wiki_root / "subsystems" / "a.md").read_text()
        self.assertNotIn("[[concepts/no_such_page", page)
        self.assertIn("the page", page)
        self.assertIn("concepts/no_such_page", page)

    def test_drift_drops_dead_covers_and_refreshes(self):
        (self.kernel_dir / "mm").mkdir(parents=True)
        (self.kernel_dir / "mm" / "slab.c").write_text("// stub\n")
        self._write_page("subsystems/mm.md", {
            "title": "MM", "kind": "subsystem",
            "covers": ["mm/*.c", "no/such/*"],
            "last_synced_sha": "old", "last_synced": _days_ago_iso(1),
        })
        self._seed_coverage({"subsystems/mm.md": {
            "kind": "subsystem", "covers": ["mm/*.c", "no/such/*"],
            "last_synced_sha": "old", "last_synced": _days_ago_iso(1),
        }}, kernel_sha="new")
        rc = anneal._main([
            "run", "--budget", "5", "--mock-llm",
            "--kernel-dir", str(self.kernel_dir),
        ])
        self.assertEqual(rc, 0)
        cov = json.loads(self.cov_path.read_text())
        self.assertEqual(cov["pages"]["subsystems/mm.md"]["covers"],
                         ["mm/*.c"])
        page = (self.wiki_root / "subsystems" / "mm.md").read_text()
        self.assertIn("- mm/*.c", page)
        self.assertNotIn("no/such/*", page)

    def test_budget_caps_repairs(self):
        # 3 stale pages, budget 1 -> only the highest-score gets repaired.
        for i, days in enumerate([15, 30, 60]):
            rel = f"p{i}.md"
            self._write_page(rel, {
                "title": f"P{i}", "kind": "subsystem", "covers": [],
                "last_synced_sha": "old", "last_synced": _days_ago_iso(days),
            })
            cov = Coverage.load(self.cov_path)
            cov.pages[rel] = {"kind": "subsystem", "covers": [],
                              "last_synced_sha": "old",
                              "last_synced": _days_ago_iso(days)}
            cov.last_kernel_sha = "new"
            cov.save(self.cov_path)
        rc = anneal._main([
            "run", "--budget", "1", "--mock-llm",
            "--kernel-dir", str(self.kernel_dir),
        ])
        self.assertEqual(rc, 0)
        # p2 is the oldest -> highest score -> only one written
        p0 = (self.wiki_root / "p0.md").read_text()
        p1 = (self.wiki_root / "p1.md").read_text()
        p2 = (self.wiki_root / "p2.md").read_text()
        self.assertIn("last_synced_sha: old", p0)
        self.assertIn("last_synced_sha: old", p1)
        self.assertIn("last_synced_sha: new", p2)


if __name__ == "__main__":
    unittest.main()
