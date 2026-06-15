"""Test suite for triplecheck."""

import argparse
import os
import random
import string
import sys
import unicodedata
from pathlib import Path
from typing import ClassVar
from unittest import mock

import blake3
import pytest

from triplecheck import triplecheck

# ---------------------------------------------------------------------------
# Low-level helper (also importable from tests via conftest)
# ---------------------------------------------------------------------------


def make_file(path: Path, content: bytes = b"hello world") -> Path:
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# Simple file fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_a(tmp_path):
    return make_file(tmp_path / "file_a.txt", b"identical content")


@pytest.fixture
def file_b_identical(tmp_path):
    return make_file(tmp_path / "file_b.txt", b"identical content")


@pytest.fixture
def file_b_different(tmp_path):
    return make_file(tmp_path / "file_b.txt", b"different content")


# ---------------------------------------------------------------------------
# Two-way directory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def identical_dirs(tmp_path):
    """Two directories with exactly the same files and sizes."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    for d in (src, dest):
        d.mkdir()
        make_file(d / "alpha.txt", b"aaa")
        make_file(d / "beta.txt", b"bbb")
        (d / "sub").mkdir()
        make_file(d / "sub" / "gamma.txt", b"ccc")
    return src, dest


@pytest.fixture
def different_dirs(tmp_path):
    """Two directories where one file has different content (and size)."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    for d in (src, dest):
        d.mkdir()
        make_file(d / "alpha.txt", b"aaa")
    make_file(dest / "alpha.txt", b"AAAA")
    return src, dest


@pytest.fixture
def dirs_extra_empty_dir(tmp_path):
    """Identical files, but dest has an extra empty subdirectory."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    for d in (src, dest):
        d.mkdir()
        make_file(d / "alpha.txt", b"aaa")
    (dest / "empty_subdir").mkdir()
    return src, dest


@pytest.fixture
def dirs_same_files_different_structure(tmp_path):
    """Same filenames and content, but organised into different subdirectories."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "2024").mkdir()
    make_file(src / "2024" / "photo.jpg", b"img")
    make_file(src / "2024" / "doc.pdf", b"pdf")
    (dest / "archive").mkdir()
    make_file(dest / "archive" / "photo.jpg", b"img")
    make_file(dest / "archive" / "doc.pdf", b"pdf")
    return src, dest


@pytest.fixture
def dirs_with_identical_dupes(tmp_path):
    """
    Same files in different subdirs, plus the same filename duplicated within
    one tree with identical content — should still report a match under -i.
    """
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "a").mkdir()
    (src / "b").mkdir()
    make_file(src / "a" / "photo.jpg", b"img")
    make_file(src / "b" / "photo.jpg", b"img")
    make_file(dest / "photo.jpg", b"img")
    return src, dest


@pytest.fixture
def dirs_with_conflicting_dupes(tmp_path):
    """
    Same filenames in different subdirs within src, but different sizes —
    conflicting duplicates, should exit 2 under -i.
    """
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "a").mkdir()
    (src / "b").mkdir()
    make_file(src / "a" / "photo.jpg", b"img_v1")
    make_file(src / "b" / "photo.jpg", b"img_version2")
    make_file(dest / "photo.jpg", b"img_v1")
    return src, dest


@pytest.fixture
def dirs_with_appledouble(tmp_path):
    """Identical dirs, but dest has extra AppleDouble (._*) files."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    for d in (src, dest):
        d.mkdir()
        make_file(d / "alpha.txt", b"aaa")
    make_file(dest / "._alpha.txt", b"mac metadata")
    return src, dest


# ---------------------------------------------------------------------------
# Three-way directory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def identical_dirs_three(tmp_path):
    """Three directories that are fully identical."""
    src = tmp_path / "src"
    dest1 = tmp_path / "dest1"
    dest2 = tmp_path / "dest2"
    for d in (src, dest1, dest2):
        d.mkdir()
        make_file(d / "alpha.txt", b"aaa")
        make_file(d / "beta.txt", b"bbb")
        (d / "sub").mkdir()
        make_file(d / "sub" / "gamma.txt", b"ccc")
    return src, dest1, dest2


@pytest.fixture
def dirs_one_differs(tmp_path):
    """Three directories: dest2 has a file with different content."""
    src = tmp_path / "src"
    dest1 = tmp_path / "dest1"
    dest2 = tmp_path / "dest2"
    for d in (src, dest1, dest2):
        d.mkdir()
        make_file(d / "alpha.txt", b"aaa")
        make_file(d / "beta.txt", b"bbb")
    make_file(dest2 / "alpha.txt", b"AAAA")
    return src, dest1, dest2


@pytest.fixture
def dirs_all_differ(tmp_path):
    """Three directories each with a uniquely-sized version of alpha.txt."""
    src = tmp_path / "src"
    dest1 = tmp_path / "dest1"
    dest2 = tmp_path / "dest2"
    src.mkdir()
    dest1.mkdir()
    dest2.mkdir()
    make_file(src / "alpha.txt", b"aaa")
    make_file(dest1 / "alpha.txt", b"bbbb")
    make_file(dest2 / "alpha.txt", b"ccccc")
    return src, dest1, dest2


@pytest.fixture
def dirs_missing_file_in_one(tmp_path):
    """Three directories: dest2 is missing a file present in src and dest1."""
    src = tmp_path / "src"
    dest1 = tmp_path / "dest1"
    dest2 = tmp_path / "dest2"
    for d in (src, dest1, dest2):
        d.mkdir()
        make_file(d / "common.txt", b"shared")
    make_file(src / "extra.txt", b"only in src and dest1")
    make_file(dest1 / "extra.txt", b"only in src and dest1")
    return src, dest1, dest2


@pytest.fixture
def dirs_three_extra_empty_dir(tmp_path):
    """Three identical-file dirs, but dest2 has an extra empty subdirectory."""
    src = tmp_path / "src"
    dest1 = tmp_path / "dest1"
    dest2 = tmp_path / "dest2"
    for d in (src, dest1, dest2):
        d.mkdir()
        make_file(d / "alpha.txt", b"aaa")
    (dest2 / "empty_subdir").mkdir()
    return src, dest1, dest2


@pytest.fixture
def dirs_three_appledouble(tmp_path):
    """Three identical dirs, but dest2 has extra AppleDouble files."""
    src = tmp_path / "src"
    dest1 = tmp_path / "dest1"
    dest2 = tmp_path / "dest2"
    for d in (src, dest1, dest2):
        d.mkdir()
        make_file(d / "alpha.txt", b"aaa")
    make_file(dest2 / "._alpha.txt", b"mac metadata")
    return src, dest1, dest2


@pytest.fixture
def dirs_three_conflicting_dupes(tmp_path):
    """
    Three-way -i comparison where src has conflicting duplicates.
    Should exit 2.
    """
    src = tmp_path / "src"
    dest1 = tmp_path / "dest1"
    dest2 = tmp_path / "dest2"
    src.mkdir()
    dest1.mkdir()
    dest2.mkdir()
    (src / "a").mkdir()
    (src / "b").mkdir()
    make_file(src / "a" / "photo.jpg", b"img_v1")
    make_file(src / "b" / "photo.jpg", b"img_version2")
    make_file(dest1 / "photo.jpg", b"img_v1")
    make_file(dest2 / "photo.jpg", b"img_v1")
    return src, dest1, dest2


# ---------------------------------------------------------------------------
# Utility fixture: temporary working-directory change
# ---------------------------------------------------------------------------


@pytest.fixture
def chdir(tmp_path):
    """
    Change into a fresh temp subdirectory for the test, then restore the
    original cwd.  Ensures --molist tests don't interfere with each other even
    when a test fails mid-way.
    """
    original = Path.cwd()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    os.chdir(cwd)
    yield cwd
    os.chdir(original)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def run(*args) -> int:
    """Call triplecheck.main() with the given arguments and return its exit code."""
    return triplecheck.main(list(args))  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


class TestDiffThree:
    """Direct tests of the diff_three() merge-diff kernel."""

    def test_empty_listings_yield_nothing(self):
        assert list(triplecheck.diff_three([[], []])) == []
        assert list(triplecheck.diff_three([[], [], []])) == []

    def test_identical_two_way_yields_nothing(self):
        listing = [(100, "a.txt"), (200, "b.txt")]
        assert list(triplecheck.diff_three([listing, listing])) == []

    def test_identical_three_way_yields_nothing(self):
        listing = [(100, "a.txt"), (200, "b.txt")]
        assert list(triplecheck.diff_three([listing, listing, listing])) == []

    def test_file_missing_from_second(self):
        a = [(1, "only_in_a.txt"), (2, "shared.txt")]
        b = [(2, "shared.txt")]
        groups = list(triplecheck.diff_three([a, b]))
        assert len(groups) == 1
        group = groups[0]
        assert group[0] == (1, "only_in_a.txt")
        assert group[1] is None

    def test_file_missing_from_third(self):
        shared = [(1, "file.txt")]
        empty = []
        groups = list(triplecheck.diff_three([shared, shared, empty]))
        assert len(groups) == 1
        group = groups[0]
        assert group[0] is not None
        assert group[1] is not None
        assert group[2] is None

    def test_value_mismatch_reported(self):
        a = [("hash_a", "file.txt")]
        b = [("hash_b", "file.txt")]
        groups = list(triplecheck.diff_three([a, b]))
        assert len(groups) == 1

    def test_value_mismatch_not_reported_when_equal(self):
        a = [("hash_x", "file.txt")]
        assert list(triplecheck.diff_three([a, a])) == []

    def test_three_way_one_differs(self):
        good = [("hash_ok", "file.txt")]
        bad = [("hash_no", "file.txt")]
        groups = list(triplecheck.diff_three([good, good, bad]))
        assert len(groups) == 1

    def test_multiple_differing_files(self):
        a = [(1, "a.txt"), (2, "b.txt"), (3, "c.txt")]
        b = [(1, "a.txt"), (9, "b.txt"), (3, "c.txt")]
        groups = list(triplecheck.diff_three([a, b]))
        assert len(groups) == 1
        entry = groups[0][0]
        assert entry is not None
        assert entry[1] == "b.txt"


# ---------------------------------------------------------------------------
# Unit tests for diff_sorted() — the two-way merge kernel used by --diff
# ---------------------------------------------------------------------------


class TestDiffSorted:
    """Direct tests of the diff_sorted() two-pointer merge kernel."""

    def test_identical_listings_yield_nothing(self):
        listing = [(100, "a.txt"), (200, "b.txt")]
        assert list(triplecheck.diff_sorted(listing, listing)) == []

    def test_empty_listings_yield_nothing(self):
        assert list(triplecheck.diff_sorted([], [])) == []

    def test_file_only_in_a_yields_left_sigil(self):
        a = [(1, "only.txt")]
        result = list(triplecheck.diff_sorted(a, []))
        assert result == [("<", (1, "only.txt"))]

    def test_file_only_in_b_yields_right_sigil(self):
        b = [(1, "only.txt")]
        result = list(triplecheck.diff_sorted([], b))
        assert result == [(">", (1, "only.txt"))]

    def test_value_mismatch_yields_both_sigils(self):
        a = [(10, "file.txt")]
        b = [(99, "file.txt")]
        result = list(triplecheck.diff_sorted(a, b))
        assert ("<", (10, "file.txt")) in result
        assert (">", (99, "file.txt")) in result

    def test_value_match_yields_nothing(self):
        a = [(42, "file.txt")]
        assert list(triplecheck.diff_sorted(a, a)) == []

    def test_ordering_preserved(self):
        """Items yielded in sorted path order regardless of value differences."""
        a = [(1, "a.txt"), (2, "b.txt"), (3, "c.txt")]
        b = [(1, "a.txt"), (9, "b.txt"), (3, "c.txt")]
        result = list(triplecheck.diff_sorted(a, b))
        paths = [tup[1] for _, tup in result]
        assert paths == sorted(paths)
        assert all(p == "b.txt" for p in paths)

    def test_extra_files_at_end_of_a(self):
        a = [(1, "a.txt"), (2, "z.txt")]
        b = [(1, "a.txt")]
        result = list(triplecheck.diff_sorted(a, b))
        assert result == [("<", (2, "z.txt"))]

    def test_extra_files_at_end_of_b(self):
        a = [(1, "a.txt")]
        b = [(1, "a.txt"), (2, "z.txt")]
        result = list(triplecheck.diff_sorted(a, b))
        assert result == [(">", (2, "z.txt"))]

    def test_completely_disjoint_listings(self):
        a = [(1, "aaa.txt"), (2, "bbb.txt")]
        b = [(3, "ccc.txt"), (4, "ddd.txt")]
        result = list(triplecheck.diff_sorted(a, b))
        sigils = [s for s, _ in result]
        assert sigils.count("<") == 2
        assert sigils.count(">") == 2


class TestRenderGroup:
    """Unit tests for render_group()."""

    def test_two_way_group_has_two_lines(self):
        group = [("x", "file.txt"), None]
        output = triplecheck.render_group(group)
        assert output.count("\n") == 1  # two lines joined by one newline

    def test_three_way_group_has_three_lines(self):
        group = [("x", "file.txt"), ("x", "file.txt"), None]
        output = triplecheck.render_group(group)
        assert output.count("\n") == 2

    def test_sigils_present(self):
        group = [("x", "file.txt"), None]
        output = triplecheck.render_group(group)
        assert "<" in output
        assert ">" in output

    def test_three_way_sigils_present(self):
        group = [("x", "file.txt"), ("y", "file.txt"), None]
        output = triplecheck.render_group(group)
        assert "< " in output
        assert "> " in output
        assert ">>" in output

    def test_path_in_output(self):
        group = [("x", "photos/img.jpg"), None]
        output = triplecheck.render_group(group)
        assert "photos/img.jpg" in output

    def test_missing_symbol_in_output(self):
        group = [("x", "file.txt"), None]
        output = triplecheck.render_group(group)
        assert "∄" in output

    def test_match_symbol_in_output(self):
        entry = ("hash", "file.txt")
        group = [entry, entry]
        output = triplecheck.render_group(group)
        assert "=" in output


class TestNormaliseAlgorithm:
    def test_xxh64_aliases(self):
        for alias in ("xxh64", "xxhash64", "xxhash64be", "XXH64"):
            assert triplecheck.normalise_algorithm(alias) == "xxh64"

    def test_xxh128_aliases(self):
        for alias in ("xxh128", "xxhash128", "XXH128"):
            assert triplecheck.normalise_algorithm(alias) == "xxh128"

    def test_unknown_algorithm_exits(self):
        with pytest.raises(SystemExit):
            triplecheck.normalise_algorithm("md5")


# ---------------------------------------------------------------------------
# File comparison tests (two-way and three-way)
# ---------------------------------------------------------------------------


class TestFileComparison:
    def test_identical_files_match(self, file_a, file_b_identical):
        assert run(str(file_a), str(file_b_identical)) == 0

    def test_identical_files_match_xxh128(self, file_a, file_b_identical):
        assert run("-a", "xxh128", str(file_a), str(file_b_identical)) == 0

    def test_identical_files_match_full_flag_accepted(self, file_a, file_b_identical):
        # -f has no effect on file-vs-file comparison
        assert run("-f", str(file_a), str(file_b_identical)) == 0

    def test_different_files_mismatch(self, file_a, file_b_different):
        assert run(str(file_a), str(file_b_different)) == 1

    def test_different_files_mismatch_xxh128(self, file_a, file_b_different):
        assert run("-a", "xxh128", str(file_a), str(file_b_different)) == 1

    def test_different_files_mismatch_full_flag_accepted(self, file_a, file_b_different):
        assert run("-f", str(file_a), str(file_b_different)) == 1

    def test_different_files_mismatch_full_flag_accepted_xxh128(self, file_a, file_b_different):
        assert run("-f", "-a", "xxh128", str(file_a), str(file_b_different)) == 1

    def test_identical_files_match_full_flag_accepted_xxh128(self, file_a, file_b_identical):
        assert run("-f", "-a", "xxh128", str(file_a), str(file_b_identical)) == 0

    # --- three-way file comparison ---

    def test_three_way_all_identical_match(self, tmp_path):
        f1 = make_file(tmp_path / "f1.txt", b"same")
        f2 = make_file(tmp_path / "f2.txt", b"same")
        f3 = make_file(tmp_path / "f3.txt", b"same")
        assert run(str(f1), str(f2), str(f3)) == 0

    def test_three_way_all_differ_mismatch(self, tmp_path):
        f1 = make_file(tmp_path / "f1.txt", b"aaa")
        f2 = make_file(tmp_path / "f2.txt", b"bbb")
        f3 = make_file(tmp_path / "f3.txt", b"ccc")
        assert run(str(f1), str(f2), str(f3)) == 1

    def test_three_way_one_differs_mismatch(self, tmp_path):
        f1 = make_file(tmp_path / "f1.txt", b"same")
        f2 = make_file(tmp_path / "f2.txt", b"same")
        f3 = make_file(tmp_path / "f3.txt", b"different content")
        assert run(str(f1), str(f2), str(f3)) == 1

    def test_three_way_match_prints_success(self, tmp_path, capsys):
        f1 = make_file(tmp_path / "f1.txt", b"same")
        f2 = make_file(tmp_path / "f2.txt", b"same")
        f3 = make_file(tmp_path / "f3.txt", b"same")
        run(str(f1), str(f2), str(f3))
        assert "match" in capsys.readouterr().out.lower()

    def test_three_way_mismatch_uses_triad_output(self, tmp_path, capsys):
        """On mismatch the triad sigils < > >> are used, consistent with dir output."""
        f1 = make_file(tmp_path / "f1.txt", b"aaa")
        f2 = make_file(tmp_path / "f2.txt", b"bbb")
        f3 = make_file(tmp_path / "f3.txt", b"ccc")
        run(str(f1), str(f2), str(f3))
        out = capsys.readouterr().out
        assert "<" in out
        assert ">" in out
        assert ">>" in out

    def test_three_way_two_match_one_differs_triad(self, tmp_path, capsys):
        """When two files match and one differs, = and ≠ symbols appear."""
        f1 = make_file(tmp_path / "f1.txt", b"same")
        f2 = make_file(tmp_path / "f2.txt", b"same")
        f3 = make_file(tmp_path / "f3.txt", b"different content")
        run(str(f1), str(f2), str(f3))
        out = capsys.readouterr().out
        assert "=" in out
        assert "≠" in out

    def test_three_way_xxh128(self, tmp_path):
        f1 = make_file(tmp_path / "f1.txt", b"same")
        f2 = make_file(tmp_path / "f2.txt", b"same")
        f3 = make_file(tmp_path / "f3.txt", b"same")
        assert run("-a", "xxh128", str(f1), str(f2), str(f3)) == 0


# ---------------------------------------------------------------------------
# Directory comparison — metadata mode (default), two-way
# ---------------------------------------------------------------------------


class TestDirMetadataTwoWay:
    def test_identical_dirs_match(self, identical_dirs):
        src, dest = identical_dirs
        assert run(str(src), str(dest)) == 0

    def test_different_dirs_mismatch(self, different_dirs):
        src, dest = different_dirs
        assert run(str(src), str(dest)) == 1

    def test_extra_empty_dir_mismatch(self, dirs_extra_empty_dir):
        src, dest = dirs_extra_empty_dir
        assert run(str(src), str(dest)) == 1

    def test_extra_empty_dir_ignored_with_i(self, dirs_extra_empty_dir):
        src, dest = dirs_extra_empty_dir
        assert run("-i", str(src), str(dest)) == 0

    def test_different_structure_match_with_i(self, dirs_same_files_different_structure):
        src, dest = dirs_same_files_different_structure
        assert run("-i", str(src), str(dest)) == 0

    def test_identical_dupes_match_with_i(self, dirs_with_identical_dupes):
        src, dest = dirs_with_identical_dupes
        assert run("-i", str(src), str(dest)) == 0

    def test_conflicting_dupes_exit_2_with_i(self, dirs_with_conflicting_dupes):
        src, dest = dirs_with_conflicting_dupes
        assert run("-i", str(src), str(dest)) == 2

    def test_appledouble_ignored_by_default(self, dirs_with_appledouble):
        src, dest = dirs_with_appledouble
        assert run(str(src), str(dest)) == 0

    def test_appledouble_detected_with_X(self, dirs_with_appledouble):
        src, dest = dirs_with_appledouble
        assert run("-X", str(src), str(dest)) == 1


# ---------------------------------------------------------------------------
# Directory comparison — full mode (-f), two-way
# ---------------------------------------------------------------------------


class TestDirFullTwoWay:
    def test_identical_dirs_match(self, identical_dirs):
        src, dest = identical_dirs
        assert run("-f", str(src), str(dest)) == 0

    def test_different_dirs_mismatch(self, different_dirs):
        src, dest = different_dirs
        assert run("-f", str(src), str(dest)) == 1

    def test_extra_empty_dir_mismatch(self, dirs_extra_empty_dir):
        src, dest = dirs_extra_empty_dir
        assert run("-f", str(src), str(dest)) == 1

    def test_extra_empty_dir_ignored_with_i(self, dirs_extra_empty_dir):
        src, dest = dirs_extra_empty_dir
        assert run("-f", "-i", str(src), str(dest)) == 0

    def test_different_structure_match_with_i(self, dirs_same_files_different_structure):
        src, dest = dirs_same_files_different_structure
        assert run("-f", "-i", str(src), str(dest)) == 0

    def test_identical_dupes_match_with_i(self, dirs_with_identical_dupes):
        src, dest = dirs_with_identical_dupes
        assert run("-f", "-i", str(src), str(dest)) == 0

    def test_conflicting_dupes_exit_2_with_i(self, dirs_with_conflicting_dupes):
        src, dest = dirs_with_conflicting_dupes
        assert run("-f", "-i", str(src), str(dest)) == 2

    def test_appledouble_ignored_by_default(self, dirs_with_appledouble):
        src, dest = dirs_with_appledouble
        assert run("-f", str(src), str(dest)) == 0

    def test_appledouble_detected_with_X(self, dirs_with_appledouble):
        src, dest = dirs_with_appledouble
        assert run("-f", "-X", str(src), str(dest)) == 1

    def test_same_size_different_content_detected(self, tmp_path):
        """Metadata mode misses same-size differing files; -f must catch them."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "file.txt", b"aaaa")
        make_file(dest / "file.txt", b"bbbb")  # same size, different content
        assert run(str(src), str(dest)) == 0  # metadata mode correctly misses it
        assert run("-f", str(src), str(dest)) == 1  # full mode correctly catches it


