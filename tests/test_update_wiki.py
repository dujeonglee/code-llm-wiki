"""Unit tests for the page parser, response extractor, and the seed/update
pipelines with the mock LLM (D3)."""
from __future__ import annotations

import json
import os
import subprocess
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


class CoverageSchema(unittest.TestCase):
    """Schema v1 → v2 migration on Coverage.load()."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "coverage.json"

    def test_load_v1_drops_last_kernel_sha_and_starts_empty_subtree_shas(self):
        self.path.write_text(json.dumps({
            "schema_version": 1,
            "last_kernel_sha": "wiki-repo-head-from-buggy-old-cmd",
            "pages": {"raw/foo/x.md": {"covers": ["foo/x.c"]}},
        }))
        cov = _meta_io.Coverage.load(self.path)
        self.assertEqual(cov.schema_version, 2)
        self.assertEqual(cov.subtree_shas, {})
        # pages preserved verbatim.
        self.assertIn("raw/foo/x.md", cov.pages)
        # old field gone after re-save.
        cov.save(self.path)
        on_disk = json.loads(self.path.read_text())
        self.assertEqual(on_disk["schema_version"], 2)
        self.assertNotIn("last_kernel_sha", on_disk)
        self.assertIn("subtree_shas", on_disk)

    def test_round_trip_preserves_subtree_shas(self):
        self.path.write_text(json.dumps({
            "schema_version": 2,
            "subtree_shas": {"pcie_scsc": "abc123", "linux": "def456"},
            "pages": {},
        }))
        cov = _meta_io.Coverage.load(self.path)
        self.assertEqual(cov.subtree_shas["pcie_scsc"], "abc123")
        self.assertEqual(cov.subtree_shas["linux"], "def456")
        cov.save(self.path)
        on_disk = json.loads(self.path.read_text())
        self.assertEqual(on_disk["subtree_shas"]["pcie_scsc"], "abc123")
        self.assertEqual(on_disk["subtree_shas"]["linux"], "def456")


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

    def test_inner_code_fence_does_not_truncate(self):
        """Pages can contain ```c / ```python code blocks inside the body.
        The outer ```markdown ... ``` must pair greedily, not stop at the
        first inner ```.
        """
        resp = (
            "```markdown\n"
            "---\ntitle: T\n---\n\n"
            "intro paragraph\n\n"
            "```c\n"
            "struct s { int x; };\n"
            "```\n\n"
            "more body after the code block\n"
            "```\n"
        )
        out = extract_markdown_block(resp)
        self.assertIn("intro paragraph", out)
        self.assertIn("struct s", out)
        self.assertIn("more body after the code block", out)


class _IsolatedWiki:
    """Mixin: redirect wiki/_meta paths and WIKI_ROOT to a tempdir."""

    def setUp(self):  # noqa: D401
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "wiki" / "_meta").mkdir(parents=True)
        (root / "wiki" / "_meta" / "coverage.json").write_text(json.dumps({
            "schema_version": 2, "subtree_shas": {}, "pages": {}}))
        (root / "wiki" / "_meta" / "todo.md").write_text("# todo\n")
        self._orig = {
            "WIKI_ROOT": _meta_io.WIKI_ROOT,
            "COVERAGE_PATH": _meta_io.COVERAGE_PATH,
            "TODO_PATH": _meta_io.TODO_PATH,
            "uw_wiki": update_wiki.WIKI_ROOT,
            "uw_kernel": update_wiki.KERNEL_ROOT,
        }
        _meta_io.WIKI_ROOT = root / "wiki"
        _meta_io.COVERAGE_PATH = root / "wiki" / "_meta" / "coverage.json"
        _meta_io.TODO_PATH = root / "wiki" / "_meta" / "todo.md"
        update_wiki.WIKI_ROOT = root / "wiki"
        # Tests don't need a real raw tree; point KERNEL_ROOT at a missing
        # dir so _git_head / _resolve_subtree return None quietly.
        update_wiki.KERNEL_ROOT = root / "no-kernel-here"

    def tearDown(self):
        _meta_io.WIKI_ROOT = self._orig["WIKI_ROOT"]
        _meta_io.COVERAGE_PATH = self._orig["COVERAGE_PATH"]
        _meta_io.TODO_PATH = self._orig["TODO_PATH"]
        update_wiki.WIKI_ROOT = self._orig["uw_wiki"]
        update_wiki.KERNEL_ROOT = self._orig["uw_kernel"]


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
        cov.subtree_shas["mm"] = "deadbeef"
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
        ])
        self.assertEqual(rc, 0)

        updated = (_meta_io.WIKI_ROOT / page_rel).read_text()
        self.assertIn("last_synced_sha: cafef00d", updated)
        self.assertIn("mock-update at cafef00d", updated)
        self.assertIn("- mm/*.c", updated)  # covers preserved

        cov2 = json.loads(_meta_io.COVERAGE_PATH.read_text())
        self.assertEqual(cov2["subtree_shas"]["mm"], "cafef00d")
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
        cov.subtree_shas["mm"] = "deadbeef"
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
        ])
        self.assertEqual(rc, 0)


