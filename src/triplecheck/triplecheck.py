#!/usr/bin/env python3
"""
`triplecheck` is a two- and three-way file and directory comparison tool:
* For files it compares their hashes.
* For directories, it either compares the hashes of every file (full comparison mode),
 or compares file names and sizes (default). And it contains an optional `-i` flag to
 ignore folder structure and focus exclusively on files (useful if directories have
 been nested, moved around or renamed in one of your copies).

Examples:

Compare two files:

```bash
triplecheck "path/to/file1" "path/to/file2"
```

Compare two (or three) directories:

```bash
triplecheck "path/to/dir1" "path/to/dir2" "path/to/dir3"         # metadata-only comparison
triplecheck -f "path/to/dir1" "path/to/dir2"                     # full  comparison: hash every file
triplecheck -i "path/to/dir1" "path/to/dir2"                     # ignore folder structure
triplecheck -e "*.mhl" -e "*.txt" "path/to/dir1" "path/to/dir2"  # exclude .mhl and .txt files
```

Compare two (or three) directories on different machines:

```bash
triplecheck --molist "path/to/local/dir1"                           # creates "molist_dir1.tsv"
triplecheck --molist "path/to/remote/dir2"                          # creates "molist_dir2.tsv"
triplecheck --mocompare "molist_dir1.tsv" "molist_dir2.tsv"
```

Check that the destination contains all of the files from the source
```bash
triplecheck --diff "path/to/src" "path/to/dst" | grep "<"
```
"""
# Copyright (c) 2026 Luis Gómez Gutiérrez. License: MIT.

import argparse
import fnmatch
import importlib.metadata
import os
import sys
import unicodedata
from collections.abc import Generator, Iterator, Mapping, Sequence
from pathlib import Path

import blake3
import xxhash

# -----------------------------------------------------------------------------
# Version
# -----------------------------------------------------------------------------

try:
    __version__ = importlib.metadata.version("triplecheck")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
# A listing entry is (value, path) — value is either an int file size
# (metadata mode) or a hex digest string (full mode).
Entry = tuple[int, str] | tuple[str, str]
# A listing is a sorted sequence of Entry tuples.
Listing = list[tuple[int, str]] | list[tuple[str, str]]
# A diff group is one Entry (or None if absent) per compared tree.
Group = Sequence[Entry | None]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EXCLUDED_NAMES = frozenset(
    {
        ".DS_Store",
    }
)

EXCLUDED_DIR_PARTS = frozenset(
    {
        ".Trashes",
        ".Spotlight-V100",
        ".fseventsd",
        ".DocumentRevisions-V100",
    }
)

ALGORITHM_ALIASES = {
    "xxh64": "xxh64",
    "xxhash64": "xxh64",
    "xxhash64be": "xxh64",
    "xxh128": "xxh128",
    "xxhash128": "xxh128",
    "blake3": "blake3",
}

# Sigils and their labels, indexed by argument position.
SIGILS = ["<", ">", ">>"]
LABELS = ["source", "dest1", "dest2"]

# Numeric limits used in CLI validation and TSV parsing.
_TWO_WAY = 2  # --diff is only defined for two-way comparisons
_MIN_PATHS = 2  # minimum number of paths for a comparison
_MAX_PATHS = 3  # maximum number of paths for a comparison
_TSV_COLS = 2  # every molist TSV row has exactly 2 tab-separated columns


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------
def normalise_algorithm(algo: str) -> str:
    result = ALGORITHM_ALIASES.get(algo.lower())
    if result is None:
        sys.exit(f"error: unknown algorithm '{algo}'. Choose from xxh64, xxh128, or blake3.")
    return result


