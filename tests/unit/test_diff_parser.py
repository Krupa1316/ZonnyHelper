"""Unit tests for git/diff_parser.py."""
from __future__ import annotations

import pytest

from zonny_core.git.diff_parser import (
    DiffFile,
    diff_stats,
    parse_diff,
    truncate_diff,
)

# ── Fixtures / sample data ────────────────────────────────────────────────────

SIMPLE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
index 1234567..abcdefg 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,5 +1,7 @@
 def hello():
-    print("hi")
+    print("hello")
+    print("world")
     return True
"""

TWO_FILE_DIFF = """\
diff --git a/alpha.py b/alpha.py
index 0000001..0000002 100644
--- a/alpha.py
+++ b/alpha.py
@@ -1,3 +1,4 @@
 x = 1
-y = 2
+y = 3
+z = 4
 end = True
diff --git a/beta.js b/beta.js
index 0000003..0000004 100644
--- a/beta.js
+++ b/beta.js
@@ -10,3 +10,2 @@
 const a = 1;
-const b = 2;
 const c = 3;
"""

EMPTY_DIFF = ""
WHITESPACE_DIFF = "   \n\t\n"


# ── parse_diff tests ──────────────────────────────────────────────────────────


class TestParseDiff:
    def test_empty_diff_returns_empty_list(self) -> None:
        assert parse_diff(EMPTY_DIFF) == []

    def test_whitespace_diff_returns_empty_list(self) -> None:
        assert parse_diff(WHITESPACE_DIFF) == []

    def test_simple_diff_returns_one_file(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        assert len(files) == 1

    def test_simple_diff_path(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        assert files[0].path == "src/foo.py"

    def test_simple_diff_addition_count(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        # Two lines starting with '+' (not '+++')
        assert files[0].additions == 2

    def test_simple_diff_deletion_count(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        # One line starting with '-' (not '---')
        assert files[0].deletions == 1

    def test_simple_diff_has_hunks(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        assert len(files[0].hunks) == 1
        assert "@@ -1,5 +1,7 @@" in files[0].hunks[0]

    def test_two_file_diff_returns_two_files(self) -> None:
        files = parse_diff(TWO_FILE_DIFF)
        assert len(files) == 2

    def test_two_file_diff_paths(self) -> None:
        files = parse_diff(TWO_FILE_DIFF)
        paths = [f.path for f in files]
        assert "alpha.py" in paths
        assert "beta.js" in paths

    def test_two_file_diff_additions(self) -> None:
        files = parse_diff(TWO_FILE_DIFF)
        alpha = next(f for f in files if f.path == "alpha.py")
        assert alpha.additions == 2
        assert alpha.deletions == 1

    def test_two_file_diff_beta_deletions(self) -> None:
        files = parse_diff(TWO_FILE_DIFF)
        beta = next(f for f in files if f.path == "beta.js")
        assert beta.deletions == 1
        assert beta.additions == 0

    def test_diff_file_raw_property(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        raw = files[0].raw
        assert "@@ -1,5 +1,7 @@" in raw

    def test_returns_list_of_difffile_instances(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        assert all(isinstance(f, DiffFile) for f in files)


# ── diff_stats tests ──────────────────────────────────────────────────────────


class TestDiffStats:
    def test_empty_list(self) -> None:
        stats = diff_stats([])
        assert stats == {"files_changed": 0, "additions": 0, "deletions": 0}

    def test_single_file(self) -> None:
        files = parse_diff(SIMPLE_DIFF)
        stats = diff_stats(files)
        assert stats["files_changed"] == 1
        assert stats["additions"] == 2
        assert stats["deletions"] == 1

    def test_two_files(self) -> None:
        files = parse_diff(TWO_FILE_DIFF)
        stats = diff_stats(files)
        assert stats["files_changed"] == 2
        assert stats["additions"] == 2   # 2 in alpha, 0 in beta
        assert stats["deletions"] == 2   # 1 in alpha, 1 in beta

    def test_keys_present(self) -> None:
        stats = diff_stats([])
        assert "files_changed" in stats
        assert "additions" in stats
        assert "deletions" in stats


# ── truncate_diff tests ───────────────────────────────────────────────────────


class TestTruncateDiff:
    def test_short_diff_unchanged(self) -> None:
        result = truncate_diff(SIMPLE_DIFF, max_chars=100_000)
        assert result == SIMPLE_DIFF

    def test_truncation_cuts_at_file_boundary(self) -> None:
        # Make a diff that is just over max_chars when both files are included
        big_diff = TWO_FILE_DIFF
        # Force truncation to happen before the second file
        # The first file block starts at pos 0
        first_file_end = big_diff.index("diff --git a/beta.js")
        result = truncate_diff(big_diff, max_chars=first_file_end - 1)
        # Should not contain the second file header
        assert "beta.js" not in result

    def test_truncation_adds_notice(self) -> None:
        big_diff = TWO_FILE_DIFF
        first_file_end = big_diff.index("diff --git a/beta.js")
        result = truncate_diff(big_diff, max_chars=first_file_end - 1)
        assert "truncated" in result.lower()

    def test_single_huge_file_hard_truncated(self) -> None:
        # A diff with no second file to cut at — should hard-truncate
        huge = SIMPLE_DIFF + ("x" * 200_000)
        result = truncate_diff(huge, max_chars=100)
        assert len(result) <= 200  # Some leeway for the notice
        assert "truncated" in result.lower()

    def test_output_length_lte_max_chars_plus_notice(self) -> None:
        # Result may be slightly longer than max_chars due to appended notice
        big_diff = TWO_FILE_DIFF * 500
        result = truncate_diff(big_diff, max_chars=500)
        # The notice is about 100 chars; total should not balloon
        assert len(result) < 700