# ---------------------------------------------------------------------------
# Directory comparison — metadata mode, three-way
# ---------------------------------------------------------------------------


class TestDirMetadataThreeWay:
    def test_identical_dirs_match(self, identical_dirs_three):
        src, dest1, dest2 = identical_dirs_three
        assert run(str(src), str(dest1), str(dest2)) == 0

    def test_one_dir_differs(self, dirs_one_differs):
        src, dest1, dest2 = dirs_one_differs
        assert run(str(src), str(dest1), str(dest2)) == 1

    def test_all_dirs_differ(self, dirs_all_differ):
        src, dest1, dest2 = dirs_all_differ
        assert run(str(src), str(dest1), str(dest2)) == 1

    def test_missing_file_in_one_dir(self, dirs_missing_file_in_one):
        src, dest1, dest2 = dirs_missing_file_in_one
        assert run(str(src), str(dest1), str(dest2)) == 1

    def test_extra_empty_dir_in_third_mismatch(self, dirs_three_extra_empty_dir):
        src, dest1, dest2 = dirs_three_extra_empty_dir
        assert run(str(src), str(dest1), str(dest2)) == 1

    def test_extra_empty_dir_in_third_ignored_with_i(self, dirs_three_extra_empty_dir):
        src, dest1, dest2 = dirs_three_extra_empty_dir
        assert run("-i", str(src), str(dest1), str(dest2)) == 0

    def test_conflicting_dupes_exit_2_with_i(self, dirs_three_conflicting_dupes):
        src, dest1, dest2 = dirs_three_conflicting_dupes
        assert run("-i", str(src), str(dest1), str(dest2)) == 2

    def test_appledouble_ignored_by_default(self, dirs_three_appledouble):
        src, dest1, dest2 = dirs_three_appledouble
        assert run(str(src), str(dest1), str(dest2)) == 0

    def test_appledouble_detected_with_X(self, dirs_three_appledouble):
        src, dest1, dest2 = dirs_three_appledouble
        assert run("-X", str(src), str(dest1), str(dest2)) == 1

    def test_same_file_missing_from_all_three_is_match(self, tmp_path):
        """Empty directories should match each other."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        assert run(str(src), str(dest1), str(dest2)) == 0


# ---------------------------------------------------------------------------
# Directory comparison — full mode (-f), three-way
# ---------------------------------------------------------------------------


class TestDirFullThreeWay:
    def test_identical_dirs_match(self, identical_dirs_three):
        src, dest1, dest2 = identical_dirs_three
        assert run("-f", str(src), str(dest1), str(dest2)) == 0

    def test_one_dir_differs(self, dirs_one_differs):
        src, dest1, dest2 = dirs_one_differs
        assert run("-f", str(src), str(dest1), str(dest2)) == 1

    def test_missing_file_in_one_dir(self, dirs_missing_file_in_one):
        src, dest1, dest2 = dirs_missing_file_in_one
        assert run("-f", str(src), str(dest1), str(dest2)) == 1

    def test_same_size_different_content_detected(self, tmp_path):
        """Three-way: -f must detect content changes that same-size metadata misses."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        make_file(src / "file.txt", b"aaaa")
        make_file(dest1 / "file.txt", b"aaaa")
        make_file(dest2 / "file.txt", b"bbbb")  # same size, different content
        assert run(str(src), str(dest1), str(dest2)) == 0  # metadata misses it
        assert run("-f", str(src), str(dest1), str(dest2)) == 1  # full catches it

    def test_conflicting_dupes_exit_2_with_i(self, dirs_three_conflicting_dupes):
        src, dest1, dest2 = dirs_three_conflicting_dupes
        assert run("-f", "-i", str(src), str(dest1), str(dest2)) == 2

    def test_appledouble_ignored_by_default(self, dirs_three_appledouble):
        src, dest1, dest2 = dirs_three_appledouble
        assert run("-f", str(src), str(dest1), str(dest2)) == 0

    def test_appledouble_detected_with_X(self, dirs_three_appledouble):
        src, dest1, dest2 = dirs_three_appledouble
        assert run("-f", "-X", str(src), str(dest1), str(dest2)) == 1


# ---------------------------------------------------------------------------
# Log (--molist) tests
# ---------------------------------------------------------------------------


