"""Unit tests for zonny_core.utils.file_utils."""
from __future__ import annotations

from pathlib import Path

import pytest

from zonny_core.utils.file_utils import find_files, matches_any, read_file_safe


class TestMatchesAny:
    def test_matches_exact_filename(self) -> None:
        assert matches_any(Path("node_modules"), ["node_modules"])

    def test_matches_glob_star(self) -> None:
        assert matches_any(Path("dist/app.min.js"), ["*.min.js"])

    def test_matches_parent_dir(self) -> None:
        assert matches_any(Path("node_modules/lodash/index.js"), ["node_modules"])

    def test_matches_pycache(self) -> None:
        assert matches_any(Path("src/__pycache__/foo.pyc"), ["__pycache__"])

    def test_no_match_returns_false(self) -> None:
        assert not matches_any(Path("src/main.py"), ["node_modules", "__pycache__"])

    def test_empty_patterns_never_match(self) -> None:
        assert not matches_any(Path("anything/file.py"), [])

    def test_matches_nested_ignore_dir(self) -> None:
        assert matches_any(Path("packages/ui/node_modules/react"), ["node_modules"])

    def test_glob_extension_pattern(self) -> None:
        assert matches_any(Path("bundle.min.css"), ["*.min.css"])

    def test_no_false_positive_on_similar_name(self) -> None:
        # "build" should not match "rebuilding.py"
        assert not matches_any(Path("src/rebuilding.py"), ["build"])


class TestFindFiles:
    def test_finds_python_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x=1")
        (tmp_path / "b.js").write_text("const x=1;")
        result = find_files(tmp_path, [".py"], [])
        assert len(result) == 1
        assert result[0].name == "a.py"

    def test_finds_multiple_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.ts").write_text("x")
        (tmp_path / "c.md").write_text("x")
        result = find_files(tmp_path, [".py", ".ts"], [])
        names = {f.name for f in result}
        assert names == {"a.py", "b.ts"}

    def test_respects_ignore_patterns(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "bundle.py").write_text("x")
        (tmp_path / "main.py").write_text("x")
        result = find_files(tmp_path, [".py"], ["dist"])
        assert all(f.name != "bundle.py" for f in result)
        assert any(f.name == "main.py" for f in result)

    def test_respects_max_file_size(self, tmp_path: Path) -> None:
        small = tmp_path / "small.py"
        small.write_text("x = 1")
        big = tmp_path / "big.py"
        big.write_bytes(b"x" * 600 * 1024)  # 600 KB
        result = find_files(tmp_path, [".py"], [], max_file_size_kb=500)
        names = {f.name for f in result}
        assert "small.py" in names
        assert "big.py" not in names

    def test_respects_max_depth(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (tmp_path / "root.py").write_text("x")
        (tmp_path / "a" / "level1.py").write_text("x")
        (deep / "level3.py").write_text("x")
        result = find_files(tmp_path, [".py"], [], max_depth=1)
        names = {f.name for f in result}
        assert "root.py" in names
        assert "level1.py" in names
        assert "level3.py" not in names

    def test_returns_empty_when_no_match(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text("[x]")
        result = find_files(tmp_path, [".py"], [])
        assert result == []

    def test_returns_sorted_results(self, tmp_path: Path) -> None:
        (tmp_path / "c.py").write_text("x")
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("x")
        result = find_files(tmp_path, [".py"], [])
        names = [f.name for f in result]
        assert names == sorted(names)

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        assert find_files(tmp_path, [".py"], []) == []

    def test_skips_pycache(self, tmp_path: Path) -> None:
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "mod.cpython-313.pyc").write_text("bytecode")
        (tmp_path / "mod.py").write_text("x = 1")
        result = find_files(tmp_path, [".py", ".pyc"], ["__pycache__"])
        assert all("__pycache__" not in str(f) for f in result)


class TestReadFileSafe:
    def test_reads_utf8_file(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read_file_safe(f) == "hello world"

    def test_replaces_invalid_bytes(self, tmp_path: Path) -> None:
        f = tmp_path / "binary.py"
        f.write_bytes(b"hello \xff world")
        content = read_file_safe(f)
        assert "hello" in content
        assert "world" in content
        # No UnicodeDecodeError raised

    def test_reads_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        assert read_file_safe(f) == ""
