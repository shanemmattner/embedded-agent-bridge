"""
Tests for FileSystemInterface implementations.

Tests for file_size, rename_file, and list_dir methods across
RealFileSystem and MockFileSystem implementations.
"""

import pytest

from eab.implementations import RealFileSystem
from eab.mocks import MockFileSystem


class TestFileSize:
    """Tests for file_size method."""

    def test_mock_file_size_basic(self):
        """MockFileSystem should return byte size of file content."""
        fs = MockFileSystem()
        fs.write_file("/test.txt", "hello")

        size = fs.file_size("/test.txt")
        assert size == 5  # "hello" is 5 bytes

    def test_mock_file_size_empty(self):
        """MockFileSystem should return 0 for empty file."""
        fs = MockFileSystem()
        fs.write_file("/empty.txt", "")

        size = fs.file_size("/empty.txt")
        assert size == 0

    def test_mock_file_size_unicode(self):
        """MockFileSystem should count UTF-8 bytes correctly."""
        fs = MockFileSystem()
        # UTF-8 encoding: € is 3 bytes, ñ is 2 bytes
        fs.write_file("/unicode.txt", "€ñ")

        size = fs.file_size("/unicode.txt")
        # € (3 bytes) + ñ (2 bytes) = 5 bytes
        assert size == 5

    def test_mock_file_size_multiline(self):
        """MockFileSystem should count bytes in multiline content."""
        fs = MockFileSystem()
        content = "line1\nline2\nline3"
        fs.write_file("/multi.txt", content)

        size = fs.file_size("/multi.txt")
        assert size == len(content.encode('utf-8'))

    def test_mock_file_size_not_found(self):
        """MockFileSystem should raise FileNotFoundError for missing file."""
        fs = MockFileSystem()

        with pytest.raises(FileNotFoundError) as exc_info:
            fs.file_size("/nonexistent.txt")

        assert "No such file" in str(exc_info.value)

    def test_real_file_size_basic(self, tmp_path):
        """RealFileSystem should return actual file size."""
        fs = RealFileSystem()
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        size = fs.file_size(str(test_file))
        assert size == 11  # "hello world" is 11 bytes

    def test_real_file_size_empty(self, tmp_path):
        """RealFileSystem should return 0 for empty file."""
        fs = RealFileSystem()
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        size = fs.file_size(str(test_file))
        assert size == 0

    def test_real_file_size_binary(self, tmp_path):
        """RealFileSystem should handle binary files."""
        fs = RealFileSystem()
        test_file = tmp_path / "binary.dat"
        test_file.write_bytes(b"\x00\x01\x02\x03\x04")

        size = fs.file_size(str(test_file))
        assert size == 5

    def test_real_file_size_not_found(self, tmp_path):
        """RealFileSystem should raise FileNotFoundError for missing file."""
        fs = RealFileSystem()

        with pytest.raises(FileNotFoundError):
            fs.file_size(str(tmp_path / "nonexistent.txt"))

    def test_real_file_size_large(self, tmp_path):
        """RealFileSystem should handle large files."""
        fs = RealFileSystem()
        test_file = tmp_path / "large.txt"
        # Write 10KB of data
        test_file.write_text("x" * 10240)

        size = fs.file_size(str(test_file))
        assert size == 10240