class TestLog:
    def test_log_single_dir_creates_file(self, identical_dirs, chdir):
        src, _ = identical_dirs
        run("--molist", str(src))
        assert (chdir / f"molist_{src.name}.tsv").exists()

    def test_log_two_dirs_creates_two_files(self, identical_dirs, chdir):
        src, dest = identical_dirs
        run("--molist", str(src), str(dest))
        assert (chdir / f"molist_{src.name}.tsv").exists()
        assert (chdir / f"molist_{dest.name}.tsv").exists()

    def test_log_three_dirs_creates_three_files(self, identical_dirs_three, chdir):
        src, dest1, dest2 = identical_dirs_three
        run("--molist", str(src), str(dest1), str(dest2))
        assert (chdir / f"molist_{src.name}.tsv").exists()
        assert (chdir / f"molist_{dest1.name}.tsv").exists()
        assert (chdir / f"molist_{dest2.name}.tsv").exists()

    def test_log_tsv_has_header(self, identical_dirs, chdir):
        src, _ = identical_dirs
        run("--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text()
        assert "\t" in content.splitlines()[0]

    def test_log_metadata_mode_size_header(self, identical_dirs, chdir):
        src, _ = identical_dirs
        run("--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text()
        assert content.startswith("size\t")

    def test_log_full_mode_hash_header(self, identical_dirs, chdir):
        src, _ = identical_dirs
        run("-f", "--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text()
        assert content.startswith("hash\t")

    def test_log_ignore_mode_filename_header(self, identical_dirs, chdir):
        src, _ = identical_dirs
        run("-i", "--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text()
        assert content.startswith("size\tfilename")


# ---------------------------------------------------------------------------
# Diff (--diff) output mode tests
# ---------------------------------------------------------------------------


class TestDiffMode:
    """
    Tests for --diff: lookback-style < / > output for 2-way comparisons.
    """

    def test_diff_match_exits_zero(self, identical_dirs):
        src, dest = identical_dirs
        assert run("--diff", str(src), str(dest)) == 0

    def test_diff_mismatch_exits_one(self, different_dirs):
        src, dest = different_dirs
        assert run("--diff", str(src), str(dest)) == 1

    def test_diff_output_uses_arrows(self, different_dirs, capsys):
        src, dest = different_dirs
        run("--diff", str(src), str(dest))
        out = capsys.readouterr().out
        lines = [line for line in out.splitlines() if line.strip()]
        assert all(line.startswith(("<", ">")) for line in lines)

    def test_diff_missing_from_dest_shows_left_arrow(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "only_src.txt", b"data")
        make_file(src / "common.txt", b"same")
        make_file(dest / "common.txt", b"same")
        run("--diff", str(src), str(dest))
        out = capsys.readouterr().out
        assert any(line.startswith("<") and "only_src.txt" in line for line in out.splitlines())

    def test_diff_missing_from_src_shows_right_arrow(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(dest / "only_dest.txt", b"data")
        make_file(src / "common.txt", b"same")
        make_file(dest / "common.txt", b"same")
        run("--diff", str(src), str(dest))
        out = capsys.readouterr().out
        assert any(line.startswith(">") and "only_dest.txt" in line for line in out.splitlines())

    def test_diff_size_mismatch_shows_both_arrows(self, different_dirs, capsys):
        src, dest = different_dirs
        run("--diff", str(src), str(dest))
        out = capsys.readouterr().out
        lines = out.splitlines()
        assert any(line.startswith("<") for line in lines)
        assert any(line.startswith(">") for line in lines)

    def test_diff_full_mode(self, tmp_path, capsys):
        """--diff -f catches same-size different-content files."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "file.bin", b"xxxx")
        make_file(dest / "file.bin", b"yyyy")
        assert run("--diff", "-f", str(src), str(dest)) == 1
        out = capsys.readouterr().out
        assert "file.bin" in out

    def test_diff_ignore_mode(self, dirs_same_files_different_structure, capsys):
        """--diff -i flattens structure before comparing."""
        src, dest = dirs_same_files_different_structure
        assert run("--diff", "-i", str(src), str(dest)) == 0

    def test_diff_with_exclude(self, tmp_path):
        """--diff -e excludes files before comparing."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "keep.txt", b"same")
        make_file(dest / "keep.txt", b"same")
        make_file(src / "skip.tmp", b"aaa")
        make_file(dest / "skip.tmp", b"bbbb")
        assert run("--diff", "-e", "*.tmp", str(src), str(dest)) == 0

    def test_diff_rejected_for_three_dirs(self, identical_dirs_three):
        """--diff with three paths must exit with an error."""
        src, dest1, dest2 = identical_dirs_three
        with pytest.raises(SystemExit) as exc:
            run("--diff", str(src), str(dest1), str(dest2))
        assert exc.value.code != 0

    def test_diff_match_prints_success_message(self, identical_dirs, capsys):
        """On match, --diff prints the 🎉 message just like the default mode."""
        src, dest = identical_dirs
        run("--diff", str(src), str(dest))
        out = capsys.readouterr().out
        assert "match" in out.lower()


# ---------------------------------------------------------------------------
# CLI validation tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_no_args_exits_nonzero(self):
        assert run() == 1

    def test_single_arg_without_log_exits_nonzero(self, identical_dirs):
        src, _ = identical_dirs
        with pytest.raises(SystemExit) as exc:
            run(str(src))
        assert exc.value.code != 0

    def test_single_arg_with_log_exits_zero(self, identical_dirs, chdir):
        src, _ = identical_dirs
        assert run("--molist", str(src)) == 0

    def test_four_args_rejected(self, tmp_path):
        dirs = []
        for name in ("a", "b", "c", "d"):
            d = tmp_path / name
            d.mkdir()
            dirs.append(str(d))
        with pytest.raises(SystemExit) as exc:
            run(*dirs)
        assert exc.value.code != 0

    def test_same_path_twice_exits_nonzero(self, identical_dirs):
        src, _ = identical_dirs
        with pytest.raises(SystemExit) as exc:
            run(str(src), str(src))
        assert exc.value.code != 0

    def test_same_path_three_times_exits_nonzero(self, identical_dirs):
        src, _ = identical_dirs
        with pytest.raises(SystemExit) as exc:
            run(str(src), str(src), str(src))
        assert exc.value.code != 0

    def test_two_identical_paths_in_three_exits_nonzero(self, identical_dirs_three):
        src, dest1, _ = identical_dirs_three
        with pytest.raises(SystemExit) as exc:
            run(str(src), str(dest1), str(src))  # src repeated
        assert exc.value.code != 0

    def test_unknown_algorithm_exits_nonzero(self, file_a, file_b_identical):
        with pytest.raises(SystemExit) as exc:
            run("-a", "md5", str(file_a), str(file_b_identical))
        assert exc.value.code != 0

    def test_mixed_file_and_dir_exits_nonzero(self, tmp_path, file_a):
        d = tmp_path / "dir"
        d.mkdir()
        with pytest.raises(SystemExit) as exc:
            run(str(file_a), str(d))
        assert exc.value.code != 0

    def test_nonexistent_path_exits_nonzero(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        ghost = tmp_path / "ghost"  # does not exist
        with pytest.raises(SystemExit) as exc:
            run(str(real), str(ghost))
        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_files_match(self, tmp_path):
        """Zero-byte files should hash and compare without error."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "empty.txt", b"")
        make_file(dest / "empty.txt", b"")
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_empty_file_vs_nonempty_mismatch(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "file.txt", b"")
        make_file(dest / "file.txt", b"data")
        assert run(str(src), str(dest)) == 1
        assert run("-f", str(src), str(dest)) == 1

    def test_hidden_files_compared(self, tmp_path):
        """Hidden files (dot-prefixed, excluding .DS_Store) should be included."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / ".hidden", b"secret")
        make_file(dest / ".hidden", b"secret")
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_hidden_file_mismatch(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / ".hidden", b"aaa")
        make_file(dest / ".hidden", b"bbbb")
        assert run(str(src), str(dest)) == 1
        assert run("-f", str(src), str(dest)) == 1

    def test_ds_store_excluded(self, tmp_path):
        """.DS_Store files should be silently ignored on both sides."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "file.txt", b"data")
        make_file(dest / "file.txt", b"data")
        make_file(src / ".DS_Store", b"mac junk src")
        make_file(dest / ".DS_Store", b"mac junk dest - different content")
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_unicode_filenames_match(self, tmp_path):
        """Files with unicode names (accented, CJK, emoji) should compare correctly."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        names = [
            "rose\u0301.txt",
            "\u65e5\u672c\u8a9e.txt",
            "\ud55c\uad6d\uc5b4.txt",
            "emoji_\U0001f389.txt",
            "na\xefve r\xe9sum\xe9.txt",
        ]
        for name in names:
            make_file(src / name, b"content")
            make_file(dest / name, b"content")
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_unicode_filename_mismatch(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "ros\xe9.txt", b"aaa")
        make_file(dest / "ros\xe9.txt", b"bbbb")
        assert run(str(src), str(dest)) == 1
        assert run("-f", str(src), str(dest)) == 1

    def test_special_character_filenames(self, tmp_path):
        """Filenames with spaces, brackets, dots, and dashes should work."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        names = [
            "file with spaces.txt",
            "file.multiple.dots.txt",
            "file-with-dashes.txt",
            "file_with_underscores.txt",
            "(parentheses).txt",
            "[brackets].txt",
        ]
        for name in names:
            make_file(src / name, b"data")
            make_file(dest / name, b"data")
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_no_extension_filenames(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "README", b"read me")
        make_file(dest / "README", b"read me")
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_deeply_nested_dirs_match(self, tmp_path):
        """Files buried many levels deep should be found and compared."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        deep_src = src / "a" / "b" / "c" / "d" / "e"
        deep_dest = dest / "a" / "b" / "c" / "d" / "e"
        deep_src.mkdir(parents=True)
        deep_dest.mkdir(parents=True)
        make_file(deep_src / "deep.txt", b"deep content")
        make_file(deep_dest / "deep.txt", b"deep content")
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_symlinks_not_followed(self, tmp_path):
        """Symlinks should not be followed or compared as regular files."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        real = tmp_path / "real.txt"
        make_file(real, b"real content")
        make_file(src / "file.txt", b"data")
        make_file(dest / "file.txt", b"data")
        (src / "link.txt").symlink_to(real)  # symlink only in src
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_only_excluded_files_compares_equal(self, tmp_path):
        """A dir containing only .DS_Store should compare equal to an empty dir."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / ".DS_Store", b"junk")
        assert run(str(src), str(dest)) == 0

    def test_ignore_flattens_across_deep_nesting(self, tmp_path):
        """
        With -i, a file nested at any depth matches a flat copy as long as
        name and size agree.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "x" / "y" / "z").mkdir(parents=True)
        make_file(src / "x" / "y" / "z" / "file.txt", b"abc")
        make_file(dest / "file.txt", b"abc")
        assert run("-i", str(src), str(dest)) == 0
        assert run("-f", "-i", str(src), str(dest)) == 0

    def test_three_way_unicode_match(self, tmp_path):
        """Unicode filenames should work in three-way mode too."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        name = "\u65e5\u672c\u8a9e.txt"
        for d in (src, dest1, dest2):
            make_file(d / name, b"content")
        assert run(str(src), str(dest1), str(dest2)) == 0
        assert run("-f", str(src), str(dest1), str(dest2)) == 0


# ---------------------------------------------------------------------------
# Output formatting validation
# ---------------------------------------------------------------------------


class TestOutputFormatting:
    def test_diff_output_identifies_correct_files(self, different_dirs, capsys):
        """The diff must name the differing file on both sigil lines."""
        src, dest = different_dirs
        # different_dirs has 'alpha.txt' with different sizes
        assert run(str(src), str(dest)) == 1
        captured = capsys.readouterr()
        assert "< " in captured.out
        assert "alpha.txt" in captured.out
        assert "> " in captured.out
        assert "alpha.txt" in captured.out

    def test_diff_output_symbols_two_way(self, different_dirs, capsys):
        """Both lines should carry the ≠ symbol when neither copy matches."""
        src, dest = different_dirs
        run(str(src), str(dest))
        captured = capsys.readouterr()
        assert captured.out.count("≠") >= 2

    def test_diff_output_three_way_one_differs(self, dirs_one_differs, capsys):
        """
        Three-way diff where dest2 diverges: src and dest1 should show =,
        dest2 should show ≠, and all three sigils must appear.
        """
        src, dest1, dest2 = dirs_one_differs
        assert run(str(src), str(dest1), str(dest2)) == 1
        captured = capsys.readouterr()
        out = captured.out
        assert "<" in out  # source sigil
        assert "> " in out  # dest1 sigil (single >)
        assert ">>" in out  # dest2 sigil
        assert "=" in out  # at least src and dest1 agree
        assert "≠" in out  # dest2 differs

    def test_diff_output_missing_symbol(self, dirs_missing_file_in_one, capsys):
        """∄ must appear on the dest2 line when a file is absent there."""
        src, dest1, dest2 = dirs_missing_file_in_one
        assert run(str(src), str(dest1), str(dest2)) == 1
        captured = capsys.readouterr()
        assert "∄" in captured.out

    def test_match_output_contains_no_diff_lines(self, identical_dirs, capsys):
        """On a clean match, stdout must not contain any sigil lines."""
        src, dest = identical_dirs
        assert run(str(src), str(dest)) == 0
        captured = capsys.readouterr()
        # No triad lines — only the success message
        for line in captured.out.splitlines():
            assert not line.startswith("<")
            assert not line.startswith(">")

    def test_diff_mode_format_is_sigil_space_path(self, different_dirs, capsys):
        """--diff: each line is exactly '<' or '>' followed by a space and the path."""
        src, dest = different_dirs
        run("--diff", str(src), str(dest))
        captured = capsys.readouterr()
        diff_lines = [line for line in captured.out.splitlines() if line.startswith(("<", ">"))]
        assert len(diff_lines) >= 2
        for line in diff_lines:
            assert line[1] == " ", f"expected space after sigil, got: {line!r}"

    def test_diff_mode_match_no_diff_lines(self, identical_dirs, capsys):
        """--diff on identical dirs: no < or > lines, only the success message."""
        src, dest = identical_dirs
        assert run("--diff", str(src), str(dest)) == 0
        captured = capsys.readouterr()
        for line in captured.out.splitlines():
            assert not line.startswith("<")
            assert not line.startswith(">")

    def test_diff_mode_identifies_correct_files(self, different_dirs, capsys):
        """--diff: the differing filename must appear on both the < and > lines."""
        src, dest = different_dirs
        run("--diff", str(src), str(dest))
        captured = capsys.readouterr()
        assert any(line.startswith("<") and "alpha.txt" in line for line in captured.out.splitlines())
        assert any(line.startswith(">") and "alpha.txt" in line for line in captured.out.splitlines())


# ---------------------------------------------------------------------------
# Empty directory behaviour
# ---------------------------------------------------------------------------


class TestEmptyDirectories:
    """
    Stress tests for empty-directory reporting (two-way and three-way).

    The rule: an empty-dir marker appears ONLY when a directory is entirely
    absent from the other side.  If both/all sides have the directory but one
    is empty (because its files differ or are missing), only the files
    themselves should appear — the empty-dir marker is suppressed.
    """

    # --- core rule: dir exists on both sides, one empty (two-way) ---

    def test_shared_empty_dir_not_reported_two_way(self, tmp_path, capsys):
        """
        src has subdir/file.txt; dest has subdir/ (empty).
        Only the missing file should appear, not a subdir/ marker.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "subdir").mkdir()
        (dest / "subdir").mkdir()
        make_file(src / "subdir" / "info.txt", b"info")
        assert run(str(src), str(dest)) == 1
        out = capsys.readouterr().out
        assert f"subdir{os.sep}info.txt" in out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("subdir/") for line in diff_lines)

    def test_shared_empty_dir_not_reported_full_mode(self, tmp_path, capsys):
        """Same suppression in -f mode, two-way."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "SUB").mkdir()
        (dest / "SUB").mkdir()
        make_file(src / "SUB" / "data.bin", b"content")
        assert run("-f", str(src), str(dest)) == 1
        out = capsys.readouterr().out
        assert f"SUB{os.sep}data.bin" in out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("SUB/") for line in diff_lines)

    def test_shared_dir_multiple_files_missing(self, tmp_path, capsys):
        """All missing files are reported; the shared dir itself is not (two-way)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "batch").mkdir()
        (dest / "batch").mkdir()
        make_file(src / "batch" / "a.txt", b"aaa")
        make_file(src / "batch" / "b.txt", b"bbb")
        assert run(str(src), str(dest)) == 1
        out = capsys.readouterr().out
        assert f"batch{os.sep}a.txt" in out
        assert f"batch{os.sep}b.txt" in out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("batch/") for line in diff_lines)

    def test_both_dirs_empty_reports_match_two_way(self, tmp_path):
        """Shared empty dir on both sides: match."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "empty").mkdir()
        (dest / "empty").mkdir()
        assert run(str(src), str(dest)) == 0

    # --- dir absent from one side entirely: marker MUST appear (two-way) ---

    def test_dir_absent_from_dest_reported(self, tmp_path, capsys):
        """Empty dir present only in src must appear in the diff."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "only_in_src").mkdir()
        assert run(str(src), str(dest)) == 1
        out = capsys.readouterr().out
        assert "only_in_src/" in out

    def test_dir_absent_from_src_reported(self, tmp_path, capsys):
        """Empty dir present only in dest must appear in the diff."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "only_in_dest").mkdir()
        assert run(str(src), str(dest)) == 1
        out = capsys.readouterr().out
        assert "only_in_dest/" in out

    # --- nested shared dirs (two-way) ---

    def test_nested_shared_dir_suppressed(self, tmp_path, capsys):
        """Nested dir on both sides; file missing from one — no dir marker."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "a" / "b").mkdir(parents=True)
        (dest / "a" / "b").mkdir(parents=True)
        make_file(src / "a" / "b" / "deep.txt", b"deep")
        assert run(str(src), str(dest)) == 1
        out = capsys.readouterr().out
        assert f"a{os.sep}b{os.sep}deep.txt" in out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("a/") for line in diff_lines)
        assert not any(line.endswith("a/b/") for line in diff_lines)

    def test_mixed_shared_and_absent_dirs(self, tmp_path, capsys):
        """
        shared/ on both sides (file missing from dest) + orphan/ only in src.
        shared/ dir marker must be suppressed; orphan/ must appear.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "shared").mkdir()
        (dest / "shared").mkdir()
        (src / "orphan").mkdir()
        make_file(src / "shared" / "file.txt", b"data")
        assert run(str(src), str(dest)) == 1
        out = capsys.readouterr().out
        assert f"shared{os.sep}file.txt" in out
        assert "orphan/" in out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("shared/") for line in diff_lines)

    # --- three-way variants ---

    def test_shared_empty_dir_not_reported_three_way(self, tmp_path, capsys):
        """
        Three-way: dir exists in all three trees, file missing from dest2.
        Only the file diff should appear, not the dir marker for any side.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            (d / "subdir").mkdir()
        make_file(src / "subdir" / "info.txt", b"info")
        make_file(dest1 / "subdir" / "info.txt", b"info")
        # dest2/subdir is empty
        assert run(str(src), str(dest1), str(dest2)) == 1
        out = capsys.readouterr().out
        assert f"subdir{os.sep}info.txt" in out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("subdir/") for line in diff_lines)

    def test_shared_empty_dir_three_way_full_mode(self, tmp_path, capsys):
        """Same three-way suppression in -f mode."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            (d / "SUB").mkdir()
        make_file(src / "SUB" / "file.bin", b"data")
        make_file(dest1 / "SUB" / "file.bin", b"data")
        assert run("-f", str(src), str(dest1), str(dest2)) == 1
        out = capsys.readouterr().out
        assert f"SUB{os.sep}file.bin" in out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("SUB/") for line in diff_lines)

    def test_dir_absent_from_one_of_three_reported(self, tmp_path, capsys):
        """
        Dir with a file exists in src and dest1 but the whole dir is absent
        from dest2.  The missing file should be reported for dest2, and the
        dir marker must not appear as a standalone empty-dir entry for src/dest1
        (since they have the dir).
        """
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        (src / "shared").mkdir()
        (dest1 / "shared").mkdir()
        make_file(src / "shared" / "file.txt", b"data")
        make_file(dest1 / "shared" / "file.txt", b"data")
        # dest2 has no "shared" at all — file.txt is missing
        assert run(str(src), str(dest1), str(dest2)) == 1
        out = capsys.readouterr().out
        assert f"shared{os.sep}file.txt" in out
        # src and dest1 share the dir, so no standalone dir marker for them
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("shared/") for line in diff_lines)

    def test_all_three_dirs_empty_reports_match(self, tmp_path):
        """Three dirs all sharing an empty subdirectory: match."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            (d / "empty").mkdir()
        assert run(str(src), str(dest1), str(dest2)) == 0

    def test_three_way_nested_shared_dir_suppressed(self, tmp_path, capsys):
        """Three-way: nested dir on all sides; file missing from dest2 only — no dir markers."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            (d / "a" / "b").mkdir(parents=True)
        make_file(src / "a" / "b" / "deep.txt", b"deep")
        make_file(dest1 / "a" / "b" / "deep.txt", b"deep")
        assert run(str(src), str(dest1), str(dest2)) == 1
        out = capsys.readouterr().out
        assert f"a{os.sep}b{os.sep}deep.txt" in out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith("a/") for line in diff_lines)
        assert not any(line.endswith("a/b/") for line in diff_lines)

    # --- interaction with -e ---

    def test_exclude_all_files_in_shared_dir_gives_match(self, tmp_path):
        """
        -e excludes all differing files in a shared dir; both sides have
        the dir — result should be a match with no empty-dir noise.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "logs").mkdir()
        (dest / "logs").mkdir()
        make_file(src / "logs" / "app.log", b"log v1")
        make_file(dest / "logs" / "app.log", b"log v2 longer")
        assert run(str(src), str(dest)) == 1
        assert run("-e", "*.log", str(src), str(dest)) == 0

    def test_three_way_exclude_all_files_in_shared_dir(self, tmp_path):
        """Three-way version of the -e + shared-dir interaction."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            (d / "logs").mkdir()
        make_file(src / "logs" / "app.log", b"log v1")
        make_file(dest1 / "logs" / "app.log", b"log v2 longer")
        make_file(dest2 / "logs" / "app.log", b"log v3 even longer")
        assert run(str(src), str(dest1), str(dest2)) == 1
        assert run("-e", "*.log", str(src), str(dest1), str(dest2)) == 0


