"""Unit tests for scripts.seed_all page selection.

The subprocess loop itself is not unit-tested (would spawn real
seed-agent), but the selection helper is the only place with branching
logic so most regressions land here.
"""
from __future__ import annotations

import unittest

from scripts.seed_all import _build_cmd, _select_pages


def _cov(pages: dict) -> dict:
    return {"pages": pages, "subtree_shas": {}, "schema_version": 2}


class SelectPages(unittest.TestCase):
    def test_skips_filled_pages_by_default(self):
        cov = _cov({
            "raw/x/a.md": {"last_synced": "2026-05-15T00:00:00Z"},
            "raw/x/b.md": {"last_synced": None},
            "raw/x/c.md": {},
        })
        self.assertEqual(
            _select_pages(cov, glob=None, force=False),
            ["raw/x/b.md", "raw/x/c.md"],
        )

    def test_force_includes_filled_pages(self):
        cov = _cov({
            "raw/x/a.md": {"last_synced": "2026-05-15T00:00:00Z"},
            "raw/x/b.md": {"last_synced": None},
        })
        self.assertEqual(
            _select_pages(cov, glob=None, force=True),
            ["raw/x/a.md", "raw/x/b.md"],
        )

    def test_filter_glob_narrows_selection(self):
        cov = _cov({
            "raw/x/a.md":      {"last_synced": None},
            "raw/x/sub/b.md":  {"last_synced": None},
            "raw/y/c.md":      {"last_synced": None},
        })
        self.assertEqual(
            _select_pages(cov, glob="raw/x/*", force=False),
            ["raw/x/a.md", "raw/x/sub/b.md"],
        )

    def test_filter_is_case_sensitive(self):
        cov = _cov({
            "raw/X/a.md": {"last_synced": None},
            "raw/x/b.md": {"last_synced": None},
        })
        self.assertEqual(
            _select_pages(cov, glob="raw/x/*", force=False),
            ["raw/x/b.md"],
        )

    def test_returns_sorted(self):
        cov = _cov({
            "raw/x/z.md": {"last_synced": None},
            "raw/x/a.md": {"last_synced": None},
            "raw/x/m.md": {"last_synced": None},
        })
        self.assertEqual(
            _select_pages(cov, glob=None, force=False),
            ["raw/x/a.md", "raw/x/m.md", "raw/x/z.md"],
        )

    def test_empty_when_all_filled(self):
        cov = _cov({
            "raw/x/a.md": {"last_synced": "2026-05-15T00:00:00Z"},
            "raw/x/b.md": {"last_synced": "2026-05-15T00:00:00Z"},
        })
        self.assertEqual(_select_pages(cov, glob=None, force=False), [])


class BuildCmd(unittest.TestCase):
    def test_basic(self):
        cmd = _build_cmd("raw/x/a.md", model="qwen", force=False)
        self.assertIn("seed-agent", cmd)
        self.assertIn("raw/x/a.md", cmd)
        self.assertIn("qwen", cmd)
        self.assertNotIn("--overwrite", cmd)

    def test_force_adds_overwrite(self):
        cmd = _build_cmd("raw/x/a.md", model="qwen", force=True)
        self.assertIn("--overwrite", cmd)


if __name__ == "__main__":
    unittest.main()