class TestRenameFile:
    """Tests for rename_file method."""

    def test_mock_rename_file_basic(self):
        """MockFileSystem should rename file successfully."""
        fs = MockFileSystem()
        fs.write_file("/old.txt", "content")

        fs.rename_file("/old.txt", "/new.txt")

        assert not fs.file_exists("/old.txt")
        assert fs.file_exists("/new.txt")
        assert fs.read_file("/new.txt") == "content"

    def test_mock_rename_file_preserves_content(self):
        """MockFileSystem should preserve file content after rename."""
        fs = MockFileSystem()
        content = "important data\nline 2\nline 3"
        fs.write_file("/source.txt", content)

        fs.rename_file("/source.txt", "/destination.txt")

        assert fs.read_file("/destination.txt") == content

    def test_mock_rename_file_preserves_mtime(self):
        """MockFileSystem should preserve modification time after rename."""
        fs = MockFileSystem()
        fs.write_file("/file.txt", "data")
        original_mtime = fs.get_mtime("/file.txt")

        fs.rename_file("/file.txt", "/renamed.txt")

        new_mtime = fs.get_mtime("/renamed.txt")
        assert new_mtime == original_mtime

    def test_mock_rename_file_not_found(self):
        """MockFileSystem should raise FileNotFoundError for missing source."""
        fs = MockFileSystem()

        with pytest.raises(FileNotFoundError) as exc_info:
            fs.rename_file("/nonexistent.txt", "/new.txt")

        assert "No such file" in str(exc_info.value)

    def test_mock_rename_file_overwrites_destination(self):
        """MockFileSystem should overwrite destination if it exists."""
        fs = MockFileSystem()
        fs.write_file("/src.txt", "source content")
        fs.write_file("/dst.txt", "destination content")

        fs.rename_file("/src.txt", "/dst.txt")

        assert not fs.file_exists("/src.txt")
        assert fs.file_exists("/dst.txt")
        assert fs.read_file("/dst.txt") == "source content"

    def test_real_rename_file_basic(self, tmp_path):
        """RealFileSystem should rename file successfully."""
        fs = RealFileSystem()
        old_file = tmp_path / "old.txt"
        new_file = tmp_path / "new.txt"
        old_file.write_text("test content")

        fs.rename_file(str(old_file), str(new_file))

        assert not old_file.exists()
        assert new_file.exists()
        assert new_file.read_text() == "test content"

    def test_real_rename_file_preserves_content(self, tmp_path):
        """RealFileSystem should preserve file content after rename."""
        fs = RealFileSystem()
        src = tmp_path / "source.dat"
        dst = tmp_path / "destination.dat"
        content = b"\x00\x01\x02\xFF\xFE\xFD"
        src.write_bytes(content)

        fs.rename_file(str(src), str(dst))

        assert dst.read_bytes() == content

    def test_real_rename_file_move_to_subdirectory(self, tmp_path):
        """RealFileSystem should move file to subdirectory."""
        fs = RealFileSystem()
        src = tmp_path / "file.txt"
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        dst = subdir / "file.txt"
        src.write_text("content")

        fs.rename_file(str(src), str(dst))

        assert not src.exists()
        assert dst.exists()
        assert dst.read_text() == "content"

    def test_real_rename_file_not_found(self, tmp_path):
        """RealFileSystem should raise FileNotFoundError for missing source."""
        fs = RealFileSystem()

        with pytest.raises(FileNotFoundError):
            fs.rename_file(
                str(tmp_path / "nonexistent.txt"),
                str(tmp_path / "new.txt")
            )