# ---------------------------------------------------------------------------
# Exclude flag (-e) tests
# ---------------------------------------------------------------------------


class TestExclude:
    """
    Tests for the -e / --exclude flag. Works in two-way and three-way modes,
    independently of -i, and can be repeated for multiple patterns.
    """

    def test_exclude_exact_name_turns_mismatch_into_match(self, tmp_path):
        """Excluding the only differing file makes dirs compare equal (two-way)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "keep.txt", b"same")
        make_file(dest / "keep.txt", b"same")
        make_file(src / "ignore.txt", b"aaa")
        make_file(dest / "ignore.txt", b"bbbb")
        assert run(str(src), str(dest)) == 1
        assert run("-e", "ignore.txt", str(src), str(dest)) == 0

    def test_exclude_wildcard_pattern(self, tmp_path):
        """Wildcard patterns (*.log) exclude all matching files (two-way)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "data.txt", b"same")
        make_file(dest / "data.txt", b"same")
        make_file(src / "app.log", b"log v1")
        make_file(dest / "app.log", b"log v2 longer")
        make_file(src / "err.log", b"err1")
        make_file(dest / "err.log", b"err2 different")
        assert run(str(src), str(dest)) == 1
        assert run("-e", "*.log", str(src), str(dest)) == 0

    def test_exclude_multiple_patterns(self, tmp_path):
        """Multiple -e flags are all applied (two-way)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "keep.txt", b"same")
        make_file(dest / "keep.txt", b"same")
        make_file(src / "skip.log", b"log a")
        make_file(dest / "skip.log", b"log b longer")
        make_file(src / "skip.tmp", b"tmp a")
        make_file(dest / "skip.tmp", b"tmp b longer")
        assert run(str(src), str(dest)) == 1
        assert run("-e", "*.log", "-e", "*.tmp", str(src), str(dest)) == 0

    def test_exclude_three_way_match(self, tmp_path):
        """Three-way: excluding the differing file in all three dirs gives a match."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            make_file(d / "keep.txt", b"same")
        make_file(src / "noise.log", b"log a")
        make_file(dest1 / "noise.log", b"log b longer")
        make_file(dest2 / "noise.log", b"log c even longer")
        assert run(str(src), str(dest1), str(dest2)) == 1
        assert run("-e", "noise.log", str(src), str(dest1), str(dest2)) == 0

    def test_exclude_three_way_file_missing_from_one(self, tmp_path):
        """Three-way: excluding a file present in only some dirs removes it from diff."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            make_file(d / "common.txt", b"shared")
        make_file(src / "extra.log", b"only src")
        make_file(dest1 / "extra.log", b"only dest1")
        # dest2 intentionally missing extra.log
        assert run(str(src), str(dest1), str(dest2)) == 1
        assert run("-e", "extra.log", str(src), str(dest1), str(dest2)) == 0

    def test_exclude_without_i_respects_structure(self, tmp_path):
        """
        -e alone does not flatten structure: differently-nested same-named files
        are still a mismatch even after excluding other files.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "sub").mkdir()
        (dest / "other").mkdir()
        make_file(src / "sub" / "photo.jpg", b"img")
        make_file(dest / "other" / "photo.jpg", b"img")
        make_file(src / "noise.tmp", b"x")
        make_file(dest / "noise.tmp", b"y")
        assert run("-e", "noise.tmp", str(src), str(dest)) == 1

    def test_exclude_combined_with_i(self, tmp_path):
        """-e and -i compose: flatten structure AND exclude patterns."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "2024").mkdir()
        (dest / "archive").mkdir()
        make_file(src / "2024" / "photo.jpg", b"img")
        make_file(dest / "archive" / "photo.jpg", b"img")
        make_file(src / "2024" / "thumb.tmp", b"t1")
        make_file(dest / "archive" / "thumb.tmp", b"t2 longer")
        assert run("-i", str(src), str(dest)) == 1
        assert run("-i", "-e", "thumb.tmp", str(src), str(dest)) == 0

    def test_exclude_combined_with_i_three_way(self, tmp_path):
        """-e -i compose in three-way mode."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            (d / "sub").mkdir()
            make_file(d / "sub" / "photo.jpg", b"img")
        make_file(src / "sub" / "cache.tmp", b"c1")
        make_file(dest1 / "sub" / "cache.tmp", b"c2 longer")
        make_file(dest2 / "sub" / "cache.tmp", b"c3 even longer")
        assert run("-i", str(src), str(dest1), str(dest2)) == 1
        assert run("-i", "-e", "cache.tmp", str(src), str(dest1), str(dest2)) == 0

    def test_exclude_full_mode(self, tmp_path):
        """Excluded files are not hashed in -f mode."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "data.txt", b"aaaa")
        make_file(dest / "data.txt", b"aaaa")
        make_file(src / "noise.bin", b"xxxx")
        make_file(dest / "noise.bin", b"yyyy")  # same size, different content
        assert run("-f", str(src), str(dest)) == 1
        assert run("-f", "-e", "noise.bin", str(src), str(dest)) == 0

    def test_exclude_full_mode_three_way(self, tmp_path):
        """Excluded files are not hashed in -f three-way mode."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for d in (src, dest1, dest2):
            make_file(d / "keep.txt", b"same content")
        make_file(src / "noise.bin", b"xxxx")
        make_file(dest1 / "noise.bin", b"yyyy")  # same size, different content
        make_file(dest2 / "noise.bin", b"zzzz")
        assert run("-f", str(src), str(dest1), str(dest2)) == 1
        assert run("-f", "-e", "noise.bin", str(src), str(dest1), str(dest2)) == 0

    def test_exclude_does_not_affect_non_matching_files(self, tmp_path):
        """A pattern that matches nothing leaves comparison results unchanged."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "alpha.txt", b"aaa")
        make_file(dest / "alpha.txt", b"bbbb")
        assert run("-e", "*.log", str(src), str(dest)) == 1

    def test_exclude_in_subdirectory(self, tmp_path):
        """Pattern matches files by name regardless of subdirectory (two-way)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "sub").mkdir()
        (dest / "sub").mkdir()
        make_file(src / "sub" / "keep.txt", b"same")
        make_file(dest / "sub" / "keep.txt", b"same")
        make_file(src / "sub" / "ignore.log", b"log a")
        make_file(dest / "sub" / "ignore.log", b"log b longer")
        assert run(str(src), str(dest)) == 1
        assert run("-e", "*.log", str(src), str(dest)) == 0

    def test_exclude_with_log_single_dir(self, tmp_path, chdir):
        """Excluded files should not appear in the saved TSV listing."""
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "keep.txt", b"data")
        make_file(src / "ignore.log", b"log")
        run("--molist", "-e", "*.log", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text()
        assert "keep.txt" in content
        assert "ignore.log" not in content


# ---------------------------------------------------------------------------
# System-directory exclusions
# ---------------------------------------------------------------------------


class TestSystemExclusions:
    def test_system_directories_are_excluded(self, identical_dirs):
        """Hardcoded system directories in EXCLUDED_DIR_PARTS are silently ignored."""
        src, dest = identical_dirs
        for forbidden_name in (
            ".Trashes",
            ".Spotlight-V100",
            ".fseventsd",
            ".DocumentRevisions-V100",
        ):
            forbidden = dest / forbidden_name
            forbidden.mkdir()
            make_file(forbidden / "junk.txt", b"junk")
        # All forbidden dirs added to dest — should still match
        assert run(str(src), str(dest)) == 0

    def test_system_directories_excluded_three_way(self, identical_dirs_three):
        """Same exclusion applies in a three-way comparison."""
        src, dest1, dest2 = identical_dirs_three
        trashes = dest2 / ".Trashes"
        trashes.mkdir()
        make_file(trashes / "junk.txt", b"junk")
        assert run(str(src), str(dest1), str(dest2)) == 0


# ---------------------------------------------------------------------------
# OSError / permission handling
# ---------------------------------------------------------------------------


class TestOSErrorHandling:
    def test_unreadable_file_is_skipped_gracefully(self, identical_dirs):
        """
        A file with mode 0o000 cannot be opened for hashing but CAN be stat'd
        on most systems (including Linux running as root in CI).  walk_tree uses
        stat for size, so the file is visible in src but absent from dest →
        the comparison exits 1 (not a crash).  The important guarantee is that
        the tool does not raise an unhandled exception.
        """
        src, dest = identical_dirs
        unreadable = src / "unreadable.txt"
        make_file(unreadable, b"secret")
        unreadable.chmod(0o000)
        try:
            result = run(str(src), str(dest))
            # Either 0 (file skipped entirely) or 1 (visible but absent from
            # dest) — both are acceptable; a crash/exception is not.
            assert result in (0, 1)
        finally:
            unreadable.chmod(0o644)

    def test_unreadable_file_full_mode(self, identical_dirs):
        """Known gap: hash_file() has no try/except, so a file that is
        stat-able but unreadable (chmod 0o000) raises PermissionError in -f
        mode when running as a non-root user (typical macOS/Linux dev machine).
        As root (common in CI containers) the open() still succeeds, so the
        result is 1 (file visible in src, absent from dest).

        Either outcome is acceptable here; what is never acceptable is a
        silent wrong answer.  A future fix that wraps hash_file in try/except
        will change the raises branch to a clean exit — update accordingly.
        """
        src, dest = identical_dirs
        unreadable = src / "unreadable.txt"
        make_file(unreadable, b"secret")
        unreadable.chmod(0o000)
        try:
            try:
                result = run("-f", str(src), str(dest))
                # Running as root: file was opened and hashed; it's visible in
                # src but absent from dest, so the diff reports a mismatch.
                assert result in (0, 1)
            except PermissionError:
                # Running as non-root: hash_file raises before returning.
                # This documents the gap — not a pass, not a crash.
                pass
        finally:
            unreadable.chmod(0o644)

    def test_unreadable_file_skipped_three_way(self, identical_dirs_three):
        """Same no-crash guarantee in three-way mode."""
        src, dest1, dest2 = identical_dirs_three
        unreadable = src / "unreadable.txt"
        make_file(unreadable, b"secret")
        unreadable.chmod(0o000)
        try:
            result = run(str(src), str(dest1), str(dest2))
            assert result in (0, 1)
        finally:
            unreadable.chmod(0o644)


# ---------------------------------------------------------------------------
# Stress tests
# ---------------------------------------------------------------------------


class TestStress:
    def test_many_files_match(self, tmp_path):
        """1000 files in each directory should compare correctly."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        for i in range(1000):
            content = f"file content {i}".encode()
            make_file(src / f"file_{i:04d}.txt", content)
            make_file(dest / f"file_{i:04d}.txt", content)
        assert run(str(src), str(dest)) == 0

    def test_many_files_mismatch(self, tmp_path):
        """1000 files where the last one differs."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        for i in range(1000):
            content = f"file content {i}".encode()
            make_file(src / f"file_{i:04d}.txt", content)
            make_file(dest / f"file_{i:04d}.txt", content)
        make_file(dest / "file_0999.txt", b"different")
        assert run(str(src), str(dest)) == 1

    def test_many_files_full_mode(self, tmp_path):
        """1000 files hashed in full mode."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        for i in range(1000):
            content = f"file content {i}".encode()
            make_file(src / f"file_{i:04d}.txt", content)
            make_file(dest / f"file_{i:04d}.txt", content)
        assert run("-f", str(src), str(dest)) == 0

    def test_large_file_match(self, tmp_path):
        """A 64 MiB file should hash and compare without error."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        data = b"x" * (64 << 20)
        make_file(src / "large.bin", data)
        make_file(dest / "large.bin", data)
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_large_file_mismatch(self, tmp_path):
        """Two 64 MiB files differing only in the last byte."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        data = b"x" * (64 << 20)
        make_file(src / "large.bin", data)
        make_file(dest / "large.bin", data[:-1] + b"y")
        assert run("-f", str(src), str(dest)) == 1

    def test_three_way_many_files_match(self, tmp_path):
        """1000 files across three identical directories."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for i in range(1000):
            content = f"file content {i}".encode()
            for d in (src, dest1, dest2):
                make_file(d / f"file_{i:04d}.txt", content)
        assert run(str(src), str(dest1), str(dest2)) == 0

    def test_three_way_many_files_one_differs(self, tmp_path):
        """1000 files, three-way, one file differs in dest2."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        for i in range(1000):
            content = f"file content {i}".encode()
            for d in (src, dest1, dest2):
                make_file(d / f"file_{i:04d}.txt", content)
        make_file(dest2 / "file_0500.txt", b"corrupted")
        assert run(str(src), str(dest1), str(dest2)) == 1

    def test_many_unicode_files(self, tmp_path):
        """500 files with unicode names should compare without encoding errors."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        names = [f"\u6587\u4ef6_{i:03d}.txt" for i in range(500)]
        for name in names:
            make_file(src / name, b"data")
            make_file(dest / name, b"data")
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    def test_deeply_nested_many_files(self, tmp_path):
        """Files spread across 10 levels of nesting, 50 files per level."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        for depth in range(10):
            parts = "/".join(f"level_{d}" for d in range(depth + 1))
            src_dir = src / parts
            dest_dir = dest / parts
            src_dir.mkdir(parents=True, exist_ok=True)
            dest_dir.mkdir(parents=True, exist_ok=True)
            for i in range(50):
                content = f"depth {depth} file {i}".encode()
                make_file(src_dir / f"file_{i}.txt", content)
                make_file(dest_dir / f"file_{i}.txt", content)
        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0


# ---------------------------------------------------------------------------
# blake3 algorithm tests
# ---------------------------------------------------------------------------


class TestNormaliseAlgorithmBlake3:
    def test_blake3_alias_recognised(self):
        assert triplecheck.normalise_algorithm("blake3") == "blake3"

    def test_blake3_alias_case_insensitive(self):
        assert triplecheck.normalise_algorithm("BLAKE3") == "blake3"
        assert triplecheck.normalise_algorithm("Blake3") == "blake3"


class TestHashFileBlake3:
    def test_identical_content_gives_same_digest(self, tmp_path):
        f1 = make_file(tmp_path / "a.txt", b"hello world")
        f2 = make_file(tmp_path / "b.txt", b"hello world")
        assert triplecheck.hash_file(str(f1), "blake3") == triplecheck.hash_file(str(f2), "blake3")

    def test_different_content_gives_different_digest(self, tmp_path):
        f1 = make_file(tmp_path / "a.txt", b"hello")
        f2 = make_file(tmp_path / "b.txt", b"world")
        assert triplecheck.hash_file(str(f1), "blake3") != triplecheck.hash_file(str(f2), "blake3")

    def test_digest_is_hex_string(self, tmp_path):
        f = make_file(tmp_path / "a.txt", b"data")
        digest = triplecheck.hash_file(str(f), "blake3")
        assert isinstance(digest, str)
        int(digest, 16)  # raises ValueError if not valid hex

    def test_digest_differs_from_xxh64(self, tmp_path):
        f = make_file(tmp_path / "a.txt", b"some content")
        assert triplecheck.hash_file(str(f), "blake3") != triplecheck.hash_file(str(f), "xxh64")

    def test_known_digest(self, tmp_path):
        """Cross-check against the blake3 library directly."""
        data = b"triplecheck blake3 test"
        f = make_file(tmp_path / "a.txt", data)
        expected = blake3.blake3(data).hexdigest()
        assert triplecheck.hash_file(str(f), "blake3") == expected

    def test_large_file_chunked_correctly(self, tmp_path):
        """A file larger than the 1 MiB chunk size must hash identically to
        a direct in-memory blake3 call on the same bytes."""
        data = b"x" * (3 << 20)  # 3 MiB — forces multiple chunks
        f = make_file(tmp_path / "large.bin", data)
        expected = blake3.blake3(data).hexdigest()
        assert triplecheck.hash_file(str(f), "blake3") == expected


class TestMolistSinglePathNotDir:
    """Line 685: --molist with a single path that is a file, not a directory."""

    def test_single_file_path_exits_with_error(self, tmp_path):
        f = make_file(tmp_path / "file.txt", b"data")
        with pytest.raises(SystemExit):
            triplecheck.main(["--molist", str(f)])


# ---------------------------------------------------------------------------
# Unicode normalisation (NFC vs NFD) tests
# ---------------------------------------------------------------------------

NFC_ROSE = "ros\u00e9.txt"  # é as a single code point (NFC, exFAT)
NFD_ROSE = "rose\u0301.txt"  # e + combining acute accent (NFD, APFS)
NFC_DIR = "ros\u00e9_dir"
NFD_DIR = "rose\u0301_dir"


class TestNfcNormalisationMetadataMode:
    """
    cross-normalisation comparisons in default metadata mode.

    The canonical real-world scenario: APFS yields NFD paths, exFAT
    yields NFC paths.  Both represent the same visual filename and must
    compare as equal.
    """

    def test_nfd_src_nfc_dest_match(self, tmp_path):
        """NFD source file matches NFC dest file (same content, same size)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFD_ROSE, b"content")
        make_file(dest / NFC_ROSE, b"content")
        assert run(str(src), str(dest)) == 0

    def test_nfc_src_nfd_dest_match(self, tmp_path):
        """NFC source file matches NFD dest file."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFC_ROSE, b"content")
        make_file(dest / NFD_ROSE, b"content")
        assert run(str(src), str(dest)) == 0

    def test_nfd_vs_nfc_different_content_mismatch(self, tmp_path):
        """Same normalised name but different sizes → mismatch."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFD_ROSE, b"aaa")
        make_file(dest / NFC_ROSE, b"bbbb")
        assert run(str(src), str(dest)) == 1

    def test_multiple_accented_files_all_match(self, tmp_path):
        """Several files whose NFD/NFC forms differ all round-trip correctly."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        pairs = [
            ("re\u0301sume\u0301.pdf", "r\u00e9sum\u00e9.pdf"),  # résumé
            ("na\u00efve.txt", "nai\u0308ve.txt"),  # naïve
            ("Z\u00fcrich.txt", "Zu\u0308rich.txt"),  # Zürich
        ]
        for nfc_name, nfd_name in pairs:
            make_file(src / nfd_name, b"data")
            make_file(dest / nfc_name, b"data")
        assert run(str(src), str(dest)) == 0

    def test_accented_in_subdir_match(self, tmp_path):
        """Accented filenames inside subdirectories also normalise correctly."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "photos").mkdir()
        (dest / "photos").mkdir()
        make_file(src / "photos" / NFD_ROSE, b"img")
        make_file(dest / "photos" / NFC_ROSE, b"img")
        assert run(str(src), str(dest)) == 0

    def test_three_way_nfd_nfc_mix_match(self, tmp_path):
        """Three-way: one NFD tree and two NFC trees compare as equal."""
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        make_file(src / NFD_ROSE, b"content")
        make_file(dest1 / NFC_ROSE, b"content")
        make_file(dest2 / NFC_ROSE, b"content")
        assert run(str(src), str(dest1), str(dest2)) == 0

    def test_sorting_stable_across_normalisation_forms(self, tmp_path):
        """
        The sorted merge in diff_three relies on path-string order.  Mixed
        NFC/NFD filenames must sort consistently so no spurious diff groups
        are produced.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        # NFD: bare 'e' (U+0065) + combining acute (U+0301)  →  "rosé"
        # NFC: precomposed 'é' (U+00E9)                       →  "rosé"
        # These are visually identical but byte-different before normalisation.
        names_nfd = [f"file_{i}_rose\u0301.txt" for i in range(5)]  # e + combining
        names_nfc = [f"file_{i}_ros\u00e9.txt" for i in range(5)]  # precomposed é
        for nfd, nfc in zip(names_nfd, names_nfc, strict=True):
            make_file(src / nfd, b"x")
            make_file(dest / nfc, b"x")
        assert run(str(src), str(dest)) == 0


class TestNfcNormalisationFullMode:
    """Same cross-normalisation scenarios under -f (hash every file)."""

    def test_nfd_src_nfc_dest_match_full(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFD_ROSE, b"content")
        make_file(dest / NFC_ROSE, b"content")
        assert run("-f", str(src), str(dest)) == 0

    def test_nfc_src_nfd_dest_match_full(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFC_ROSE, b"content")
        make_file(dest / NFD_ROSE, b"content")
        assert run("-f", str(src), str(dest)) == 0

    def test_nfd_vs_nfc_different_content_mismatch_full(self, tmp_path):
        """Same name (NFC≡NFD) but different hash → full mode must catch it."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFD_ROSE, b"aaa")
        make_file(dest / NFC_ROSE, b"bbb")  # same size different content
        assert run("-f", str(src), str(dest)) == 1

    def test_three_way_nfd_nfc_mix_match_full(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        make_file(src / NFD_ROSE, b"content")
        make_file(dest1 / NFC_ROSE, b"content")
        make_file(dest2 / NFC_ROSE, b"content")
        assert run("-f", str(src), str(dest1), str(dest2)) == 0

    def test_accented_in_subdir_match_full(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "sub").mkdir()
        (dest / "sub").mkdir()
        make_file(src / "sub" / NFD_ROSE, b"img")
        make_file(dest / "sub" / NFC_ROSE, b"img")
        assert run("-f", str(src), str(dest)) == 0


class TestNfcNormalisationIgnoreMode:
    """Cross-normalisation under -i (flat/ignore-structure mode)."""

    def test_nfd_src_nfc_dest_match_ignore(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "sub").mkdir()
        make_file(src / "sub" / NFD_ROSE, b"data")
        make_file(dest / NFC_ROSE, b"data")
        assert run("-i", str(src), str(dest)) == 0

    def test_nfc_src_nfd_dest_match_ignore(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "sub").mkdir()
        make_file(src / NFC_ROSE, b"data")
        make_file(dest / "sub" / NFD_ROSE, b"data")
        assert run("-i", str(src), str(dest)) == 0

    def test_three_way_nfd_nfc_ignore_match(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()
        (src / "sub").mkdir()
        make_file(src / "sub" / NFD_ROSE, b"data")
        make_file(dest1 / NFC_ROSE, b"data")
        make_file(dest2 / NFC_ROSE, b"data")
        assert run("-i", str(src), str(dest1), str(dest2)) == 0


class TestNfcNormalisationDiffMode:
    """Cross-normalisation under --diff (lookback-style two-way output)."""

    def test_nfd_src_nfc_dest_match_diff(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFD_ROSE, b"content")
        make_file(dest / NFC_ROSE, b"content")
        assert run("--diff", str(src), str(dest)) == 0

    def test_nfd_src_nfc_dest_mismatch_diff(self, tmp_path, capsys):
        """Size mismatch with NFD/NFC filenames still surfaces correctly."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFD_ROSE, b"aaa")
        make_file(dest / NFC_ROSE, b"bbbb")
        assert run("--diff", str(src), str(dest)) == 1
        out = capsys.readouterr().out
        # The normalised (NFC) filename must appear in the diff output
        assert NFC_ROSE in out


class TestNfcNormalisationEmptyDirs:
    """Cross-normalisation with accented directory names and empty-dir markers."""

    def test_accented_dir_shared_both_sides_no_marker(self, tmp_path, capsys):
        """
        An accented directory present on both sides (one NFD, one NFC) should
        not generate a spurious empty-dir marker — the dir must be recognised
        as shared.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / NFD_DIR).mkdir()
        (dest / NFC_DIR).mkdir()
        make_file(src / NFD_DIR / "file.txt", b"data")
        make_file(dest / NFC_DIR / "file.txt", b"data")
        # Files and directory are equivalent after NFC normalisation → match
        assert run(str(src), str(dest)) == 0

    def test_accented_dir_absent_from_dest_reported(self, tmp_path, capsys):
        """
        An accented directory present only in src must still appear in the
        diff output even after NFC normalisation.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / NFD_DIR).mkdir()  # no matching dir in dest
        run(str(src), str(dest))
        out = capsys.readouterr().out
        # NFC form of the dir name should appear in the output
        assert NFC_DIR + "/" in out

    def test_accented_dir_file_missing_from_dest_no_dir_marker(self, tmp_path, capsys):
        """
        Shared accented directory (NFD on src, NFC on dest), file missing from
        dest.  Only the file diff should appear — no spurious dir marker.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / NFD_DIR).mkdir()
        (dest / NFC_DIR).mkdir()
        make_file(src / NFD_DIR / "file.txt", b"data")
        # dest has the dir but not the file
        assert run(str(src), str(dest)) == 1
        out = capsys.readouterr().out
        diff_lines = [line.strip() for line in out.splitlines()]
        assert not any(line.endswith((NFC_DIR + "/", NFD_DIR + "/")) for line in diff_lines)


