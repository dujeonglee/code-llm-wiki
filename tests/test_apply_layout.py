"""Unit tests for scripts.apply_layout.

The propose half (LLM call) is not unit-tested here — it requires the
agent SDK and a live or mocked backend. The apply half is pure plumbing:
parse YAML, write stubs, merge coverage. All branches are exercised.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import _meta_io, apply_layout
from scripts.apply_layout import (
    LayoutError,
    _apply,
    _normalize_entries,
)


def _proposal(top: str, *, subsystems=(), concepts=()) -> str:
    lines = [
        "---",
        "template: layout-proposal",
        f"tree: raw/{top}",
        "sha: deadbeef",
        'llm_profile: "ollama"',
        'llm_model: "qwen"',
        "produced: 2026-05-16T00:00:00Z",
        "---",
        "",
    ]
    if subsystems:
        lines.append("subsystems:")
        for s in subsystems:
            lines.append(f"  - title: {s['title']!r}")
            lines.append(f"    basename: {s['basename']}")
            lines.append(f"    covers: {list(s['covers'])}")
            lines.append(f"    rationale: {s.get('rationale', '')!r}")
    if concepts:
        lines.append("concepts:")
        for c in concepts:
            lines.append(f"  - title: {c['title']!r}")
            lines.append(f"    basename: {c['basename']}")
            lines.append(f"    covers: {list(c['covers'])}")
            lines.append(f"    rationale: {c.get('rationale', '')!r}")
    return "\n".join(lines) + "\n"


class NormalizeTests(unittest.TestCase):
    def test_flattens_both_kinds_with_kind_tag(self):
        out = _normalize_entries({
            "subsystems": [{
                "title": "MLME",
                "basename": "_mlme",
                "covers": ["pcie_scsc/mlme*.c"],
                "rationale": "cluster",
            }],
            "concepts": [{
                "title": "FAPI",
                "basename": "_fapi",
                "covers": ["pcie_scsc/fapi.h"],
            }],
        })
        self.assertEqual([(e["kind"], e["basename"]) for e in out],
                         [("subsystem", "_mlme"), ("concept", "_fapi")])

    def test_rejects_missing_field(self):
        with self.assertRaises(LayoutError):
            _normalize_entries({
                "subsystems": [{"title": "x", "basename": "y"}],
            })

    def test_rejects_slash_in_basename(self):
        with self.assertRaises(LayoutError):
            _normalize_entries({
                "subsystems": [{
                    "title": "x", "basename": "sub/x",
                    "covers": ["a"],
                }],
            })

    def test_rejects_md_suffix_in_basename(self):
        with self.assertRaises(LayoutError):
            _normalize_entries({
                "concepts": [{
                    "title": "x", "basename": "_x.md", "covers": ["a"],
                }],
            })

    def test_rejects_empty_covers(self):
        with self.assertRaises(LayoutError):
            _normalize_entries({
                "subsystems": [{
                    "title": "x", "basename": "_x", "covers": [],
                }],
            })

    def test_rejects_duplicate_basename(self):
        with self.assertRaises(LayoutError):
            _normalize_entries({
                "subsystems": [{
                    "title": "A", "basename": "_x", "covers": ["a"]}],
                "concepts": [{
                    "title": "B", "basename": "_x", "covers": ["b"]}],
            })


class _IsolatedRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "wiki" / "_meta").mkdir(parents=True)
        self.wiki_root = root / "wiki"
        self.cov_path = root / "wiki" / "_meta" / "coverage.json"
        self.cov_path.write_text(json.dumps({
            "schema_version": 2,
            "subtree_shas": {},
            "pages": {
                "raw/pcie_scsc/dev.md": {
                    "kind": "entity",
                    "covers": ["pcie_scsc/dev.c", "pcie_scsc/dev.h"],
                    "last_synced_sha": None,
                    "last_synced": None,
                },
            },
        }))
        self._orig = {
            "WIKI_ROOT_io": _meta_io.WIKI_ROOT,
            "COV_io": _meta_io.COVERAGE_PATH,
            "WIKI_ROOT_al": apply_layout.WIKI_ROOT,
            "COV_al": apply_layout.COVERAGE_PATH,
        }
        _meta_io.WIKI_ROOT = self.wiki_root
        _meta_io.COVERAGE_PATH = self.cov_path
        apply_layout.WIKI_ROOT = self.wiki_root
        apply_layout.COVERAGE_PATH = self.cov_path

    def tearDown(self):
        _meta_io.WIKI_ROOT = self._orig["WIKI_ROOT_io"]
        _meta_io.COVERAGE_PATH = self._orig["COV_io"]
        apply_layout.WIKI_ROOT = self._orig["WIKI_ROOT_al"]
        apply_layout.COVERAGE_PATH = self._orig["COV_al"]

    def _write(self, name: str, text: str) -> Path:
        p = Path(self.tmp.name) / name
        p.write_text(text)
        return p


class ApplyTests(_IsolatedRepo):
    def test_creates_pages_and_merges_coverage(self):
        path = self._write("p.yaml", _proposal(
            "pcie_scsc",
            subsystems=[{
                "title": "MLME overview", "basename": "_mlme",
                "covers": ["pcie_scsc/mlme*.c"],
                "rationale": "MLME cluster",
            }],
            concepts=[{
                "title": "FAPI signaling", "basename": "_fapi",
                "covers": ["pcie_scsc/fapi.h", "pcie_scsc/mlme.c"],
            }],
        ))
        rc = _apply(path, force=False, dry_run=False)
        self.assertEqual(rc, 0)

        # Files written
        mlme = self.wiki_root / "raw" / "pcie_scsc" / "_mlme.md"
        fapi = self.wiki_root / "raw" / "pcie_scsc" / "_fapi.md"
        self.assertTrue(mlme.exists())
        self.assertTrue(fapi.exists())

        # Front-matter shape
        mlme_text = mlme.read_text()
        self.assertIn("kind: subsystem", mlme_text)
        self.assertIn("title: MLME overview", mlme_text)
        self.assertIn("last_synced_sha: null", mlme_text)
        self.assertIn("last_synced: null", mlme_text)
        self.assertIn("- pcie_scsc/mlme*.c", mlme_text)

        # Coverage merged: pre-existing dev.md still there, plus the 2 new
        cov = json.loads(self.cov_path.read_text())
        self.assertIn("raw/pcie_scsc/dev.md", cov["pages"])
        self.assertEqual(
            cov["pages"]["raw/pcie_scsc/_mlme.md"]["kind"], "subsystem")
        self.assertEqual(
            cov["pages"]["raw/pcie_scsc/_fapi.md"]["kind"], "concept")

    def test_dry_run_writes_nothing(self):
        path = self._write("p.yaml", _proposal(
            "pcie_scsc",
            subsystems=[{
                "title": "X", "basename": "_x", "covers": ["pcie_scsc/x.c"],
            }],
        ))
        rc = _apply(path, force=False, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertFalse(
            (self.wiki_root / "raw" / "pcie_scsc" / "_x.md").exists())
        # coverage unchanged
        cov = json.loads(self.cov_path.read_text())
        self.assertNotIn("raw/pcie_scsc/_x.md", cov["pages"])

    def test_skip_existing_is_idempotent(self):
        path = self._write("p.yaml", _proposal(
            "pcie_scsc",
            subsystems=[{
                "title": "X", "basename": "_x", "covers": ["pcie_scsc/x.c"],
            }],
        ))
        # first run creates
        _apply(path, force=False, dry_run=False)
        page = self.wiki_root / "raw" / "pcie_scsc" / "_x.md"
        page.write_text("---\nedited: true\n---\n\n# edited\n")
        # second run must NOT clobber the user/LLM-edited body
        _apply(path, force=False, dry_run=False)
        self.assertIn("edited: true", page.read_text())

    def test_force_overwrites(self):
        path = self._write("p.yaml", _proposal(
            "pcie_scsc",
            subsystems=[{
                "title": "X", "basename": "_x", "covers": ["pcie_scsc/x.c"],
            }],
        ))
        _apply(path, force=False, dry_run=False)
        page = self.wiki_root / "raw" / "pcie_scsc" / "_x.md"
        page.write_text("---\nedited: true\n---\n\n# edited\n")
        _apply(path, force=True, dry_run=False)
        text = page.read_text()
        self.assertNotIn("edited: true", text)
        self.assertIn("kind: subsystem", text)

    def test_rejects_tree_outside_raw(self):
        path = self._write("p.yaml", _proposal("pcie_scsc").replace(
            "tree: raw/pcie_scsc", "tree: somewhere/else"))
        with self.assertRaises(LayoutError):
            _apply(path, force=False, dry_run=False)

    def test_empty_proposal_returns_ok(self):
        path = self._write("p.yaml", _proposal("pcie_scsc"))
        rc = _apply(path, force=False, dry_run=False)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
