"""Unit tests for scripts.propose_layout.

The agent SDK call itself is not unit-tested (requires a live backend).
Only the pure helpers — prompt assembly and YAML fence extraction — get
coverage here, since those are where regressions would silently corrupt
proposals.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from scripts.propose_layout import _build_user_prompt, _extract_yaml


class PromptTests(unittest.TestCase):
    def test_no_exclude_omits_exclude_line(self):
        p = _build_user_prompt(Path("raw/pcie_scsc"), exclude=[])
        self.assertIn("TASK: WIKI LAYOUT PROPOSAL", p)
        self.assertIn("TREE: raw/pcie_scsc", p)
        self.assertIn("TOP NAME (for basename hints): pcie_scsc", p)
        self.assertIn("COVERS PREFIX (use this in every cover glob): "
                      "pcie_scsc/", p)
        self.assertNotIn("EXCLUDE", p)

    def test_single_exclude_appears_in_prompt(self):
        p = _build_user_prompt(Path("raw/pcie_scsc"), exclude=["kunit"])
        self.assertIn("EXCLUDE", p)
        self.assertIn("kunit", p)

    def test_multiple_excludes_joined(self):
        p = _build_user_prompt(Path("raw/pcie_scsc"),
                               exclude=["kunit", "test"])
        self.assertRegex(p, r"EXCLUDE.*kunit.*test")


class ExtractYamlTests(unittest.TestCase):
    def test_extracts_fenced_yaml(self):
        text = """Here is the proposal:

```yaml
subsystems:
  - title: MLME
    basename: _mlme
    covers: [pcie_scsc/mlme*.c]
    rationale: cluster
```
"""
        out = _extract_yaml(text)
        self.assertIsNotNone(out)
        self.assertIn("subsystems:", out)
        self.assertIn("title: MLME", out)
        self.assertTrue(out.endswith("\n"))

    def test_accepts_yml_tag(self):
        text = "```yml\nfoo: bar\n```\n"
        self.assertEqual(_extract_yaml(text), "foo: bar\n")

    def test_accepts_untagged_fence(self):
        text = "```\nfoo: bar\n```\n"
        self.assertEqual(_extract_yaml(text), "foo: bar\n")

    def test_returns_none_when_no_fence(self):
        self.assertIsNone(_extract_yaml("just text, no fences"))


if __name__ == "__main__":
    unittest.main()
