"""Unit tests for the site build preflight (D5).

The MkDocs build itself runs in an environment with the wheel installed
(CI or the user's venv) — we can't pip-install in the sandbox. So these
tests only cover the preflight checks: front-matter sanity and link
resolution. They give the CI job something to fail on *before* it spends
time launching MkDocs.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import _meta_io, build_site


class _IsolatedWiki:
    def setUp(self):  # noqa: D401
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "wiki" / "_meta").mkdir(parents=True)
        self._orig_wiki = _meta_io.WIKI_ROOT
        self._orig_bs_wiki = build_site.WIKI_ROOT
        self._orig_mkdocs = build_site.MKDOCS_YML
        _meta_io.WIKI_ROOT = self.root / "wiki"
        build_site.WIKI_ROOT = self.root / "wiki"
        build_site.MKDOCS_YML = self.root / "mkdocs.yml"
        # Default valid layout
        (self.root / "mkdocs.yml").write_text("site_name: test\n")
        (self.root / "wiki" / "index.md").write_text(
            "---\ntitle: Home\n---\n\n# Home\n")

    def tearDown(self):
        _meta_io.WIKI_ROOT = self._orig_wiki
        build_site.WIKI_ROOT = self._orig_bs_wiki
        build_site.MKDOCS_YML = self._orig_mkdocs


class PreflightTests(_IsolatedWiki, unittest.TestCase):
    def test_baseline_layout_passes(self):
        errors, warnings = build_site.preflight(verbose=False)
        self.assertEqual(errors, 0)
        self.assertEqual(warnings, 0)

    def test_missing_index_fails(self):
        (self.root / "wiki" / "index.md").unlink()
        errors, _ = build_site.preflight(verbose=False)
        self.assertGreaterEqual(errors, 1)

    def test_missing_mkdocs_fails(self):
        (self.root / "mkdocs.yml").unlink()
        errors, _ = build_site.preflight(verbose=False)
        self.assertGreaterEqual(errors, 1)

    def test_double_front_matter_detected(self):
        # The exact corruption shape we fixed during D3.
        (self.root / "wiki" / "bad.md").write_text(
            "---\n"
            "last_synced_sha: abc\n"
            "---\n"
            "\n"
            "---\n"
            "title: nested\n"
            "kind: subsystem\n"
            "---\n"
            "body\n"
        )
        errors, _ = build_site.preflight(verbose=False)
        self.assertGreaterEqual(errors, 1)

    def test_broken_wiki_link_is_warning_not_error(self):
        (self.root / "wiki" / "page.md").write_text(
            "---\ntitle: P\n---\n\nSee [[concepts/no_such]].\n")
        errors, warnings = build_site.preflight(verbose=False)
        self.assertEqual(errors, 0)
        self.assertEqual(warnings, 1)

    def test_existing_wiki_link_not_warned(self):
        (self.root / "wiki" / "concepts").mkdir()
        (self.root / "wiki" / "concepts" / "rcu.md").write_text(
            "---\ntitle: RCU\n---\n\n# RCU\n")
        (self.root / "wiki" / "page.md").write_text(
            "---\ntitle: P\n---\n\nSee [[concepts/rcu]] and [[concepts/rcu|RCU]].\n")
        errors, warnings = build_site.preflight(verbose=False)
        self.assertEqual(errors, 0)
        self.assertEqual(warnings, 0)

    def test_meta_directory_excluded_from_walk(self):
        # A bogus markdown under _meta/ must not be scanned (would produce a
        # spurious broken-link warning for our existing todo.md).
        (self.root / "wiki" / "_meta" / "spurious.md").write_text(
            "[[no/such]]\n")
        errors, warnings = build_site.preflight(verbose=False)
        self.assertEqual(errors, 0)
        self.assertEqual(warnings, 0)


if __name__ == "__main__":
    unittest.main()