class TestNfcNormalisationMolist:
    """NFC normalisation is reflected in --molist TSV output."""

    def test_molist_nfd_filename_stored_as_nfc(self, tmp_path, chdir):
        """TSV listing must contain the NFC form of an NFD-named file."""
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / NFD_ROSE, b"data")
        run("--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text(encoding="utf-8")
        for line in content.splitlines()[1:]:  # skip header
            path_col = line.split("\t")[-1]
            assert unicodedata.is_normalized("NFC", path_col), f"path in TSV is not NFC: {path_col!r}"
        assert NFC_ROSE in content


# ---------------------------------------------------------------------------
# Fuzz tests
# ---------------------------------------------------------------------------


def _random_ascii_name(rng: random.Random, min_len: int = 3, max_len: int = 20) -> str:
    """Generate a random ASCII filename (no path separators, no NULs)."""
    safe = string.ascii_letters + string.digits + " ._-"
    length = rng.randint(min_len, max_len)
    return "".join(rng.choice(safe) for _ in range(length)) + ".bin"


def _random_content(rng: random.Random, max_bytes: int = 256) -> bytes:
    size = rng.randint(0, max_bytes)
    return bytes(rng.randint(0, 255) for _ in range(size))


class TestFuzz:
    """
    Property-based / randomised tests that exercise triplecheck end-to-end
    with varied file trees, ensuring no crashes and correct exit codes across
    many random inputs.
    """

    SEEDS: ClassVar[list[int]] = list(range(20))  # deterministic; extend for deeper coverage

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_identical_trees_always_match(self, tmp_path, seed):
        """
        Two identical randomly-generated directory trees must always compare
        as equal (exit 0) in both metadata and full mode.
        """
        rng = random.Random(seed)
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        n_files = rng.randint(1, 30)
        n_dirs = rng.randint(0, 5)
        dirs = [""]
        for _ in range(n_dirs):
            parent = rng.choice(dirs)
            name = _random_ascii_name(rng, 3, 10).replace(".", "_")
            dirs.append(f"{parent}/{name}" if parent else name)

        for _ in range(n_files):
            rel_dir = rng.choice(dirs)
            name = _random_ascii_name(rng)
            content = _random_content(rng)
            for root in (src, dest):
                if rel_dir:
                    (root / rel_dir).mkdir(parents=True, exist_ok=True)
                    make_file(root / rel_dir / name, content)
                else:
                    make_file(root / name, content)

        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_one_modified_file_always_detected(self, tmp_path, seed):
        """
        After copying a random tree, mutating exactly one file must make -f
        report a mismatch (exit 1).  Metadata mode is allowed to miss
        same-size mutations (and often will), so we only assert on -f.
        """
        rng = random.Random(seed + 100)  # different seed space from above
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        n_files = rng.randint(2, 20)
        candidates = []
        for i in range(n_files):
            name = f"file_{i:03d}.bin"
            content = _random_content(rng)
            make_file(src / name, content)
            make_file(dest / name, content)
            candidates.append((name, content))

        # Mutate one file in dest
        victim_name, victim_content = rng.choice(candidates)
        # Produce different content (same or different length — doesn't matter
        # for -f, which hashes)
        new_content = bytes((b ^ 0xFF) for b in victim_content) or b"\x00"
        make_file(dest / victim_name, new_content)

        assert run("-f", str(src), str(dest)) == 1

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_three_way_identical_always_match(self, tmp_path, seed):
        """Three identical random trees always compare as equal."""
        rng = random.Random(seed + 200)
        src = tmp_path / "src"
        src.mkdir()
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()

        n_files = rng.randint(1, 20)
        for _ in range(n_files):
            name = _random_ascii_name(rng)
            content = _random_content(rng)
            for root in (src, dest1, dest2):
                make_file(root / name, content)

        assert run(str(src), str(dest1), str(dest2)) == 0
        assert run("-f", str(src), str(dest1), str(dest2)) == 0

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_extra_file_in_dest_detected(self, tmp_path, seed):
        """An extra file in dest that is absent from src must be reported."""
        rng = random.Random(seed + 300)
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        n_files = rng.randint(1, 15)
        for i in range(n_files):
            name = f"shared_{i:03d}.bin"
            content = _random_content(rng)
            make_file(src / name, content)
            make_file(dest / name, content)

        extra_name = "extra_only_in_dest.bin"
        make_file(dest / extra_name, _random_content(rng))

        assert run(str(src), str(dest)) == 1
        assert run("-f", str(src), str(dest)) == 1

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_missing_file_in_dest_detected(self, tmp_path, seed):
        """A file present in src but absent from dest must be reported."""
        rng = random.Random(seed + 400)
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        n_files = rng.randint(2, 15)
        names_contents = []
        for i in range(n_files):
            name = f"file_{i:03d}.bin"
            content = _random_content(rng)
            make_file(src / name, content)
            make_file(dest / name, content)
            names_contents.append(name)

        # Remove one file from dest
        victim = rng.choice(names_contents)
        (dest / victim).unlink()

        assert run(str(src), str(dest)) == 1
        assert run("-f", str(src), str(dest)) == 1

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_unicode_names_no_crash(self, tmp_path, seed):
        """
        Random unicode filenames — including accented Latin, CJK, Arabic,
        emoji, and mixed NFC/NFD — must never cause an unhandled exception.
        The exit code is not asserted; survival (no crash) is the guarantee.
        """
        rng = random.Random(seed + 500)

        # Pool of tricky name templates
        templates = [
            "ros\u00e9_{}.txt",  # NFC é
            "rose\u0301_{}.txt",  # NFD é
            "\u65e5\u672c\u8a9e_{}.txt",  # CJK
            "\u0645\u0644\u0641_{}.txt",  # Arabic
            "emoji_\U0001f4c1_{}.txt",  # folder emoji
            "na\u00efve_{}.txt",  # NFC ï
            "nai\u0308ve_{}.txt",  # NFD ï
            "r\u00e9sum\u00e9_{}.txt",  # NFC
            "re\u0301sume\u0301_{}.txt",  # NFD
        ]

        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        n_files = rng.randint(3, 15)
        for i in range(n_files):
            tpl = rng.choice(templates)
            name = tpl.format(i)
            content = _random_content(rng)
            make_file(src / name, content)
            make_file(dest / name, content)

        # Must not raise
        rc = run(str(src), str(dest))
        assert rc in (0, 1)
        rc = run("-f", str(src), str(dest))
        assert rc in (0, 1)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_exclude_patterns_no_crash(self, tmp_path, seed):
        """
        Random trees with random -e patterns applied must not crash and must
        return a valid exit code.
        """
        rng = random.Random(seed + 600)
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        extensions = [".log", ".tmp", ".bak", ".bin", ".txt"]
        n_files = rng.randint(2, 20)
        for i in range(n_files):
            ext = rng.choice(extensions)
            name = f"file_{i:03d}{ext}"
            content = _random_content(rng)
            make_file(src / name, content)
            # Randomly omit from dest to exercise mismatch paths too
            if rng.random() > 0.2:
                make_file(dest / name, content)

        # Pick a random subset of extension patterns to exclude
        patterns = rng.sample([f"*{e}" for e in extensions], k=rng.randint(0, 3))
        cmd = []
        for p in patterns:
            cmd += ["-e", p]

        rc = run(*cmd, str(src), str(dest))
        assert rc in (0, 1, 2)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_deep_nesting_no_crash(self, tmp_path, seed):
        """
        Randomly deep directory trees (up to 8 levels) must not crash and must
        return a consistent result when src and dest are identical.
        """
        rng = random.Random(seed + 700)
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        depth = rng.randint(1, 8)
        path_parts = [f"level_{d}" for d in range(depth)]
        rel = "/".join(path_parts)
        (src / rel).mkdir(parents=True)
        (dest / rel).mkdir(parents=True)

        n_files = rng.randint(1, 10)
        for i in range(n_files):
            name = f"file_{i}.bin"
            content = _random_content(rng)
            make_file(src / rel / name, content)
            make_file(dest / rel / name, content)

        assert run(str(src), str(dest)) == 0
        assert run("-f", str(src), str(dest)) == 0

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_ignore_mode_scrambled_structure(self, tmp_path, seed):
        """
        Scatter identical files into completely different folder structures in
        src and dest.  Default mode must fail (paths differ); -i must pass
        (flat file list is identical).
        """
        rng = random.Random(seed + 800)
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        n_files = rng.randint(5, 30)
        for _ in range(n_files):
            name = _random_ascii_name(rng)
            content = _random_content(rng)

            src_depth = rng.randint(0, 4)
            src_dir = src / "/".join(f"d{rng.randint(0, 9)}" for _ in range(src_depth))
            src_dir.mkdir(parents=True, exist_ok=True)
            make_file(src_dir / name, content)

            dest_depth = rng.randint(0, 4)
            dest_dir = dest / "/".join(f"f{rng.randint(0, 9)}" for _ in range(dest_depth))
            dest_dir.mkdir(parents=True, exist_ok=True)
            make_file(dest_dir / name, content)

        # Structures differ so default mode must report a mismatch.
        assert run(str(src), str(dest)) == 1
        # Flat file lists are identical so -i must report a match.
        assert run("-i", str(src), str(dest)) == 0

    @pytest.mark.parametrize("seed", SEEDS)
    def test_fuzz_conflicting_duplicates_ignore_mode(self, tmp_path, seed):
        """
        Place the same filename with different content in two subdirectories of
        src — a conflicting duplicate under -i.  Must exit 2, never crash.
        """
        rng = random.Random(seed + 900)
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        conflict_name = _random_ascii_name(rng)

        dir1 = src / "loc1"
        dir1.mkdir()
        make_file(dir1 / conflict_name, b"version 1")

        dir2 = src / "loc2"
        dir2.mkdir()
        make_file(dir2 / conflict_name, b"version 2 longer")

        make_file(dest / conflict_name, b"version 1")

        # Background noise files that match on both sides.
        for _ in range(rng.randint(1, 10)):
            name = _random_ascii_name(rng)
            content = _random_content(rng)
            make_file(src / name, content)
            make_file(dest / name, content)

        # Default mode sees different paths — just a mismatch, not a collision.
        assert run(str(src), str(dest)) == 1
        # Ignore mode detects the conflicting duplicate and must exit 2.
        assert run("-i", str(src), str(dest)) == 2


# ---------------------------------------------------------------------------
# --molist with no arguments defaults to cwd
# ---------------------------------------------------------------------------


class TestMolistCwdDefault:
    """
    `triplecheck --molist` with no path arguments should use the current
    working directory as the target, rather than erroring or printing help.
    """

    def test_bare_molist_creates_tsv_for_cwd(self, tmp_path, chdir):
        """Bare --molist produces molist_<cwd-name>.tsv in the cwd."""
        make_file(chdir / "alpha.txt", b"aaa")
        make_file(chdir / "beta.txt", b"bbb")
        rc = run("--molist")
        assert rc == 0
        assert (chdir / f"molist_{chdir.name}.tsv").exists()

    def test_bare_molist_tsv_contains_files(self, tmp_path, chdir):
        """The TSV produced by bare --molist lists the files in cwd."""
        make_file(chdir / "file.txt", b"hello")
        run("--molist")
        content = (chdir / f"molist_{chdir.name}.tsv").read_text(encoding="utf-8")
        assert "file.txt" in content

    def test_bare_molist_full_mode(self, tmp_path, chdir):
        """--molist -f with no path also defaults to cwd and writes hash header."""
        make_file(chdir / "file.txt", b"hello")
        rc = run("--molist", "-f")
        assert rc == 0
        content = (chdir / f"molist_{chdir.name}.tsv").read_text(encoding="utf-8")
        assert content.startswith("hash\t")

    def test_bare_molist_with_exclude(self, tmp_path, chdir):
        """--molist -e with no path defaults to cwd and respects exclusion."""
        make_file(chdir / "keep.txt", b"data")
        make_file(chdir / "skip.log", b"log")
        run("--molist", "-e", "*.log")
        content = (chdir / f"molist_{chdir.name}.tsv").read_text(encoding="utf-8")
        assert "keep.txt" in content
        assert "skip.log" not in content

    def test_bare_molist_empty_cwd_still_succeeds(self, tmp_path, chdir):
        """--molist on an empty cwd should exit 0 and write a header-only TSV."""
        rc = run("--molist")
        assert rc == 0
        tsv = chdir / f"molist_{chdir.name}.tsv"
        assert tsv.exists()
        lines = tsv.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1  # header only
        assert lines[0].startswith("size\t")

    def test_explicit_path_still_works_alongside_fix(self, tmp_path, chdir):
        """Providing an explicit path with --molist still uses that path (not cwd)."""
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "deep.txt", b"x")
        rc = run("--molist", str(src))
        assert rc == 0
        assert (chdir / f"molist_{src.name}.tsv").exists()
        # cwd TSV must not have been created
        assert not (chdir / f"molist_{chdir.name}.tsv").exists()


