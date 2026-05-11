"""Unit tests for the page parser, response extractor, and the seed/update
pipelines with the mock LLM (D3)."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import _meta_io, update_wiki
from scripts._meta_io import (
    extract_markdown_block,
    parse_front_matter,
    serialize_page,
)


class FrontMatterTests(unittest.TestCase):
    def test_roundtrip_with_block_list(self):
        text = (
            "---\n"
            "title: Memory Management\n"
            "kind: subsystem\n"
            "covers:\n"
            "  - mm/*.c\n"
            "  - mm/*.h\n"
            "last_synced_sha: deadbeef\n"
            "---\n"
            "\n"
            "# body here\n"
        )
        fm, body = parse_front_matter(text)
        self.assertEqual(fm["title"], "Memory Management")
        self.assertEqual(fm["kind"], "subsystem")
        self.assertEqual(fm["covers"], ["mm/*.c", "mm/*.h"])
        self.assertEqual(fm["last_synced_sha"], "deadbeef")
        self.assertIn("body here", body)
        rendered = serialize_page(fm, body)
        fm2, body2 = parse_front_matter(rendered)
        self.assertEqual(fm2["covers"], ["mm/*.c", "mm/*.h"])
        self.assertEqual(fm2["kind"], "subsystem")
        self.assertEqual(body2.strip(), "# body here")

    def test_null_and_empty_list(self):
        text = (
            "---\n"
            "title: Empty\n"
            "covers: []\n"
            "last_synced: null\n"
            "---\n"
            "body\n"
        )
        fm, body = parse_front_matter(text)
        self.assertEqual(fm["covers"], [])
        self.assertIsNone(fm["last_synced"])

    def test_no_front_matter(self):
        text = "no header here\nbody only"
        fm, body = parse_front_matter(text)
        self.assertEqual(fm, {})
        self.assertEqual(body, text)


class ExtractorTests(unittest.TestCase):
    def test_fenced_block(self):
        resp = ("Sure! Here is the page:\n\n```markdown\n"
                "---\ntitle: T\n---\n\nbody\n```\n\n"
                "Hope that helps!")
        out = extract_markdown_block(resp)
        self.assertTrue(out.startswith("---\ntitle: T\n---"))
        self.assertNotIn("Hope that helps", out)

    def test_no_fence_falls_back(self):
        resp = "---\ntitle: T\n---\nbody\n"
        out = extract_markdown_block(resp)
        self.assertIn("title: T", out)


class _IsolatedWiki:
    """Mixin: redirect wiki/_meta paths and WIKI_ROOT to a tempdir."""

    def setUp(self):  # noqa: D401
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "wiki" / "_meta").mkdir(parents=True)
        (root / "wiki" / "_meta" / "coverage.json").write_text(json.dumps({
            "schema_version": 1, "last_kernel_sha": None, "pages": {}}))
        (root / "wiki" / "_meta" / "todo.md").write_text("# todo\n")
        self._orig = {
            "WIKI_ROOT": _meta_io.WIKI_ROOT,
            "COVERAGE_PATH": _meta_io.COVERAGE_PATH,
            "TODO_PATH": _meta_io.TODO_PATH,
            "uw_wiki": update_wiki.WIKI_ROOT,
        }
        _meta_io.WIKI_ROOT = root / "wiki"
        _meta_io.COVERAGE_PATH = root / "wiki" / "_meta" / "coverage.json"
        _meta_io.TODO_PATH = root / "wiki" / "_meta" / "todo.md"
        update_wiki.WIKI_ROOT = root / "wiki"

    def tearDown(self):
        _meta_io.WIKI_ROOT = self._orig["WIKI_ROOT"]
        _meta_io.COVERAGE_PATH = self._orig["COVERAGE_PATH"]
        _meta_io.TODO_PATH = self._orig["TODO_PATH"]
        update_wiki.WIKI_ROOT = self._orig["uw_wiki"]


class SeedTests(_IsolatedWiki, unittest.TestCase):
    def test_seed_with_mock_llm_writes_page_and_coverage(self):
        rc = update_wiki._main([
            "seed",
            "--page", "subsystems/mm.md",
            "--kind", "subsystem",
            "--covers", "mm/*.c", "mm/*.h",
            "--mock-llm",
            "--kernel-dir", "/does/not/exist",
        ])
        self.assertEqual(rc, 0)
        page = (_meta_io.WIKI_ROOT / "subsystems" / "mm.md").read_text()
        self.assertIn("kind: subsystem", page)
        self.assertIn("- mm/*.c", page)
        self.assertIn("- mm/*.h", page)
        self.assertIn("## Recent changes", page)
        cov = json.loads(_meta_io.COVERAGE_PATH.read_text())
        self.assertIn("subsystems/mm.md", cov["pages"])
        self.assertEqual(cov["pages"]["subsystems/mm.md"]["covers"],
                         ["mm/*.c", "mm/*.h"])

    def test_seed_refuses_to_overwrite(self):
        # first seed
        update_wiki._main([
            "seed", "--page", "x.md", "--kind", "concept",
            "--covers", "a/*", "--mock-llm",
            "--kernel-dir", "/none",
        ])
        # second seed without --overwrite should fail
        rc = update_wiki._main([
            "seed", "--page", "x.md", "--kind", "concept",
            "--covers", "a/*", "--mock-llm",
            "--kernel-dir", "/none",
        ])
        self.assertEqual(rc, 2)
        # with --overwrite, succeeds
        rc = update_wiki._main([
            "seed", "--page", "x.md", "--kind", "concept",
            "--covers", "a/*", "--mock-llm",
            "--kernel-dir", "/none",
            "--overwrite",
        ])
        self.assertEqual(rc, 0)


class UpdateTests(_IsolatedWiki, unittest.TestCase):
    def test_update_patches_existing_page(self):
        page_rel = "subsystems/mm.md"
        (_meta_io.WIKI_ROOT / "subsystems").mkdir(parents=True)
        (_meta_io.WIKI_ROOT / page_rel).write_text(
            "---\n"
            "title: Memory Management\n"
            "kind: subsystem\n"
            "covers:\n"
            "  - mm/*.c\n"
            "last_synced_sha: deadbeef\n"
            "last_synced: 2026-05-01T00:00:00Z\n"
            "---\n"
            "\n"
            "# Memory Management\n\n"
            "Original body.\n"
        )
        # pre-populate coverage so the update path's setdefault works
        cov = _meta_io.Coverage.load()
        cov.last_kernel_sha = "deadbeef"
        cov.pages[page_rel] = {
            "kind": "subsystem",
            "covers": ["mm/*.c"],
            "last_synced_sha": "deadbeef",
            "last_synced": "2026-05-01T00:00:00Z",
        }
        cov.save()

        routing = {
            "from": "deadbeef",
            "to": "cafef00d",
            "n_files": 1,
            "affected_pages": [page_rel],
            "uncovered": [],
            "commits": ["cafef00d slab: tighten kfree_rcu()"],
        }
        routing_path = Path(self.tmp.name) / "routing.json"
        routing_path.write_text(json.dumps(routing))

        rc = update_wiki._main([
            "update",
            "--routing", str(routing_path),
            "--mock-llm",
            "--kernel-dir", "/does/not/exist",
        ])
        self.assertEqual(rc, 0)

        updated = (_meta_io.WIKI_ROOT / page_rel).read_text()
        self.assertIn("last_synced_sha: cafef00d", updated)
        self.assertIn("mock-update at cafef00d", updated)
        self.assertIn("- mm/*.c", updated)  # covers preserved

        cov2 = json.loads(_meta_io.COVERAGE_PATH.read_text())
        self.assertEqual(cov2["last_kernel_sha"], "cafef00d")
        self.assertEqual(cov2["pages"][page_rel]["last_synced_sha"],
                         "cafef00d")
        self.assertEqual(cov2["pages"][page_rel]["covers"], ["mm/*.c"])

    def test_update_preserves_unrelated_front_matter_fields(self):
        """Even if the LLM's response front-matter only sets a few fields,
        the merge step must keep title/kind/sources from the existing page."""
        page_rel = "subsystems/mm.md"
        (_meta_io.WIKI_ROOT / "subsystems").mkdir(parents=True)
        (_meta_io.WIKI_ROOT / page_rel).write_text(
            "---\n"
            "title: Memory Management\n"
            "kind: subsystem\n"
            "covers:\n"
            "  - mm/*.c\n"
            "last_synced_sha: deadbeef\n"
            "last_synced: 2026-05-01T00:00:00Z\n"
            "sources:\n"
            "  - mm/slab.c#L1-L100\n"
            "---\n"
            "\nbody\n"
        )
        cov = _meta_io.Coverage.load()
        cov.last_kernel_sha = "deadbeef"
        cov.pages[page_rel] = {"kind": "subsystem", "covers": ["mm/*.c"],
                               "last_synced_sha": "deadbeef",
                               "last_synced": "2026-05-01T00:00:00Z"}
        cov.save()
        routing = {"from": "deadbeef", "to": "feedface",
                   "affected_pages": [page_rel], "uncovered": [],
                   "commits": []}
        rpath = Path(self.tmp.name) / "r.json"
        rpath.write_text(json.dumps(routing))
        rc = update_wiki._main([
            "update", "--routing", str(rpath), "--mock-llm",
            "--kernel-dir", "/none",
        ])
        self.assertEqual(rc, 0)
        page = (_meta_io.WIKI_ROOT / page_rel).read_text()
        # The mock LLM preserves the fm it parsed; the merge guarantees
        # title/kind/sources persist regardless of what the LLM did.
        self.assertIn("title: Memory Management", page)
        self.assertIn("kind: subsystem", page)
        self.assertIn("mm/slab.c#L1-L100", page)
        self.assertIn("last_synced_sha: feedface", page)
        # Single front-matter block — no duplication.
        self.assertEqual(page.count("\n---\n"), 1)

    def test_update_with_empty_affected_pages_is_a_noop(self):
        routing = {"from": "a", "to": "b", "affected_pages": [],
                   "uncovered": [], "commits": []}
        rpath = Path(self.tmp.name) / "r.json"
        rpath.write_text(json.dumps(routing))
        rc = update_wiki._main([
            "update", "--routing", str(rpath), "--mock-llm",
            "--kernel-dir", "/none",
        ])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