class QueryTests(_IsolatedWiki, unittest.TestCase):
    """D7-lite: query subcommand writes a saved artifact with full
    provenance and no freshness scoring."""

    def setUp(self):
        super().setUp()
        # Lay down the three real templates by copying from the live repo.
        # We point TEMPLATE_DIR (resolved through update_wiki.WIKI_ROOT) at
        # the temp wiki and create stub templates inline so tests are
        # hermetic.
        tpl_dir = _meta_io.WIKI_ROOT / "queries" / "_templates"
        tpl_dir.mkdir(parents=True)
        for tid in ("code-review", "porting-guide", "feature-impl"):
            (tpl_dir / f"{tid}.md").write_text(
                f"---\ntemplate_id: {tid}\n---\n\n"
                "# System prompt\n\n"
                "You are a careful reviewer. Ground every claim in [[pages]].\n\n"
                "# User message scaffold\n\nIgnored at runtime.\n"
            )
        # The query command reads TEMPLATE_DIR via update_wiki, which we
        # already redirected to the temp wiki in _IsolatedWiki.setUp().
        update_wiki.TEMPLATE_DIR = tpl_dir

    def test_code_review_writes_artifact_with_provenance(self):
        # Seed a wiki page so the query has something to cite.
        (_meta_io.WIKI_ROOT / "subsystems").mkdir()
        (_meta_io.WIKI_ROOT / "subsystems" / "mm.md").write_text(
            "---\ntitle: MM\nkind: subsystem\ncovers: [mm/*.c]\n"
            "last_synced_sha: deadbeef\n---\n\nmm body\n")
        cov = _meta_io.Coverage.load()
        cov.subtree_shas["mm"] = "deadbeef"
        cov.pages["subsystems/mm.md"] = {
            "kind": "subsystem", "covers": ["mm/*.c"],
            "last_synced_sha": "deadbeef", "last_synced": None,
        }
        cov.save()

        patch = Path(self.tmp.name) / "patch.diff"
        patch.write_text("--- a/mm/slab.c\n+++ b/mm/slab.c\n@@\n- x\n+ y\n")

        out = Path(self.tmp.name) / "out.md"
        rc = update_wiki._main([
            "query",
            "--template", "code-review",
            "--input", str(patch),
            "--pages", "subsystems/mm.md",
            "--out", str(out),
            "--mock-llm",
        ])
        self.assertEqual(rc, 0)
        fm, body = _meta_io.parse_front_matter(out.read_text())
        # Provenance must be recorded.
        self.assertEqual(fm["template"], "code-review")
        self.assertEqual(fm["kind"], "query")
        # sources is "path@sha" so the sha at query time is preserved even
        # if the page is later re-synced.
        self.assertEqual(fm["sources"], ["subsystems/mm.md@deadbeef"])
        self.assertEqual(fm["kernel_sha_at_query"], "deadbeef")
        self.assertEqual(fm["llm_model"], "mock")
        self.assertIn("produced", fm)
        # The reuse policy line is mandatory so humans can't pretend they
        # didn't see it.
        self.assertIn("single-use", str(fm["reuse_policy"]).lower())
        # Body comes from the mock LLM and includes the structured headings.
        self.assertIn("## Summary", body)

    def test_porting_guide_requires_target_and_feature(self):
        out = Path(self.tmp.name) / "out.md"
        with self.assertRaises(SystemExit):
            update_wiki._main([
                "query", "--template", "porting-guide",
                "--out", str(out), "--mock-llm",
            ])

    def test_feature_impl_minimal_inputs(self):
        out = Path(self.tmp.name) / "out.md"
        rc = update_wiki._main([
            "query", "--template", "feature-impl",
            "--feature", "add a memory pressure callback to slab",
            "--out", str(out), "--mock-llm",
        ])
        self.assertEqual(rc, 0)
        fm, _ = _meta_io.parse_front_matter(out.read_text())
        self.assertEqual(fm["template"], "feature-impl")
        # sources is allowed to be empty (no --pages given).
        self.assertEqual(fm["sources"], [])

    def test_no_freshness_field_recorded(self):
        """We deliberately do NOT compute a freshness/staleness score —
        that's the central D7-lite decision. Regression-guard it."""
        out = Path(self.tmp.name) / "out.md"
        update_wiki._main([
            "query", "--template", "feature-impl",
            "--feature", "x",
            "--out", str(out), "--mock-llm",
        ])
        fm, _ = _meta_io.parse_front_matter(out.read_text())
        self.assertNotIn("freshness", fm)
        self.assertNotIn("stale", str(fm).lower())