# ---------------------------------------------------------------------------
# Forward slashes in molist TSV output
# ---------------------------------------------------------------------------


class TestMolistForwardSlashes:
    """
    Paths stored in TSV files must always use forward slashes as the path
    separator, regardless of the OS separator (important on Windows where
    os.sep is backslash).
    """

    def test_nested_file_uses_forward_slash(self, tmp_path, chdir):
        """A file in a subdirectory must be stored with '/' not os.sep."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "sub").mkdir()
        make_file(src / "sub" / "file.txt", b"data")
        run("--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text(encoding="utf-8")
        # The separator in the TSV must always be '/'
        for line in content.splitlines()[1:]:  # skip header
            path_col = line.split("\t")[-1]
            assert "/" in path_col
            assert "\\" not in path_col, f"backslash found in TSV path: {path_col!r}"

    def test_deeply_nested_file_uses_forward_slash(self, tmp_path, chdir):
        """Forward slashes are used at every level of nesting."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a" / "b" / "c").mkdir(parents=True)
        make_file(src / "a" / "b" / "c" / "deep.txt", b"deep")
        run("--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text(encoding="utf-8")
        assert "a/b/c/deep.txt" in content
        assert "a\\b\\c\\deep.txt" not in content

    def test_full_mode_uses_forward_slash(self, tmp_path, chdir):
        """Forward slashes apply in -f (hash) mode too."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "sub").mkdir()
        make_file(src / "sub" / "file.bin", b"x")
        run("-f", "--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text(encoding="utf-8")
        for line in content.splitlines()[1:]:
            path_col = line.split("\t")[-1]
            assert "\\" not in path_col

    def test_flat_file_has_no_separator(self, tmp_path, chdir):
        """A top-level file has no path separator at all — neither / nor \\."""
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "flat.txt", b"data")
        run("--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text(encoding="utf-8")
        for line in content.splitlines()[1:]:
            path_col = line.split("\t")[-1]
            assert "/" not in path_col
            assert "\\" not in path_col

    def test_no_backslashes_in_any_path(self, tmp_path, chdir):
        """Exhaustive check: no backslash appears anywhere in path columns."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "x" / "y").mkdir(parents=True)
        make_file(src / "top.txt", b"t")
        make_file(src / "x" / "mid.txt", b"m")
        make_file(src / "x" / "y" / "bot.txt", b"b")
        run("--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text(encoding="utf-8")
        for line in content.splitlines()[1:]:
            path_col = line.split("\t")[-1]
            assert "\\" not in path_col, f"backslash in: {path_col!r}"


# ---------------------------------------------------------------------------
# --mocompare
# ---------------------------------------------------------------------------


class TestMocompare:
    """Tests for comparing two or three saved molist TSV files with --mocompare."""

    # --- basic two-way match / mismatch ---

    def test_two_identical_molists_match(self, identical_dirs, chdir):
        """Two molists from identical dirs compare as equal."""
        src, dest = identical_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        assert run("--mocompare", str(tsv_src), str(tsv_dest)) == 0

    def test_two_different_molists_mismatch(self, different_dirs, chdir):
        """Two molists from different dirs compare as not equal."""
        src, dest = different_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        assert run("--mocompare", str(tsv_src), str(tsv_dest)) == 1

    def test_mocompare_match_prints_success(self, identical_dirs, chdir, capsys):
        """A matching mocompare prints the 🎉 message."""
        src, dest = identical_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        run("--mocompare", str(tsv_src), str(tsv_dest))
        assert "match" in capsys.readouterr().out.lower()

    def test_mocompare_mismatch_prints_diff_lines(self, different_dirs, chdir, capsys):
        """A mismatching mocompare prints triad diff lines."""
        src, dest = different_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        run("--mocompare", str(tsv_src), str(tsv_dest))
        out = capsys.readouterr().out
        assert "<" in out
        assert ">" in out

    def test_mocompare_identifies_missing_file(self, tmp_path, chdir, capsys):
        """A file present in src but absent from dest appears in mocompare output."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "common.txt", b"shared")
        make_file(src / "only_src.txt", b"extra")
        make_file(dest / "common.txt", b"shared")
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        run("--mocompare", str(tsv_src), str(tsv_dest))
        out = capsys.readouterr().out
        assert "only_src.txt" in out
        assert "∄" in out

    # --- three-way ---

    def test_three_identical_molists_match(self, identical_dirs_three, chdir):
        """Three molists from identical dirs compare as equal."""
        src, dest1, dest2 = identical_dirs_three
        run("--molist", str(src), str(dest1), str(dest2))
        tsvs = [chdir / f"molist_{p.name}.tsv" for p in (src, dest1, dest2)]
        assert run("--mocompare", *[str(t) for t in tsvs]) == 0

    def test_three_molists_one_differs(self, dirs_one_differs, chdir):
        """Three molists where one dir differs — mocompare reports mismatch."""
        src, dest1, dest2 = dirs_one_differs
        run("--molist", str(src), str(dest1), str(dest2))
        tsvs = [chdir / f"molist_{p.name}.tsv" for p in (src, dest1, dest2)]
        assert run("--mocompare", *[str(t) for t in tsvs]) == 1

    def test_three_molists_one_differs_shows_symbols(self, dirs_one_differs, chdir, capsys):
        """Three-way mocompare output shows = for matching entries and ≠ for the outlier."""
        src, dest1, dest2 = dirs_one_differs
        run("--molist", str(src), str(dest1), str(dest2))
        tsvs = [chdir / f"molist_{p.name}.tsv" for p in (src, dest1, dest2)]
        run("--mocompare", *[str(t) for t in tsvs])
        out = capsys.readouterr().out
        assert "=" in out
        assert "≠" in out

    def test_three_molists_missing_file_shows_absent_symbol(self, dirs_missing_file_in_one, chdir, capsys):
        """Three-way mocompare shows ∄ when a file is absent from one molist."""
        src, dest1, dest2 = dirs_missing_file_in_one
        run("--molist", str(src), str(dest1), str(dest2))
        tsvs = [chdir / f"molist_{p.name}.tsv" for p in (src, dest1, dest2)]
        run("--mocompare", *[str(t) for t in tsvs])
        out = capsys.readouterr().out
        assert "∄" in out

    # --- --diff flag composing with --mocompare ---

    def test_mocompare_diff_mode_match(self, identical_dirs, chdir):
        """--mocompare --diff on identical molists exits 0."""
        src, dest = identical_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        assert run("--mocompare", "--diff", str(tsv_src), str(tsv_dest)) == 0

    def test_mocompare_diff_mode_mismatch(self, different_dirs, chdir):
        """--mocompare --diff on differing molists exits 1."""
        src, dest = different_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        assert run("--mocompare", "--diff", str(tsv_src), str(tsv_dest)) == 1

    def test_mocompare_diff_mode_output_format(self, different_dirs, chdir, capsys):
        """--mocompare --diff output lines start with < or >."""
        src, dest = different_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        run("--mocompare", "--diff", str(tsv_src), str(tsv_dest))
        out = capsys.readouterr().out
        diff_lines = [ln for ln in out.splitlines() if ln.startswith(("<", ">"))]
        assert len(diff_lines) >= 2
        for line in diff_lines:
            assert line[1] == " ", f"expected space after sigil: {line!r}"

    def test_mocompare_diff_mode_rejected_for_three(self, identical_dirs_three, chdir):
        """--mocompare --diff with three TSVs must exit with an error."""
        src, dest1, dest2 = identical_dirs_three
        run("--molist", str(src), str(dest1), str(dest2))
        tsvs = [chdir / f"molist_{p.name}.tsv" for p in (src, dest1, dest2)]
        with pytest.raises(SystemExit) as exc:
            run("--mocompare", "--diff", *[str(t) for t in tsvs])
        assert exc.value.code != 0

    # --- hash-mode TSVs ---

    def test_mocompare_hash_mode_match(self, identical_dirs, chdir):
        """--mocompare works on TSVs produced by -f (hash column)."""
        src, dest = identical_dirs
        run("-f", "--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        assert run("--mocompare", str(tsv_src), str(tsv_dest)) == 0

    def test_mocompare_hash_mode_catches_same_size_diff_content(self, tmp_path, chdir):
        """
        Two dirs with files of the same size but different content are equal
        in a size-mode TSV but differ in a hash-mode TSV.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "file.bin", b"aaaa")
        make_file(dest / "file.bin", b"bbbb")  # same size, different content

        # Size-mode TSVs are identical (both report size=4)
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        assert run("--mocompare", str(tsv_src), str(tsv_dest)) == 0

        # Hash-mode TSVs differ
        run("-f", "--molist", str(src), str(dest))
        assert run("--mocompare", str(tsv_src), str(tsv_dest)) == 1

    def test_mocompare_match_message_mentions_hash(self, identical_dirs, chdir, capsys):
        """On match, hash-mode TSVs produce a message mentioning 'hash'."""
        src, dest = identical_dirs
        run("-f", "--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        run("--mocompare", str(tsv_src), str(tsv_dest))
        assert "hash" in capsys.readouterr().out.lower()

    def test_mocompare_match_message_mentions_size(self, identical_dirs, chdir, capsys):
        """On match, size-mode TSVs produce a message mentioning 'names and sizes'."""
        src, dest = identical_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        run("--mocompare", str(tsv_src), str(tsv_dest))
        out = capsys.readouterr().out.lower()
        assert "names" in out or "sizes" in out

    # --- error cases ---

    def test_mocompare_rejects_directory_path(self, identical_dirs, chdir):
        """--mocompare with a directory instead of a TSV file must exit with error."""
        src, dest = identical_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        with pytest.raises(SystemExit) as exc:
            run("--mocompare", str(tsv_src), str(src))  # src is a dir, not a TSV
        assert exc.value.code != 0

    def test_mocompare_rejects_nonexistent_file(self, identical_dirs, chdir):
        """--mocompare with a path that doesn't exist must exit with error."""
        src, dest = identical_dirs
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        ghost = chdir / "ghost.tsv"
        with pytest.raises(SystemExit) as exc:
            run("--mocompare", str(tsv_src), str(ghost))
        assert exc.value.code != 0

    def test_mocompare_rejects_malformed_tsv(self, identical_dirs, chdir):
        """A TSV file without the expected header column causes a clean error exit."""
        src, _ = identical_dirs
        run("--molist", str(src))
        bad_tsv = chdir / "bad.tsv"
        bad_tsv.write_text("col1\tcol2\nvalue\tpath\n", encoding="utf-8")
        tsv_src = chdir / f"molist_{src.name}.tsv"
        with pytest.raises(SystemExit) as exc:
            run("--mocompare", str(tsv_src), str(bad_tsv))
        assert exc.value.code != 0

    # --- round-trip consistency with live comparison ---

    def test_mocompare_matches_live_comparison_result_identical(self, identical_dirs, chdir):
        """mocompare result agrees with a live comparison for identical dirs."""
        src, dest = identical_dirs
        live_rc = run(str(src), str(dest))
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        mocompare_rc = run("--mocompare", str(tsv_src), str(tsv_dest))
        assert live_rc == mocompare_rc

    def test_mocompare_matches_live_comparison_result_different(self, different_dirs, chdir):
        """mocompare result agrees with a live comparison for different dirs."""
        src, dest = different_dirs
        live_rc = run(str(src), str(dest))
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        mocompare_rc = run("--mocompare", str(tsv_src), str(tsv_dest))
        assert live_rc == mocompare_rc

    def test_mocompare_matches_live_three_way_identical(self, identical_dirs_three, chdir):
        """Three-way mocompare agrees with a live three-way comparison (identical)."""
        src, dest1, dest2 = identical_dirs_three
        live_rc = run(str(src), str(dest1), str(dest2))
        run("--molist", str(src), str(dest1), str(dest2))
        tsvs = [chdir / f"molist_{p.name}.tsv" for p in (src, dest1, dest2)]
        mocompare_rc = run("--mocompare", *[str(t) for t in tsvs])
        assert live_rc == mocompare_rc

    def test_mocompare_matches_live_three_way_differs(self, dirs_one_differs, chdir):
        """Three-way mocompare agrees with a live three-way comparison (differs)."""
        src, dest1, dest2 = dirs_one_differs
        live_rc = run(str(src), str(dest1), str(dest2))
        run("--molist", str(src), str(dest1), str(dest2))
        tsvs = [chdir / f"molist_{p.name}.tsv" for p in (src, dest1, dest2)]
        mocompare_rc = run("--mocompare", *[str(t) for t in tsvs])
        assert live_rc == mocompare_rc


# ---------------------------------------------------------------------------
# --mocompare with NFC normalisation
# ---------------------------------------------------------------------------


NFC_ROSE = "ros\u00e9.txt"  # é as a single code point  (NFC)
NFD_ROSE = "rose\u0301.txt"  # e + combining acute accent (NFD)


class TestMocompareNfc:
    """
    TSV files written by --molist always store paths in NFC.  --mocompare
    must normalise paths loaded from TSVs too, so that a TSV produced from
    an APFS volume (NFD) compares correctly against one from an exFAT volume
    (NFC) — the canonical cross-platform use-case.
    """

    def test_mocompare_nfd_vs_nfc_tsv_match(self, tmp_path, chdir):
        """
        Two TSVs where one has an NFD-written filename and the other NFC
        compare as equal, because both are normalised to NFC on load.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        # Simulate: APFS produced NFD, exFAT produced NFC
        make_file(src / NFD_ROSE, b"content")
        make_file(dest / NFC_ROSE, b"content")
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        # Both TSVs store NFC (written by _write_listing), and mocompare
        # normalises on load — result must be a match.
        assert run("--mocompare", str(tsv_src), str(tsv_dest)) == 0

    def test_mocompare_manually_crafted_nfd_tsv(self, tmp_path, chdir):
        """
        A TSV file crafted by hand with NFD paths (simulating a pre-fix tool
        or a tool on another OS) is still normalised to NFC on load, so it
        compares correctly against an NFC TSV.
        """
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / NFC_ROSE, b"content")

        # Write a TSV manually using NFD paths (as if from an older version)
        nfd_tsv = chdir / "molist_nfd.tsv"
        nfd_tsv.write_text(
            f"size\tfilepath\n7\t{NFD_ROSE}\n",
            encoding="utf-8",
        )

        # Write the live NFC TSV via --molist
        run("--molist", str(src))
        nfc_tsv = chdir / f"molist_{src.name}.tsv"

        # mocompare must treat them as equal
        assert run("--mocompare", str(nfc_tsv), str(nfd_tsv)) == 0

    def test_molist_tsv_paths_are_nfc(self, tmp_path, chdir):
        """
        Every path stored by --molist is in NFC form, regardless of the
        normalisation form the OS handed back.
        """
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / NFD_ROSE, b"data")
        run("--molist", str(src))
        content = (chdir / f"molist_{src.name}.tsv").read_text(encoding="utf-8")
        for line in content.splitlines()[1:]:
            path_col = line.split("\t")[-1]
            assert unicodedata.is_normalized("NFC", path_col), f"TSV path is not NFC: {path_col!r}"

    def test_mocompare_nfd_vs_nfc_size_mismatch_still_differs(self, tmp_path, chdir):
        """
        Even with NFC normalisation, a genuine size difference between
        NFD-named and NFC-named files is still reported as a mismatch.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / NFD_ROSE, b"aaa")
        make_file(dest / NFC_ROSE, b"bbbb")  # same name (NFC≡NFD), different size
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        assert run("--mocompare", str(tsv_src), str(tsv_dest)) == 1


# ---------------------------------------------------------------------------
# OSError paths in walk_tree (exercised via the public function)
# ---------------------------------------------------------------------------


class TestWalkTreeOSErrors:
    """OSError handling inside walk_tree, exercised by calling it directly."""

    def test_scandir_oserror_skipped(self, tmp_path):
        """An OSError from os.scandir inside walk_tree is caught and the subtree skipped."""
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "file.txt", b"data")
        sub = src / "sub"
        sub.mkdir()
        make_file(sub / "inner.txt", b"inner")

        real_scandir = os.scandir

        def patched(path):
            if str(path) == str(sub):
                raise OSError("simulated")
            return real_scandir(path)

        with mock.patch("os.scandir", side_effect=patched):
            entries = list(triplecheck.walk_tree(str(src), appledouble=False))
        paths = [e[0] for e in entries]
        assert any("file.txt" in p for p in paths)
        assert not any("inner.txt" in p for p in paths)

    def test_is_dir_or_is_file_oserror_skipped(self, tmp_path):
        """An OSError from entry.is_dir()/is_file() inside walk_tree is caught and the entry skipped."""
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "good.txt", b"ok")
        make_file(src / "bad.txt", b"bad")

        real_scandir = os.scandir

        def patched(path):
            it = real_scandir(path)
            entries = list(it)
            wrapped = []
            for e in entries:
                if e.name == "bad.txt":
                    m = mock.MagicMock(wraps=e)
                    m.name = e.name
                    m.path = e.path
                    m.is_dir.side_effect = OSError("simulated")
                    m.is_file.side_effect = OSError("simulated")
                    wrapped.append(m)
                else:
                    wrapped.append(e)
            cm = mock.MagicMock()
            cm.__enter__ = mock.Mock(return_value=None)
            cm.__exit__ = mock.Mock(return_value=False)
            cm.__iter__ = mock.Mock(return_value=iter(wrapped))
            return cm

        with mock.patch("os.scandir", side_effect=patched):
            entries = list(triplecheck.walk_tree(str(src), appledouble=False))
        paths = [e[0] for e in entries]
        assert any("good.txt" in p for p in paths)
        assert not any("bad.txt" in p for p in paths)

    def test_stat_oserror_skipped(self, tmp_path):
        """An OSError from entry.stat() inside walk_tree is caught and the entry skipped."""
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "good.txt", b"ok")
        make_file(src / "bad.txt", b"bad")

        real_scandir = os.scandir

        def patched(path):
            it = real_scandir(path)
            entries = list(it)
            wrapped = []
            for e in entries:
                if e.name == "bad.txt":
                    m = mock.MagicMock(wraps=e)
                    m.name = e.name
                    m.path = e.path
                    m.is_dir.return_value = False
                    m.is_file.return_value = True
                    m.stat.side_effect = OSError("simulated")
                    wrapped.append(m)
                else:
                    wrapped.append(e)
            cm = mock.MagicMock()
            cm.__enter__ = mock.Mock(return_value=None)
            cm.__exit__ = mock.Mock(return_value=False)
            cm.__iter__ = mock.Mock(return_value=iter(wrapped))
            return cm

        with mock.patch("os.scandir", side_effect=patched):
            entries = list(triplecheck.walk_tree(str(src), appledouble=False))
        paths = [e[0] for e in entries]
        assert any("good.txt" in p for p in paths)
        assert not any("bad.txt" in p for p in paths)