class TestListDir:
    """Tests for list_dir method."""

    def test_mock_list_dir_empty(self):
        """MockFileSystem should return empty list for directory with no files."""
        fs = MockFileSystem()

        files = fs.list_dir("/empty")

        assert files == []

    def test_mock_list_dir_single_file(self):
        """MockFileSystem should list single file in directory."""
        fs = MockFileSystem()
        fs.write_file("/dir/file.txt", "content")

        files = fs.list_dir("/dir")

        assert files == ["file.txt"]

    def test_mock_list_dir_multiple_files(self):
        """MockFileSystem should list all files in directory."""
        fs = MockFileSystem()
        fs.write_file("/data/file1.txt", "a")
        fs.write_file("/data/file2.txt", "b")
        fs.write_file("/data/file3.txt", "c")

        files = fs.list_dir("/data")

        assert sorted(files) == ["file1.txt", "file2.txt", "file3.txt"]

    def test_mock_list_dir_excludes_subdirectories(self):
        """MockFileSystem should not include files from subdirectories."""
        fs = MockFileSystem()
        fs.write_file("/root/file.txt", "root file")
        fs.write_file("/root/subdir/nested.txt", "nested file")
        fs.write_file("/root/another.txt", "another root file")

        files = fs.list_dir("/root")

        # Should only include direct children, not nested files
        assert sorted(files) == ["another.txt", "file.txt"]

    def test_mock_list_dir_with_trailing_slash(self):
        """MockFileSystem should handle directory path with trailing slash."""
        fs = MockFileSystem()
        fs.write_file("/dir/file1.txt", "a")
        fs.write_file("/dir/file2.txt", "b")

        files = fs.list_dir("/dir/")

        assert sorted(files) == ["file1.txt", "file2.txt"]

    def test_mock_list_dir_sorted(self):
        """MockFileSystem should return sorted list of filenames."""
        fs = MockFileSystem()
        fs.write_file("/data/zebra.txt", "z")
        fs.write_file("/data/apple.txt", "a")
        fs.write_file("/data/banana.txt", "b")

        files = fs.list_dir("/data")

        assert files == ["apple.txt", "banana.txt", "zebra.txt"]

    def test_mock_list_dir_different_directories(self):
        """MockFileSystem should distinguish between different directories."""
        fs = MockFileSystem()
        fs.write_file("/dir1/file1.txt", "a")
        fs.write_file("/dir2/file2.txt", "b")

        files1 = fs.list_dir("/dir1")
        files2 = fs.list_dir("/dir2")

        assert files1 == ["file1.txt"]
        assert files2 == ["file2.txt"]

    def test_mock_list_dir_root_directory(self):
        """MockFileSystem should list files in root directory."""
        fs = MockFileSystem()
        fs.write_file("/file1.txt", "a")
        fs.write_file("/file2.txt", "b")
        fs.write_file("/subdir/nested.txt", "c")

        files = fs.list_dir("/")

        assert sorted(files) == ["file1.txt", "file2.txt"]

    def test_real_list_dir_empty(self, tmp_path):
        """RealFileSystem should return empty list for empty directory."""
        fs = RealFileSystem()
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        files = fs.list_dir(str(empty_dir))

        assert files == []

    def test_real_list_dir_multiple_files(self, tmp_path):
        """RealFileSystem should list all files in directory."""
        fs = RealFileSystem()
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("a")
        (test_dir / "file2.txt").write_text("b")
        (test_dir / "file3.txt").write_text("c")

        files = fs.list_dir(str(test_dir))

        assert sorted(files) == ["file1.txt", "file2.txt", "file3.txt"]

    def test_real_list_dir_includes_subdirectories(self, tmp_path):
        """RealFileSystem should include subdirectories in listing."""
        fs = RealFileSystem()
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")
        (test_dir / "subdir").mkdir()

        files = fs.list_dir(str(test_dir))

        assert sorted(files) == ["file.txt", "subdir"]

    def test_real_list_dir_not_found(self, tmp_path):
        """RealFileSystem should raise FileNotFoundError for missing directory."""
        fs = RealFileSystem()

        with pytest.raises(FileNotFoundError):
            fs.list_dir(str(tmp_path / "nonexistent"))

    def test_real_list_dir_mixed_content(self, tmp_path):
        """RealFileSystem should list both files and directories."""
        fs = RealFileSystem()
        test_dir = tmp_path / "mixed"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("a")
        (test_dir / "dir1").mkdir()
        (test_dir / "file2.dat").write_bytes(b"\x00\x01")
        (test_dir / "dir2").mkdir()

        files = fs.list_dir(str(test_dir))

        assert sorted(files) == ["dir1", "dir2", "file1.txt", "file2.dat"]


