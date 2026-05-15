"""Unit tests for the glob matcher and patch router (D2)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import _meta_io
from scripts._meta_io import (
    Coverage,
    affected_pages,
    append_todo,
    glob_to_regex,
)
from scripts.patch_router import route


class GlobTests(unittest.TestCase):
    def test_single_star_stays_within_segment(self):
        r = glob_to_regex("mm/*.c")
        self.assertTrue(r.match("mm/slab.c"))
        self.assertFalse(r.match("mm/slab/foo.c"))
        self.assertFalse(r.match("kernel/sched/core.c"))

    def test_double_star_spans_segments(self):
        r = glob_to_regex("drivers/**/*.c")
        self.assertTrue(r.match("drivers/gpu/drm/i915/intel_display.c"))
        self.assertTrue(r.match("drivers/net/ethernet/intel/e1000/e1000_main.c"))
        self.assertFalse(r.match("mm/slab.c"))

    def test_double_star_with_trailing_slash_matches_zero_segments(self):
        r = glob_to_regex("net/**/dev.c")
        self.assertTrue(r.match("net/core/dev.c"))
        self.assertTrue(r.match("net/dev.c"))

    def test_question_mark(self):
        r = glob_to_regex("mm/slab?.c")
        self.assertTrue(r.match("mm/slab1.c"))
        self.assertFalse(r.match("mm/slab.c"))
        self.assertFalse(r.match("mm/slab12.c"))

    def test_escapes_regex_metachars(self):
        r = glob_to_regex("a+b.c")
        self.assertTrue(r.match("a+b.c"))
        self.assertFalse(r.match("axb.c"))


class AffectedPagesTests(unittest.TestCase):
    def _cov(self, pages: dict) -> Coverage:
        return Coverage(pages=pages)

    def test_single_page_match(self):
        cov = self._cov({
            "subsystems/mm.md": {"covers": ["mm/*.c"]},
        })
        pages, uncovered = affected_pages(cov, ["mm/slab.c", "mm/slub.c"])
        self.assertEqual(pages, ["subsystems/mm.md"])
        self.assertEqual(uncovered, [])

    def test_multi_page_match_and_uncovered(self):
        cov = self._cov({
            "subsystems/mm.md": {"covers": ["mm/*.c"]},
            "subsystems/sched.md": {"covers": ["kernel/sched/**"]},
        })
        pages, uncovered = affected_pages(cov, [
            "mm/slab.c",
            "kernel/sched/core.c",
            "fs/ext4/super.c",
        ])
        self.assertEqual(pages, ["subsystems/mm.md", "subsystems/sched.md"])
        self.assertEqual(uncovered, ["fs/ext4/super.c"])

    def test_one_file_can_hit_multiple_pages(self):
        cov = self._cov({
            "subsystems/mm.md":     {"covers": ["mm/*.c"]},
            "concepts/slab.md":     {"covers": ["mm/slab*.c", "mm/slub.c"]},
        })
        pages, uncovered = affected_pages(cov, ["mm/slab.c"])
        self.assertEqual(pages, ["concepts/slab.md", "subsystems/mm.md"])
        self.assertEqual(uncovered, [])


class TodoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "todo.md"

    def test_append_dedups(self):
        n1 = append_todo("first", ["a", "b"], path=self.path)
        n2 = append_todo("second", ["b", "c"], path=self.path)
        self.assertEqual(n1, 2)
        self.assertEqual(n2, 1)
        body = self.path.read_text()
        self.assertEqual(body.count("- [ ] `a`"), 1)
        self.assertEqual(body.count("- [ ] `b`"), 1)
        self.assertEqual(body.count("- [ ] `c`"), 1)


class RouteTests(unittest.TestCase):
    """End-to-end-ish: load a fixture coverage, route a dummy manifest."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.cov_path = tmp / "coverage.json"
        self.todo_path = tmp / "todo.md"
        self.cov_path.write_text(json.dumps({
            "schema_version": 2,
            "subtree_shas": {"mm": "deadbeef"},
            "pages": {
                "subsystems/mm.md": {
                    "kind": "subsystem",
                    "covers": ["mm/*.c", "mm/*.h"],
                    "last_synced_sha": "deadbeef",
                    "last_synced": "2026-05-01T00:00:00Z",
                },
                "concepts/slab.md": {
                    "kind": "concept",
                    "covers": ["mm/slab*.c", "mm/slub.c"],
                    "last_synced_sha": "deadbeef",
                    "last_synced": "2026-05-01T00:00:00Z",
                },
            },
        }))
        self._orig_cov = _meta_io.COVERAGE_PATH
        self._orig_todo = _meta_io.TODO_PATH
        _meta_io.COVERAGE_PATH = self.cov_path
        _meta_io.TODO_PATH = self.todo_path

    def tearDown(self):
        _meta_io.COVERAGE_PATH = self._orig_cov
        _meta_io.TODO_PATH = self._orig_todo

    def test_route_with_apply(self):
        manifest = {
            "from": "deadbeef",
            "to":   "cafef00d",
            "files": [
                "mm/slab.c",      # hits both pages
                "mm/page_alloc.c",  # mm subsystem only
                "fs/ext4/super.c",  # uncovered
                "drivers/gpu/drm/i915/intel_display.c",  # uncovered
            ],
            "commits": ["cafef00d slab: tighten kfree_rcu()"],
        }
        result = route(manifest, apply=True)
        self.assertEqual(result["from"], "deadbeef")
        self.assertEqual(result["to"], "cafef00d")
        self.assertEqual(result["n_files"], 4)
        self.assertEqual(
            result["affected_pages"],
            ["concepts/slab.md", "subsystems/mm.md"],
        )
        self.assertEqual(
            result["uncovered"],
            ["drivers/gpu/drm/i915/intel_display.c", "fs/ext4/super.c"],
        )
        self.assertEqual(result["todo_added"], 2)
        body = self.todo_path.read_text()
        self.assertIn("fs/ext4/super.c", body)
        self.assertIn("drivers/gpu/drm/i915/intel_display.c", body)


if __name__ == "__main__":
    unittest.main()