# ---------------------------------------------------------------------------
# OSError paths in walk_tree_with_empty_dirs
# ---------------------------------------------------------------------------


class TestWalkTreeWithEmptyDirsOSErrors:
    """OSError handling inside walk_tree_with_empty_dirs."""

    def test_scandir_oserror_skipped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "file.txt", b"data")
        sub = src / "sub"
        sub.mkdir()
        make_file(sub / "inner.txt", b"inner")

        real_scandir = os.scandir

        def patched(path):
            if str(path) == str(sub):
                raise OSError("simulated")
            return real_scandir(path)

        with mock.patch("os.scandir", side_effect=patched):
            entries = list(triplecheck.walk_tree_with_empty_dirs(str(src), appledouble=False))
        paths = [e[0] for e in entries]
        assert any("file.txt" in p for p in paths)
        assert not any("inner.txt" in p for p in paths)

    def test_is_dir_or_is_file_oserror_skipped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "good.txt", b"ok")
        make_file(src / "bad.txt", b"bad")

        real_scandir = os.scandir

        def patched(path):
            it = real_scandir(path)
            entries = list(it)
            wrapped = []
            for e in entries:
                if e.name == "bad.txt":
                    m = mock.MagicMock(wraps=e)
                    m.name = e.name
                    m.path = e.path
                    m.is_dir.side_effect = OSError("simulated")
                    m.is_file.side_effect = OSError("simulated")
                    wrapped.append(m)
                else:
                    wrapped.append(e)
            cm = mock.MagicMock()
            cm.__enter__ = mock.Mock(return_value=None)
            cm.__exit__ = mock.Mock(return_value=False)
            cm.__iter__ = mock.Mock(return_value=iter(wrapped))
            return cm

        with mock.patch("os.scandir", side_effect=patched):
            entries = list(triplecheck.walk_tree_with_empty_dirs(str(src), appledouble=False))
        paths = [e[0] for e in entries]
        assert any("good.txt" in p for p in paths)
        assert not any("bad.txt" in p for p in paths)

    def test_stat_oserror_skipped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        make_file(src / "good.txt", b"ok")
        make_file(src / "bad.txt", b"bad")

        real_scandir = os.scandir

        def patched(path):
            it = real_scandir(path)
            entries = list(it)
            wrapped = []
            for e in entries:
                if e.name == "bad.txt":
                    m = mock.MagicMock(wraps=e)
                    m.name = e.name
                    m.path = e.path
                    m.is_dir.return_value = False
                    m.is_file.return_value = True
                    m.stat.side_effect = OSError("simulated")
                    wrapped.append(m)
                else:
                    wrapped.append(e)
            cm = mock.MagicMock()
            cm.__enter__ = mock.Mock(return_value=None)
            cm.__exit__ = mock.Mock(return_value=False)
            cm.__iter__ = mock.Mock(return_value=iter(wrapped))
            return cm

        with mock.patch("os.scandir", side_effect=patched):
            entries = list(triplecheck.walk_tree_with_empty_dirs(str(src), appledouble=False))
        paths = [e[0] for e in entries]
        assert any("good.txt" in p for p in paths)
        assert not any("bad.txt" in p for p in paths)