class TestCrossImplementationConsistency:
    """Tests to verify MockFileSystem behaves like RealFileSystem."""

    def test_file_size_consistency(self, tmp_path):
        """Both implementations should report same size for same content."""
        mock_fs = MockFileSystem()
        real_fs = RealFileSystem()

        content = "Test content with special chars: €ñ\n"

        # Mock
        mock_fs.write_file("/test.txt", content)
        mock_size = mock_fs.file_size("/test.txt")

        # Real
        real_file = tmp_path / "test.txt"
        real_file.write_text(content)
        real_size = real_fs.file_size(str(real_file))

        assert mock_size == real_size

    def test_rename_preserves_content_both(self, tmp_path):
        """Both implementations should preserve content after rename."""
        mock_fs = MockFileSystem()
        real_fs = RealFileSystem()

        content = "Critical data"

        # Mock
        mock_fs.write_file("/old.txt", content)
        mock_fs.rename_file("/old.txt", "/new.txt")
        mock_content = mock_fs.read_file("/new.txt")

        # Real
        old_file = tmp_path / "old.txt"
        new_file = tmp_path / "new.txt"
        old_file.write_text(content)
        real_fs.rename_file(str(old_file), str(new_file))
        real_content = new_file.read_text()

        assert mock_content == real_content == content

    def test_list_dir_consistency(self, tmp_path):
        """Both implementations should list files consistently."""
        mock_fs = MockFileSystem()
        real_fs = RealFileSystem()

        # Mock
        mock_fs.write_file("/dir/a.txt", "a")
        mock_fs.write_file("/dir/b.txt", "b")
        mock_fs.write_file("/dir/c.txt", "c")
        mock_files = mock_fs.list_dir("/dir")

        # Real
        real_dir = tmp_path / "dir"
        real_dir.mkdir()
        (real_dir / "a.txt").write_text("a")
        (real_dir / "b.txt").write_text("b")
        (real_dir / "c.txt").write_text("c")
        real_files = real_fs.list_dir(str(real_dir))

        assert sorted(mock_files) == sorted(real_files)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_file_size_after_append(self):
        """File size should update after appending content."""
        fs = MockFileSystem()
        fs.write_file("/log.txt", "line1\n")
        initial_size = fs.file_size("/log.txt")

        fs.write_file("/log.txt", "line2\n", append=True)
        final_size = fs.file_size("/log.txt")

        assert final_size > initial_size
        assert final_size == len("line1\nline2\n".encode('utf-8'))

    def test_rename_to_same_name(self):
        """Renaming file to itself should work."""
        fs = MockFileSystem()
        fs.write_file("/file.txt", "content")

        fs.rename_file("/file.txt", "/file.txt")

        assert fs.file_exists("/file.txt")
        assert fs.read_file("/file.txt") == "content"

    def test_list_dir_after_rename(self):
        """Directory listing should reflect renamed files."""
        fs = MockFileSystem()
        fs.write_file("/dir/old.txt", "content")

        initial_files = fs.list_dir("/dir")
        fs.rename_file("/dir/old.txt", "/dir/new.txt")
        final_files = fs.list_dir("/dir")

        assert initial_files == ["old.txt"]
        assert final_files == ["new.txt"]

    def test_list_dir_after_delete(self):
        """Directory listing should reflect deleted files."""
        fs = MockFileSystem()
        fs.write_file("/dir/file1.txt", "a")
        fs.write_file("/dir/file2.txt", "b")
        fs.write_file("/dir/file3.txt", "c")

        fs.delete_file("/dir/file2.txt")
        files = fs.list_dir("/dir")

        assert sorted(files) == ["file1.txt", "file3.txt"]

    def test_file_size_very_large_content(self):
        """File size should handle very large content."""
        fs = MockFileSystem()
        # 1MB of data
        large_content = "x" * (1024 * 1024)
        fs.write_file("/large.txt", large_content)

        size = fs.file_size("/large.txt")

        assert size == 1024 * 1024

    def test_list_dir_special_characters(self):
        """List dir should handle filenames with special characters."""
        fs = MockFileSystem()
        fs.write_file("/dir/file-with-dash.txt", "a")
        fs.write_file("/dir/file_with_underscore.txt", "b")
        fs.write_file("/dir/file.multiple.dots.txt", "c")

        files = fs.list_dir("/dir")

        assert sorted(files) == [
            "file-with-dash.txt",
            "file.multiple.dots.txt",
            "file_with_underscore.txt"
        ]

    def test_rename_across_deep_paths(self):
        """Rename should work with deeply nested paths."""
        fs = MockFileSystem()
        fs.write_file("/a/b/c/d/e/file.txt", "deep content")

        fs.rename_file("/a/b/c/d/e/file.txt", "/x/y/z/file.txt")

        assert not fs.file_exists("/a/b/c/d/e/file.txt")
        assert fs.file_exists("/x/y/z/file.txt")
        assert fs.read_file("/x/y/z/file.txt") == "deep content"