# ---------------------------------------------------------------------------
# Unicode normalisation
# ---------------------------------------------------------------------------
def _nfc(s: str) -> str:
    """Return the NFC form of *s*.

    HFS+ (Mac OS Extended) stores filenames in a Modified NFD, while APFS
    exFAT (and most other filesystems) are normalisation-preserving (they
    can store files in NFC or NFD).  Without normalisation, the visually
    identical string "café.txt" can appear as two different byte sequences
    — U+0065 U+0301 on a Mac source and U+00E9 a exFAT backup —
    causing spurious diff results.  Normalising every relative path to NFC
    before comparison or sorting eliminates the false positives.
    """
    return unicodedata.normalize("NFC", s)


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------
_CHUNK = 1 << 20  # 1 MiB


def hash_file(path: str, algo: str) -> str:
    """Hash a file and return the hex digest."""
    if algo == "blake3":
        bh = blake3.blake3()
        with Path(path).open("rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                bh.update(chunk)
        return bh.hexdigest()
    xh = xxhash.xxh128() if algo == "xxh128" else xxhash.xxh64()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            xh.update(chunk)
    return xh.hexdigest()


# ---------------------------------------------------------------------------
# Walking a directory tree
# ---------------------------------------------------------------------------
def walk_tree(
    root: str,
    appledouble: bool,
    ignore_files: list[str] | None = None,
) -> Iterator[tuple[str, int, str]]:
    """
    Yields (relative_path, size_in_bytes, full_path) for every regular file.
    If `ignore_files` is given, files matching any fnmatch pattern are skipped.
    """
    root_len = len(root) + 1
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except OSError:
            continue
        with it:
            entries = list(it)
        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if name in EXCLUDED_DIR_PARTS:
                        continue
                    stack.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if name in EXCLUDED_NAMES:
                continue
            if not appledouble and name.startswith("._"):
                continue
            if ignore_files and any(fnmatch.fnmatch(name, pat) for pat in ignore_files):
                continue
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            yield _nfc(entry.path[root_len:]), size, entry.path


def walk_tree_with_empty_dirs(
    root: str,
    appledouble: bool,
    ignore_files: list[str] | None = None,
) -> Iterator[tuple[str, int, str]]:
    """
    Like walk_tree, but also yields (relative_path + '/', -1, full_path)
    for empty directories. If `ignore_files` is given, matching files are skipped.
    """
    root_len = len(root) + 1
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except OSError:
            continue
        with it:
            entries = list(it)
        eligible_children = False
        subdirs = []
        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if name in EXCLUDED_DIR_PARTS:
                        continue
                    subdirs.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if name in EXCLUDED_NAMES:
                continue
            if not appledouble and name.startswith("._"):
                continue
            if ignore_files and any(fnmatch.fnmatch(name, pat) for pat in ignore_files):
                continue
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            eligible_children = True
            yield _nfc(entry.path[root_len:]), size, entry.path
        if current != root and not eligible_children and not subdirs:
            yield _nfc(current[root_len:]) + "/", -1, current
        stack.extend(subdirs)


# ---------------------------------------------------------------------------
# Building sorted listings of a directory
# ---------------------------------------------------------------------------
def _dir_set(root: str) -> set[str]:
    """
    Return the set of relative paths (with trailing '/') for every
    non-excluded subdirectory under `root`.  Used to suppress empty-dir
    markers that exist in at least one other tree.
    """
    root_len = len(root) + 1
    dirs: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except OSError:
            continue
        with it:
            entries = list(it)
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in EXCLUDED_DIR_PARTS:
                        continue
                    dirs.add(_nfc(entry.path[root_len:]) + "/")
                    stack.append(entry.path)
            except OSError:
                continue
    return dirs


def _detect_duplicates(seen: Mapping[str, list[int] | list[str]]) -> tuple[list[str], list[str]]:
    identical_dupes: list[str] = []
    conflicting_dupes: list[str] = []
    for name, values in seen.items():
        if len(values) > 1:
            if len(set(values)) == 1:
                identical_dupes.append(name)
            else:
                conflicting_dupes.append(name)
    return sorted(identical_dupes), sorted(conflicting_dupes)


def list_metadata(
    root: str,
    ignore: bool,
    appledouble: bool,
    ignore_files: list[str] | None = None,
    other_dirs: set[str] | None = None,
) -> tuple[Listing, list[str], list[str]]:
    """
    Returns (listing, identical_dupes, conflicting_dupes).
    listing: sorted list of (size, path_or_name) tuples.
    If `other_dirs` is given, empty-dir markers are suppressed for any
    directory whose relative path appears in that set.
    """
    if ignore:
        seen: dict[str, list[int]] = {}
        for rel, size, _full in walk_tree(root, appledouble, ignore_files):
            seen.setdefault(Path(rel).name, []).append(size)
        identical_dupes, conflicting_dupes = _detect_duplicates(seen)
        conflict_set = set(conflicting_dupes)
        result = [(values[-1], name) for name, values in seen.items() if name not in conflict_set]
        return sorted(result, key=lambda e: e[1]), identical_dupes, conflicting_dupes

    suppress = other_dirs or set()
    out = [
        (size, rel)
        for rel, size, _full in walk_tree_with_empty_dirs(root, appledouble, ignore_files)
        if size != -1 or rel not in suppress
    ]
    out.sort(key=lambda e: e[1])
    return out, [], []


def list_full(  # noqa: PLR0913
    root: str,
    algo: str,
    appledouble: bool,
    ignore: bool,
    ignore_files: list[str] | None = None,
    other_dirs: set[str] | None = None,
) -> tuple[Listing, list[str], list[str]]:
    """
    Returns (listing, identical_dupes, conflicting_dupes).
    listing: sorted list of (hex_digest, name_or_path) tuples.
    If `other_dirs` is given, empty-dir markers are suppressed for any
    directory whose relative path appears in that set.
    """
    if ignore:
        seen: dict[str, list[str]] = {}
        for rel, _size, full in walk_tree(root, appledouble, ignore_files):
            seen.setdefault(Path(rel).name, []).append(hash_file(full, algo))
        identical_dupes, conflicting_dupes = _detect_duplicates(seen)
        conflict_set = set(conflicting_dupes)
        result = [(values[-1], name) for name, values in seen.items() if name not in conflict_set]
        return sorted(result, key=lambda e: e[1]), identical_dupes, conflicting_dupes

    suppress = other_dirs or set()
    results = [
        (hash_file(full, algo) if size != -1 else "", rel)
        for rel, size, full in walk_tree_with_empty_dirs(root, appledouble, ignore_files)
        if size != -1 or rel not in suppress
    ]
    results.sort(key=lambda e: e[1])
    return results, [], []


# ---------------------------------------------------------------------------
# Three-way diff
# ---------------------------------------------------------------------------
def diff_three(listings: list[Listing]) -> Generator[Group, None, None]:
    """
    N-way sorted merge diff (N = 2 or 3).

    Each listing is a sorted list of (value, path) tuples. Yields one group
    per unique path that differs across listings: a list of N entries, each
    either (value, path) or None if that path is absent from that listing.
    """
    n = len(listings)
    indices = [0] * n
    lengths = [len(lst) for lst in listings]

    while True:
        current_paths = [listings[i][indices[i]][1] if indices[i] < lengths[i] else None for i in range(n)]
        active = [p for p in current_paths if p is not None]
        if not active:
            break

        min_path = min(active)

        group: list[Entry | None] = []
        for i in range(n):
            if current_paths[i] == min_path:
                group.append(listings[i][indices[i]])
                indices[i] += 1
            else:
                group.append(None)  # missing from this listing

        # Only yield groups where something actually differs.
        present = [e for e in group if e is not None]
        if len(present) < n or len({e[0] for e in present}) > 1:
            yield group


# ---------------------------------------------------------------------------
# Two-way diff (--diff mode, ported from lookback)
# ---------------------------------------------------------------------------
def diff_sorted(a: Listing, b: Listing) -> Iterator[tuple[str, Entry]]:
    """
    Linear merge of two sorted listings.  Yields (sign, tuple) pairs where
    sign is '<' (only in a) or '>' (only in b), or both when present but
    differing.
    """
    ia = ib = 0
    la, lb = len(a), len(b)
    while ia < la and ib < lb:
        ka, kb = a[ia][1], b[ib][1]
        if ka == kb:
            if a[ia] != b[ib]:
                yield "<", a[ia]
                yield ">", b[ib]
            ia += 1
            ib += 1
        elif ka < kb:
            yield "<", a[ia]
            ia += 1
        else:
            yield ">", b[ib]
            ib += 1
    while ia < la:
        yield "<", a[ia]
        ia += 1
    while ib < lb:
        yield ">", b[ib]
        ib += 1


def render_diff(a: Listing, b: Listing) -> int:
    """
    Print lookback-style diff output and return 0 (match) or 1 (differs).
    Only valid for 2-way comparisons.
    """
    diffs = list(diff_sorted(a, b))
    if not diffs:
        return 0
    write = sys.stdout.write
    for sign, tup in diffs:
        write(f"{sign} {tup[1]}\n")
    return 1


# ---------------------------------------------------------------------------
# Rendering a diff group as a triad
# ---------------------------------------------------------------------------
RED = "\033[31m"
ORANGE = "\033[38;5;208m"
RESET = "\033[0m"


def _colourise(line: str, symbol: str) -> str:
    """Wrap line in an ANSI colour based on its symbol, when stdout is a TTY."""
    if sys.stdout.isatty():
        if symbol == "∄":
            return f"{RED}{line}{RESET}"
        if symbol == "≠":
            return f"{ORANGE}{line}{RESET}"
    return line


def _symbol(entry: Entry | None, group: Group) -> str:
    """
    Return the comparison symbol for one entry within a group.

      =   present and matches at least one other present entry
      ≠   present but doesn't match the other present entries
      ∃   present (single instance)
      ∄   missing
    """
    if entry is None:
        return "∄"
    present_values = [e[0] for e in group if e is not None]
    if len(present_values) == 1:
        return "∃"
    matches_another = sum(1 for v in present_values if v == entry[0]) > 1
    return "=" if matches_another else "≠"


def render_group(group: Group) -> str:
    """
    Render one diff group as a triad of lines, e.g.:

        <  = photos/img_001.jpg
        >  = photos/img_001.jpg
        >> ∄ photos/img_001.jpg

    Lines with ∄ are coloured red; lines with ≠ are coloured yellow.
    Colour is suppressed when stdout is not a TTY.
    """
    display_path = next(e[1] for e in group if e is not None)
    lines = []
    for i, entry in enumerate(group):
        sigil = SIGILS[i]
        symbol = _symbol(entry, group)
        line = f"{sigil:<2} {symbol} {display_path}"
        lines.append(_colourise(line, symbol))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save listings to TSV
# ---------------------------------------------------------------------------
def _write_listing(name: str, listing: Listing, full: bool, ignore: bool) -> None:
    out = Path.cwd() / f"molist_{name}.tsv"
    col_header = "hash" if full else "size"
    path_header = "filename" if ignore else "filepath"
    try:
        with out.open("w", encoding="utf-8") as f:
            f.write(f"{col_header}\t{path_header}\n")
            f.writelines(f"{tup[0]}\t{_nfc(str(tup[1])).replace(os.sep, '/')}\n" for tup in listing)
        print(f"Listing saved to {out}")
    except OSError as e:
        sys.exit(f"error: could not write to current directory: {e}")


def cmd_save(paths: list[Path], listings: list[Listing], args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    if not os.access(cwd, os.W_OK):
        sys.exit(f"error: current directory is not writable: {cwd}")
    for path, listing in zip(paths, listings, strict=True):
        _write_listing(path.name, listing, args.full, args.ignore)
    return 0


# ---------------------------------------------------------------------------
# Duplicate warnings
# ---------------------------------------------------------------------------
def _print_dupe_warnings(
    label: str,
    identical: list[str],
    conflicting: list[str],
    full: bool,
) -> None:
    if conflicting:
        unit = "hashes" if full else "sizes"
        for name in conflicting:
            print(
                f"  ⚠️  {name} found multiple times in {label} with different {unit} — skipped",
                file=sys.stderr,
            )
    if identical:
        names = ", ".join(identical)
        print(
            f"  👯 Duplicate files in {label} (identical): {names}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------
def cmd_compare_files(paths: list[Path], algo: str) -> int:
    """Two- or three-way file hash comparison using triad rendering."""
    hashes = [hash_file(str(p), algo) for p in paths]
    names = [p.name for p in paths]

    if len(set(hashes)) == 1:
        quoted = " and ".join(f'"{n}"' for n in names)
        print(f"\n🎉 It's a match! File hashes from {quoted} are identical.\n")
        return 0

    # All names the same (e.g. two files called "photo.jpg" in different dirs):
    # show just the name.  Different names: show them slash-separated as the key
    # so the user knows which file is which.
    key = names[0] if len(set(names)) == 1 else " / ".join(names)
    group = [(h, key) for h in hashes]
    print()
    print(render_group(group))
    print()
    return 1


def _render_diff_mode(
    listings: list[Listing],
    paths: list[Path],
    all_ident: list[list[str]],
    all_conflict: list[list[str]],
    args: argparse.Namespace,
) -> int:
    """Render --diff output for a two-way comparison."""
    if len(paths) != _TWO_WAY:
        sys.exit("error: --diff only supports 2-way comparison.")
    for i, _p in enumerate(paths):
        _print_dupe_warnings(LABELS[i], all_ident[i], all_conflict[i], args.full)
    if any(c for c in all_conflict):
        print("\n🛑 Comparison incomplete due to conflicting duplicates (see warnings above).\n")
        return 2
    src, dest = paths
    rc = render_diff(listings[0], listings[1])
    if rc == 0:
        has_ident_dupes = any(d for d in all_ident)
        if has_ident_dupes:
            all_names = sorted({n for d in all_ident for n in d})
            print(
                f"  👯 Duplicate files were found ({', '.join(all_names)}) but...",
                file=sys.stderr,
            )
        if args.full:
            print(f'\n🎉 It\'s a match! File hashes from "{src.name}" and "{dest.name}" are identical.\n')
        else:
            print(f'\n🎉 It\'s a match! File names and sizes from "{src.name}" and "{dest.name}" are matching.\n')
    return rc


def _render_triad_mode(
    listings: list[Listing],
    paths: list[Path],
    all_ident: list[list[str]],
    all_conflict: list[list[str]],
    args: argparse.Namespace,
) -> int:
    """Render triad (non-diff) output for a two- or three-way comparison."""
    for i, _p in enumerate(paths):
        _print_dupe_warnings(LABELS[i], all_ident[i], all_conflict[i], args.full)

    if any(c for c in all_conflict):
        print("\n🛑 Comparison incomplete due to conflicting duplicates (see warnings above).\n")
        return 2

    groups = list(diff_three(listings))
    has_ident_dupes = any(d for d in all_ident)

    if not groups:
        if has_ident_dupes:
            all_names = sorted({n for d in all_ident for n in d})
            print(
                f"  👯 Duplicate files were found ({', '.join(all_names)}) but...",
                file=sys.stderr,
            )
        names = " and ".join(f'"{p.name}"' for p in paths)
        if args.full:
            print(f"\n🎉 It's a match! File hashes from {names} are identical.\n")
        else:
            print(f"\n🎉 It's a match! File names and sizes from {names} are matching.\n")
        return 0

    write = sys.stdout.write
    for i, group in enumerate(groups):
        write(render_group(group) + "\n")
        if i < len(groups) - 1:
            write("\n")
    return 1


def cmd_compare_dirs(paths: list[Path], args: argparse.Namespace) -> int:
    """Two- or three-way directory comparison."""
    ignore_files = args.exclude or None

    # Pre-compute dir sets for each root so each listing can suppress
    # empty-dir markers for directories that exist in any other tree.
    dir_sets = [_dir_set(str(p)) for p in paths]

    listings: list[Listing] = []
    all_ident: list[list[str]] = []
    all_conflict: list[list[str]] = []

    for i, p in enumerate(paths):
        other_dirs = set().union(*(dir_sets[j] for j in range(len(paths)) if j != i))
        if args.full:
            lst, ident, conflict = list_full(
                str(p), args.algorithm, args.appledouble, args.ignore, ignore_files, other_dirs
            )
        else:
            lst, ident, conflict = list_metadata(str(p), args.ignore, args.appledouble, ignore_files, other_dirs)
        listings.append(lst)
        all_ident.append(ident)
        all_conflict.append(conflict)

    if args.molist:
        return cmd_save(paths, listings, args)

    if args.diff:
        return _render_diff_mode(listings, paths, all_ident, all_conflict, args)

    return _render_triad_mode(listings, paths, all_ident, all_conflict, args)


# ---------------------------------------------------------------------------
# Compare saved molist TSV files
# ---------------------------------------------------------------------------
def _load_molist(path: Path) -> Listing:
    """
    Load a molist TSV produced by --molist.
    Returns a sorted list of (value, filepath) tuples where value is either
    an int (size) or a str (hash), matching the format of live listings.
    Paths are NFC-normalised on load so that TSVs produced before the NFC
    fix (or on a different OS) compare correctly against NFC-normalised
    live listings.
    """
    # Collect raw (val_str, filepath) rows first, then convert to the right
    # typed list so the return type matches Listing without a cast.
    rows: list[tuple[str, str]] = []
    is_hash: bool
    try:
        with path.open(encoding="utf-8") as f:
            header = f.readline().strip().split("\t")
            if len(header) < _TSV_COLS or header[0] not in ("hash", "size"):
                sys.exit(
                    f"error: '{path}' doesn't look like a molist TSV (expected 'hash' or 'size' as the first column)."
                )
            is_hash = header[0] == "hash"
            for lineno, raw_line in enumerate(f, start=2):
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) != _TSV_COLS:
                    sys.exit(f"error: malformed line {lineno} in '{path}': {line!r}")
                raw_val, filepath = parts
                rows.append((raw_val, _nfc(filepath)))
    except OSError as e:
        sys.exit(f"error: cannot read '{path}': {e}")
    rows.sort(key=lambda e: e[1])
    if is_hash:
        str_listing: list[tuple[str, str]] = [(v, p) for v, p in rows]
        return str_listing
    int_listing: list[tuple[int, str]] = [(int(v), p) for v, p in rows]
    return int_listing


def cmd_mocompare(paths: list[Path], args: argparse.Namespace) -> int:
    """Compare two or three molist TSV files using the same diff machinery."""
    listings: list[Listing] = [_load_molist(p) for p in paths]

    # Infer full/size mode from the first file's header to decide wording.
    with paths[0].open(encoding="utf-8") as f:
        first_col = f.readline().strip().split("\t")[0]
    is_hash = first_col == "hash"

    if args.diff:
        if len(paths) != _TWO_WAY:
            sys.exit("error: --diff only supports 2-way comparison.")
        rc = render_diff(listings[0], listings[1])
        if rc == 0:
            names = f'"{paths[0].stem}" and "{paths[1].stem}"'
            if is_hash:
                print(f"\n🎉 It's a match! File hashes from {names} are identical.\n")
            else:
                print(f"\n🎉 It's a match! File names and sizes from {names} are matching.\n")
        return rc

    groups = list(diff_three(listings))
    if not groups:
        names = " and ".join(f'"{p.stem}"' for p in paths)
        if is_hash:
            print(f"\n🎉 It's a match! File hashes from {names} are identical.\n")
        else:
            print(f"\n🎉 It's a match! File names and sizes from {names} are matching.\n")
        return 0

    write = sys.stdout.write
    for i, group in enumerate(groups):
        write(render_group(group) + "\n")
        if i < len(groups) - 1:
            write("\n")
    return 1


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------
def _dispatch_mocompare(resolved: list[Path], args: argparse.Namespace) -> int:
    """Validate TSV paths and delegate to cmd_mocompare."""
    for rp in resolved:
        if not rp.is_file():
            sys.exit(f"error: '{rp}' is not a file. --mocompare expects molist TSV paths.")
    return cmd_mocompare(resolved, args)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Two- or three-way comparison tool for files and directories",
    )

    p.add_argument("paths", nargs="*", metavar="path", help="two or three files or directories to compare")
    p.add_argument(
        "-i",
        "--ignore",
        action="store_true",
        help="ignore folder structure (compare flat list of file names and sizes)",
    )
    p.add_argument(
        "-e",
        "--exclude",
        action="append",
        metavar="PATTERN",
        default=[],
        help="exclude files whose names match PATTERN",
    )
    p.add_argument("-f", "--full", action="store_true", help="full directory comparison: hash every file (slower)")
    p.add_argument(
        "-a", "--algorithm", default="xxh64", metavar="[xxh64|xxh128|blake3]", help="hash algorithm (default: xxh64)"
    )
    p.add_argument("-X", "--appledouble", action="store_true", help="include AppleDouble (._*) files")
    p.add_argument("--diff", action="store_true", help="classic diff-style output (2-way comparison only)")
    p.add_argument("--molist", action="store_true", help="save TSV listing(s) to the current directory")
    p.add_argument("--mocompare", action="store_true", help="compare two or three molist TSV files saved by --molist")
    p.add_argument("--version", action="version", version=__version__)

    raw_argv = list(argv if argv is not None else sys.argv[1:])

    if not raw_argv:
        p.print_help()
        return 1

    args = p.parse_args(raw_argv)
    args.algorithm = normalise_algorithm(args.algorithm)

    # `triplecheck --molist` with no paths → default to cwd.
    if args.molist and not args.paths:
        raw_argv.append(str(Path.cwd()))
        args = p.parse_args(raw_argv)
        args.algorithm = normalise_algorithm(args.algorithm)

    raw_paths = args.paths

    # Single-path invocation: only valid with --molist.
    if len(raw_paths) == 1:
        if not args.molist:
            sys.exit(
                "error: at least two paths are required for comparison. "
                "Use --molist to save a listing from a single path."
            )
        p_resolved = Path(raw_paths[0]).resolve()
        if not p_resolved.is_dir():
            sys.exit("error: source must be a directory when using --molist with a single path.")
        ignore_files = args.exclude or None
        lst, _, _ = (
            list_full(str(p_resolved), args.algorithm, args.appledouble, args.ignore, ignore_files)
            if args.full
            else list_metadata(str(p_resolved), args.ignore, args.appledouble, ignore_files)
        )
        return cmd_save([p_resolved], [lst], args)

    if len(raw_paths) < _MIN_PATHS or len(raw_paths) > _MAX_PATHS:
        sys.exit("error: provide two or three paths to compare (or one with --molist).")

    resolved = [Path(rp).resolve() for rp in raw_paths]

    if args.mocompare:
        return _dispatch_mocompare(resolved, args)

    if len(set(resolved)) != len(resolved):
        sys.exit("error: all paths must be different.")

    are_files = [p.is_file() for p in resolved]
    are_dirs = [p.is_dir() for p in resolved]

    if all(are_files):
        return cmd_compare_files(resolved, args.algorithm)

    if all(are_dirs):
        return cmd_compare_dirs(resolved, args)

    sys.exit("error: all paths must be of the same type (all files or all directories).")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