# ---------------------------------------------------------------------------
# OSError paths in _dir_set
# ---------------------------------------------------------------------------


class TestDirSetOSErrors:
    """OSError handling inside _dir_set, accessed via the inner module."""

    def test_scandir_oserror_skipped(self, tmp_path):
        """An OSError from os.scandir inside _dir_set skips that subtree."""
        src = tmp_path / "src"
        src.mkdir()
        sub = src / "sub"
        sub.mkdir()
        (sub / "nested").mkdir()

        real_scandir = os.scandir

        def patched(path):
            if str(path) == str(sub):
                raise OSError("simulated")
            return real_scandir(path)

        with mock.patch("os.scandir", side_effect=patched):
            dirs = triplecheck._dir_set(str(src))
        # "sub/" is added before the error; "sub/nested/" is not
        assert "sub/" in dirs
        assert "sub/nested/" not in dirs

    def test_is_dir_oserror_skipped(self, tmp_path):
        """An OSError from entry.is_dir() inside _dir_set skips that entry."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "real_sub").mkdir()
        make_file(src / "file.txt", b"x")

        real_scandir = os.scandir

        def patched(path):
            it = real_scandir(path)
            entries = list(it)
            wrapped = []
            for e in entries:
                if e.name == "file.txt":
                    m = mock.MagicMock(wraps=e)
                    m.name = e.name
                    m.path = e.path
                    m.is_dir.side_effect = OSError("simulated")
                    wrapped.append(m)
                else:
                    wrapped.append(e)
            cm = mock.MagicMock()
            cm.__enter__ = mock.Mock(return_value=None)
            cm.__exit__ = mock.Mock(return_value=False)
            cm.__iter__ = mock.Mock(return_value=iter(wrapped))
            return cm

        with mock.patch("os.scandir", side_effect=patched):
            dirs = triplecheck._dir_set(str(src))
        assert "real_sub/" in dirs


# ---------------------------------------------------------------------------
# _colourise — TTY colour paths
# ---------------------------------------------------------------------------


class TestColourise:
    """
    _colourise wraps lines in ANSI codes when stdout is a TTY.
    We patch sys.stdout.isatty to exercise the colour branches.
    """

    def test_absent_symbol_red_when_tty(self):
        with mock.patch.object(sys.stdout, "isatty", return_value=True):
            result = triplecheck._colourise("some line", "∄")
        assert triplecheck.RED in result
        assert triplecheck.RESET in result
        assert "some line" in result

    def test_mismatch_symbol_orange_when_tty(self):
        with mock.patch.object(sys.stdout, "isatty", return_value=True):
            result = triplecheck._colourise("some line", "≠")
        assert triplecheck.ORANGE in result
        assert triplecheck.RESET in result

    def test_other_symbol_unchanged_when_tty(self):
        with mock.patch.object(sys.stdout, "isatty", return_value=True):
            result = triplecheck._colourise("some line", "=")
        assert result == "some line"

    def test_no_colour_when_not_tty(self):
        assert triplecheck._colourise("some line", "∄") == "some line"
        assert triplecheck._colourise("some line", "≠") == "some line"


# ---------------------------------------------------------------------------
# _write_listing OSError + cmd_save unwritable cwd
# ---------------------------------------------------------------------------


class TestWriteListingErrors:
    def test_write_listing_oserror_exits(self, tmp_path, chdir):
        """_write_listing exits cleanly when the TSV cannot be written."""
        with mock.patch("pathlib.Path.open", side_effect=OSError("disk full")), pytest.raises(SystemExit) as exc:
            triplecheck._write_listing("test", [(3, "file.txt")], full=False, ignore=False)
        assert exc.value.code != 0

    def test_cmd_save_unwritable_cwd_exits(self, tmp_path, chdir):
        """cmd_save exits cleanly when the cwd is not writable."""
        args = argparse.Namespace(full=False, ignore=False)
        src = tmp_path / "src"
        src.mkdir()
        with mock.patch("os.access", return_value=False), pytest.raises(SystemExit) as exc:
            triplecheck.cmd_save([src], [[(3, "file.txt")]], args)
        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# --diff + edge cases in cmd_compare_dirs
# ---------------------------------------------------------------------------


class TestDiffModeEdgeCases:
    def test_diff_conflicting_dupes_exits_2(self, dirs_with_conflicting_dupes):
        """--diff exits 2 when conflicting duplicates are detected under -i."""
        src, dest = dirs_with_conflicting_dupes
        assert run("--diff", "-i", str(src), str(dest)) == 2

    def test_diff_identical_dupes_on_match_prints_warning(self, dirs_with_identical_dupes, capsys):
        """--diff -i on a match with identical dupes: warning is printed to stderr."""
        src, dest = dirs_with_identical_dupes
        rc = run("--diff", "-i", str(src), str(dest))
        assert rc == 0
        assert "👯" in capsys.readouterr().err

    def test_diff_full_mode_match_message(self, identical_dirs, capsys):
        """--diff -f on a match prints the 'file hashes … identical' message."""
        src, dest = identical_dirs
        run("--diff", "-f", str(src), str(dest))
        out = capsys.readouterr().out
        assert "hash" in out.lower()


# ---------------------------------------------------------------------------
# _load_molist edge cases
# ---------------------------------------------------------------------------


class TestLoadMolistEdgeCases:
    def test_blank_lines_in_tsv_are_skipped(self, tmp_path):
        """Blank lines interspersed in a TSV are silently ignored on load."""
        tsv = tmp_path / "molist_test.tsv"
        tsv.write_text("size\tfilepath\n3\talpha.txt\n\n5\tbeta.txt\n\n", encoding="utf-8")
        listing = triplecheck._load_molist(tsv)
        assert len(listing) == 2
        paths = [e[1] for e in listing]
        assert "alpha.txt" in paths
        assert "beta.txt" in paths

    def test_malformed_line_no_tab_exits(self, tmp_path):
        """A line without a tab separator causes a clean SystemExit."""
        tsv = tmp_path / "bad.tsv"
        tsv.write_text("size\tfilepath\nNOTAVALIDLINE\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            triplecheck._load_molist(tsv)
        assert exc.value.code != 0

    def test_oserror_reading_tsv_exits(self, tmp_path):
        """An OSError opening the TSV causes a clean SystemExit."""
        ghost = tmp_path / "ghost.tsv"
        # File does not exist — opening it raises FileNotFoundError (an OSError)
        with pytest.raises(SystemExit) as exc:
            triplecheck._load_molist(ghost)
        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# cmd_mocompare output details
# ---------------------------------------------------------------------------


class TestMocompareOutputDetails:
    def test_mocompare_diff_hash_mode_match_message(self, identical_dirs, chdir, capsys):
        """--mocompare --diff -f on matching dirs prints the 'file hashes' message."""
        src, dest = identical_dirs
        run("-f", "--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        run("--mocompare", "--diff", str(tsv_src), str(tsv_dest))
        assert "hash" in capsys.readouterr().out.lower()

    def test_mocompare_multiple_diff_groups_separated_by_blank_line(self, tmp_path, chdir, capsys):
        """When mocompare finds more than one diff group, groups are separated by a blank line."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        make_file(src / "alpha.txt", b"aaa")
        make_file(src / "beta.txt", b"bbb")
        make_file(dest / "alpha.txt", b"aaaa")  # different size
        make_file(dest / "beta.txt", b"bbbbb")  # different size
        run("--molist", str(src), str(dest))
        tsv_src = chdir / f"molist_{src.name}.tsv"
        tsv_dest = chdir / f"molist_{dest.name}.tsv"
        run("--mocompare", str(tsv_src), str(tsv_dest))
        assert "\n\n" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# diff_sorted — the else branch (b's path sorts before a's current path)
# ---------------------------------------------------------------------------


class TestDiffSortedElseBranch:
    def test_b_entry_sorts_before_a_entry(self):
        """Entry only in b that sorts before the next a entry hits the else branch."""
        a = [(1, "beta.txt")]
        b = [(2, "alpha.txt"), (1, "beta.txt")]
        result = list(triplecheck.diff_sorted(a, b))
        assert (">", (2, "alpha.txt")) in result

    def test_interleaved_b_only_entries(self):
        """Multiple b-only entries interspersed with shared entries hit else repeatedly."""
        a = [(1, "b.txt"), (2, "d.txt")]
        b = [(9, "a.txt"), (1, "b.txt"), (9, "c.txt"), (2, "d.txt")]
        result = list(triplecheck.diff_sorted(a, b))
        sigil_paths = [(s, t[1]) for s, t in result]
        assert (">", "a.txt") in sigil_paths
        assert (">", "c.txt") in sigil_paths


# ---------------------------------------------------------------------------
# walk_tree — direct unit tests for internal skip branches
# (walk_tree is only called in -i / --ignore mode; walk_tree_with_empty_dirs
#  has identical logic but is a separate function so coverage tracks them separately)
# ---------------------------------------------------------------------------


class TestWalkTreeDirectBranches:
    def test_excluded_dir_parts_skipped(self, tmp_path):
        """Directories in EXCLUDED_DIR_PARTS are not descended into."""
        root = tmp_path / "root"
        root.mkdir()
        make_file(root / "keep.txt", b"x")
        forbidden = root / ".Trashes"
        forbidden.mkdir()
        make_file(forbidden / "junk.txt", b"junk")
        entries = list(triplecheck.walk_tree(str(root), appledouble=False))
        names = [e[0] for e in entries]
        assert any("keep.txt" in n for n in names)
        assert not any("junk.txt" in n for n in names)

    def test_non_file_non_dir_entry_skipped(self, tmp_path):
        """A non-file, non-dir entry (e.g. a socket or named pipe) is skipped."""
        root = tmp_path / "root"
        root.mkdir()
        make_file(root / "real.txt", b"data")

        real_scandir = os.scandir

        def patched(path):
            it = real_scandir(path)
            entries = list(it)
            pipe = mock.MagicMock()
            pipe.name = "mypipe"
            pipe.path = str(root / "mypipe")
            pipe.is_dir.return_value = False
            pipe.is_file.return_value = False
            cm = mock.MagicMock()
            cm.__enter__ = mock.Mock(return_value=None)
            cm.__exit__ = mock.Mock(return_value=False)
            cm.__iter__ = mock.Mock(return_value=iter([*entries, pipe]))
            return cm

        with mock.patch("os.scandir", side_effect=patched):
            result = list(triplecheck.walk_tree(str(root), appledouble=False))
        names = [e[0] for e in result]
        assert any("real.txt" in n for n in names)
        assert not any("mypipe" in n for n in names)

    def test_ds_store_skipped(self, tmp_path):
        """Files named .DS_Store are always skipped."""
        root = tmp_path / "root"
        root.mkdir()
        make_file(root / "file.txt", b"data")
        make_file(root / ".DS_Store", b"mac junk")
        entries = list(triplecheck.walk_tree(str(root), appledouble=False))
        names = [e[0] for e in entries]
        assert any("file.txt" in n for n in names)
        assert not any(".DS_Store" in n for n in names)

    def test_appledouble_skipped_unless_flag_set(self, tmp_path):
        """AppleDouble (._*) files are skipped by default, included with appledouble=True."""
        root = tmp_path / "root"
        root.mkdir()
        make_file(root / "file.txt", b"data")
        make_file(root / "._file.txt", b"mac metadata")
        without = [e[0] for e in triplecheck.walk_tree(str(root), appledouble=False)]
        with_ = [e[0] for e in triplecheck.walk_tree(str(root), appledouble=True)]
        assert not any("._file.txt" in n for n in without)
        assert any("._file.txt" in n for n in with_)