class SubtreeRoutingTests(_IsolatedWiki, unittest.TestCase):
    """Cover the per-sub-tree sha resolution: each raw/<top>/ git repo
    answers for its own pages, not the parent wiki repo."""

    def test_resolve_subtree_single_segment(self):
        kernel = Path(self.tmp.name) / "raw"
        (kernel / "foo").mkdir(parents=True)
        update_wiki.KERNEL_ROOT = kernel
        self.assertEqual(
            update_wiki._resolve_subtree(["foo/a.c", "foo/b.h"]),
            kernel / "foo",
        )

    def test_resolve_subtree_none_when_covers_span_subtrees(self):
        kernel = Path(self.tmp.name) / "raw"
        (kernel / "foo").mkdir(parents=True)
        (kernel / "bar").mkdir(parents=True)
        update_wiki.KERNEL_ROOT = kernel
        self.assertIsNone(
            update_wiki._resolve_subtree(["foo/a.c", "bar/b.c"])
        )

    def test_resolve_subtree_none_for_missing_path(self):
        kernel = Path(self.tmp.name) / "raw"
        kernel.mkdir()
        update_wiki.KERNEL_ROOT = kernel
        self.assertIsNone(
            update_wiki._resolve_subtree(["no_such_top/a.c"])
        )

    def test_git_head_returns_subtree_sha_when_git_repo_present(self):
        """Per-subtree git resolution: _git_head against a real sub-tree
        git returns that tree's HEAD, not the parent repo's."""
        kernel = Path(self.tmp.name) / "raw"
        sub = kernel / "foo"
        sub.mkdir(parents=True)
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "init", "-q"], cwd=sub, check=True, env=env)
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"],
                       cwd=sub, check=True, env=env)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=sub, text=True).strip()
        update_wiki.KERNEL_ROOT = kernel
        resolved = update_wiki._resolve_subtree(["foo/x.c"])
        self.assertEqual(resolved, sub)
        self.assertEqual(update_wiki._git_head(resolved), head)

    def test_git_head_returns_none_for_non_git_subtree(self):
        update_wiki.KERNEL_ROOT = Path(self.tmp.name) / "raw"
        (update_wiki.KERNEL_ROOT / "foo").mkdir(parents=True)
        self.assertIsNone(
            update_wiki._git_head(update_wiki._resolve_subtree(["foo/x.c"]))
        )


if __name__ == "__main__":
    unittest.main()
