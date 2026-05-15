"""Unit tests for scripts.sync_subtree.

Covers the per-sub-tree sha tracking, manifest shape, and `--record`
side-effect on coverage.subtree_shas. Each test points the module at a
tempdir holding a real local git repo so the CLI's git invocations get
real shas to work with.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import _meta_io, sync_subtree
from scripts._meta_io import Coverage


def _git_init(repo: Path) -> str:
    """Create a git repo at `repo` with one empty commit. Returns HEAD sha."""
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=repo, check=True, env=env,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
    ).strip()


def _git_commit_file(repo: Path, rel: str, body: str = "x\n") -> str:
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(body)
    subprocess.run(["git", "add", rel], cwd=repo, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", f"touch {rel}"],
        cwd=repo, check=True, env=env,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
    ).strip()


class _IsolatedCov:
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "wiki" / "_meta").mkdir(parents=True)
        self.cov_path = self.root / "wiki" / "_meta" / "coverage.json"
        self.cov_path.write_text(json.dumps({
            "schema_version": 2, "subtree_shas": {}, "pages": {}}))
        self._orig_cov = _meta_io.COVERAGE_PATH
        _meta_io.COVERAGE_PATH = self.cov_path

    def tearDown(self):
        _meta_io.COVERAGE_PATH = self._orig_cov


class BuildManifest(_IsolatedCov, unittest.TestCase):
    def test_first_run_emits_empty_manifest(self):
        sub = self.root / "raw" / "foo"
        _git_init(sub)
        m = sync_subtree.build_manifest(
            sub, remote="origin", branch="main",
            do_fetch=False, max_commits=10,
        )
        self.assertIsNone(m["from"])
        self.assertEqual(m["files"], [])
        self.assertEqual(m["commits"], [])
        # tree path captured for downstream tools.
        self.assertEqual(Path(m["tree"]), sub)

    def test_diff_after_recorded_sha_lists_changed_files(self):
        sub = self.root / "raw" / "foo"
        old_sha = _git_init(sub)
        cov = Coverage.load()
        cov.subtree_shas["foo"] = old_sha
        cov.save()

        _git_commit_file(sub, "a.c", "hello\n")
        new_sha = _git_commit_file(sub, "b.c", "world\n")

        m = sync_subtree.build_manifest(
            sub, remote="origin", branch="main",
            do_fetch=False, max_commits=10,
        )
        self.assertEqual(m["from"], old_sha)
        self.assertEqual(m["to"], new_sha)
        # Files are prefixed with <top>/ so they match KERNEL_ROOT-relative
        # covers.
        self.assertEqual(sorted(m["files"]), ["foo/a.c", "foo/b.c"])
        self.assertEqual(len(m["commits"]), 2)

    def test_record_writes_subtree_shas(self):
        sub = self.root / "raw" / "foo"
        head = _git_init(sub)
        sync_subtree._record_new_sha("foo", head)
        cov = Coverage.load()
        self.assertEqual(cov.subtree_shas["foo"], head)


class CliEntry(_IsolatedCov, unittest.TestCase):
    def test_missing_tree_rejected_cleanly(self):
        # Tree path doesn't exist → SystemExit, not Python traceback.
        missing = self.root / "raw" / "does-not-exist"
        # Need to call build_manifest directly since _main parses CLI; either
        # path raises SystemExit. We chose the direct call to avoid argparse
        # printing usage on stderr in the test output.
        with self.assertRaises(SystemExit):
            sync_subtree.build_manifest(
                missing, remote="origin", branch="main",
                do_fetch=False, max_commits=10,
            )

    def test_non_git_dir_rejected_cleanly(self):
        plain = self.root / "raw" / "plain"
        plain.mkdir(parents=True)
        with self.assertRaises(SystemExit):
            sync_subtree.build_manifest(
                plain, remote="origin", branch="main",
                do_fetch=False, max_commits=10,
            )


if __name__ == "__main__":
    unittest.main()
