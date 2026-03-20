#!/usr/bin/env python3
"""
fix_manhuato_duplicates.py — Merge and rename duplicate [Manhuato] series directories.

Problem: ManhuaTo previously stored series under inconsistent names because:
  1. Titles came in different casings from listing vs detail pages
     ("Return Of The Mad Demon" vs "Return of the Mad Demon")
  2. Type suffixes (Manhwa/Manga/Manhua) were sometimes included before the fix

This script:
  1. Scans a library directory for [Manhuato] folders
  2. Groups folders by their canonical name (stripped suffix + Title Case)
  3. Merges duplicates into the canonical directory, renaming CBZ files as needed
  4. Renames any non-canonical directories to their canonical name
  5. Updates ComicInfo.xml series titles inside CBZs (optional, --update-xml)

Usage:
    # Dry run (see what would happen, no changes made):
    python fix_manhuato_duplicates.py /mnt/manga-storage/Manhua

    # Apply changes:
    python fix_manhuato_duplicates.py /mnt/manga-storage/Manhua --apply

    # Also update ComicInfo.xml inside each CBZ:
    python fix_manhuato_duplicates.py /mnt/manga-storage/Manhua --apply --update-xml

    # Scan all library subdirs at once:
    python fix_manhuato_duplicates.py /mnt/manga-storage --apply --recursive
"""

import argparse
import re
import sys
import zipfile
import io
from pathlib import Path


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_SUFFIX_RE = re.compile(r'\s+\b(Manhwa|Manhua|Manga|Comics)\b\s*$', re.IGNORECASE)
_PREFIX = "[Manhuato] "

# Words that stay lowercase in title case (unless they're the first word).
_MINOR_WORDS = frozenset({
    'a', 'an', 'the',
    'and', 'but', 'or', 'nor', 'for', 'so', 'yet',
    'as', 'at', 'by', 'in', 'of', 'on', 'to', 'up', 'via',
    'with', 'from', 'into', 'onto', 'upon',
})


def _title_case(text: str) -> str:
    """Title-case that skips minor words and never capitalises after apostrophes.

    Python's built-in str.title() has two problems:
      - "world's" → "World'S"  (capitalises the s after the apostrophe)
      - "and", "a", "the" → "And", "A", "The"  (capitalises minor words)
    This function fixes both while still capitalising the first word always.
    """
    words = text.split()
    result = []
    for i, word in enumerate(words):
        lower = word.lower()
        if i == 0 or lower not in _MINOR_WORDS:
            # Capitalise only the very first character; leave the rest as-is
            # so "world's" → "World's", not "World'S".
            result.append(word[0].upper() + word[1:] if word else word)
        else:
            result.append(lower)
    return ' '.join(result)


def _strip_suffix(title: str) -> str:
    return _SUFFIX_RE.sub('', title).strip()


def canonical_dir_name(dir_name: str) -> str:
    """Return the canonical directory name for a [Manhuato] folder."""
    if dir_name.startswith(_PREFIX):
        raw_title = dir_name[len(_PREFIX):]
    else:
        raw_title = dir_name
    return _PREFIX + _title_case(_strip_suffix(raw_title))


def canonical_cbz_name(cbz_stem: str) -> str | None:
    """
    cbz_stem e.g. '[Manhuato] Return of the Mad Demon Manhwa - Chapter 188'
    Returns canonical stem or None if it doesn't look like a ManhuaTo CBZ.
    """
    # Pattern: [Manhuato] <title> - Chapter <number>
    m = re.match(r'^(\[Manhuato\] .+?) - (Chapter .+)$', cbz_stem)
    if not m:
        return None
    old_prefix = m.group(1)   # e.g. "[Manhuato] Return of the Mad Demon Manhwa"
    chapter_part = m.group(2)  # e.g. "Chapter 188"
    canon_prefix = canonical_dir_name(old_prefix)  # applies suffix strip + title()
    return f"{canon_prefix} - {chapter_part}"


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def find_manhuato_dirs(root: Path) -> list[Path]:
    """Return all immediate child directories starting with [Manhuato]."""
    return sorted(
        d for d in root.iterdir()
        if d.is_dir() and d.name.startswith(_PREFIX)
    )


def update_comicinfo_in_cbz(cbz_path: Path, new_series_title: str, dry_run: bool) -> bool:
    """Rewrite the Series tag inside ComicInfo.xml within a CBZ. Returns True if changed."""
    try:
        with zipfile.ZipFile(cbz_path, 'r') as zin:
            names = zin.namelist()
            if 'ComicInfo.xml' not in names:
                return False
            old_xml = zin.read('ComicInfo.xml').decode('utf-8', errors='replace')

        new_xml = re.sub(
            r'<Series>[^<]*</Series>',
            f'<Series>{new_series_title}</Series>',
            old_xml,
        )
        if new_xml == old_xml:
            return False

        if dry_run:
            return True

        # Rewrite the zip with the updated ComicInfo.xml
        buf = io.BytesIO()
        with zipfile.ZipFile(cbz_path, 'r') as zin, zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == 'ComicInfo.xml':
                    zout.writestr(item, new_xml.encode('utf-8'))
                else:
                    zout.writestr(item, zin.read(item.filename))

        cbz_path.write_bytes(buf.getvalue())
        return True
    except Exception as e:
        print(f"    WARNING: could not update ComicInfo.xml in {cbz_path.name}: {e}")
        return False


def process_library_dir(lib_dir: Path, apply: bool, update_xml: bool) -> None:
    dirs = find_manhuato_dirs(lib_dir)
    if not dirs:
        print(f"  No [Manhuato] dirs found in {lib_dir}")
        return

    # Build canonical → [list of actual dirs] mapping
    groups: dict[str, list[Path]] = {}
    for d in dirs:
        canon = canonical_dir_name(d.name)
        groups.setdefault(canon, []).append(d)

    renamed = 0
    merged = 0
    skipped = 0

    for canon_name, dir_list in sorted(groups.items()):
        canon_dir = lib_dir / canon_name

        if len(dir_list) == 1 and dir_list[0].name == canon_name:
            # Already canonical, nothing to do
            continue

        if len(dir_list) == 1:
            # Single dir but wrong name — just rename it
            old_dir = dir_list[0]
            print(f"  RENAME  {old_dir.name!r}")
            print(f"       -> {canon_name!r}")
            if apply:
                old_dir.rename(canon_dir)
                # Rename CBZ files inside
                _rename_cbzs_in_dir(canon_dir, update_xml, apply)
            renamed += 1
            continue

        # Multiple dirs with the same canonical name — merge them
        print(f"\n  MERGE   {len(dir_list)} dirs -> {canon_name!r}")
        for d in dir_list:
            print(f"          src: {d.name!r}")

        # Determine which directory to treat as the target (prefer the one
        # already named canonically, else the one with the most CBZ files)
        target_dir: Path | None = None
        for d in dir_list:
            if d.name == canon_name:
                target_dir = d
                break
        if target_dir is None:
            target_dir = max(dir_list, key=lambda d: len(list(d.glob('*.cbz'))))

        if apply and not canon_dir.exists():
            canon_dir.mkdir(parents=True, exist_ok=True)

        for src_dir in dir_list:
            if src_dir == target_dir and src_dir.name == canon_name:
                # Rename CBZs inside canonical dir
                _rename_cbzs_in_dir(src_dir, update_xml, apply)
                continue

            cbz_files = list(src_dir.glob('*.cbz'))
            cover_files = [f for f in src_dir.iterdir() if f.stem.lower() == 'cover']

            for cbz in cbz_files:
                canon_stem = canonical_cbz_name(cbz.stem)
                new_name = f"{canon_stem}.cbz" if canon_stem else cbz.name
                dest = canon_dir / new_name

                if dest.exists():
                    # Destination already has this chapter — the source is a
                    # true duplicate. Delete it so the source dir becomes empty
                    # and can be removed.
                    print(f"    DELETE duplicate: {cbz.name}")
                    if apply:
                        cbz.unlink()
                    skipped += 1
                else:
                    print(f"    MOVE: {cbz.name} -> {new_name}")
                    if apply:
                        cbz.rename(dest)
                        if update_xml:
                            update_comicinfo_in_cbz(dest, canon_name[len(_PREFIX):], dry_run=False)
                    merged += 1

            # Move cover image if target doesn't have one
            for cover in cover_files:
                dest_cover = canon_dir / cover.name
                if not dest_cover.exists():
                    print(f"    MOVE cover: {cover.name}")
                    if apply:
                        cover.rename(dest_cover)

            # Remove old dir if now empty
            if apply:
                remaining = list(src_dir.iterdir())
                if not remaining:
                    src_dir.rmdir()
                    print(f"    REMOVED empty dir: {src_dir.name!r}")
                else:
                    print(f"    WARNING: {src_dir.name!r} not empty after merge ({len(remaining)} files remain)")

    summary = f"  Done: {renamed} renamed, {merged} CBZs moved, {skipped} skipped (already exist)"
    if not apply:
        summary += "  [DRY RUN — no changes made, use --apply to apply]"
    print(f"\n{summary}\n")


def _rename_cbzs_in_dir(directory: Path, update_xml: bool, apply: bool) -> None:
    """Rename CBZ files inside a directory to their canonical names."""
    for cbz in list(directory.glob('*.cbz')):
        canon_stem = canonical_cbz_name(cbz.stem)
        if canon_stem is None or canon_stem == cbz.stem:
            continue
        new_path = directory / f"{canon_stem}.cbz"
        if new_path.exists():
            print(f"    SKIP rename (exists): {canon_stem}.cbz")
            continue
        print(f"    RENAME CBZ: {cbz.name} -> {new_path.name}")
        if apply:
            cbz.rename(new_path)
            if update_xml:
                canon_title = canonical_dir_name(directory.name)[len(_PREFIX):]
                update_comicinfo_in_cbz(new_path, canon_title, dry_run=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge and rename duplicate [Manhuato] series directories."
    )
    parser.add_argument(
        "library_dir",
        help="Path to the library directory containing [Manhuato] folders "
             "(e.g. /mnt/manga-storage/Manhua)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rename/move files. Without this flag the script runs in dry-run mode.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan all immediate subdirectories of library_dir instead of library_dir itself.",
    )
    parser.add_argument(
        "--update-xml",
        action="store_true",
        help="Also update the <Series> tag inside ComicInfo.xml within each CBZ.",
    )
    args = parser.parse_args()

    root = Path(args.library_dir)
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== fix_manhuato_duplicates.py [{mode}] ===\n")

    if args.recursive:
        subdirs = [d for d in sorted(root.iterdir()) if d.is_dir()]
        for subdir in subdirs:
            has_manhuato = any(d.name.startswith(_PREFIX) for d in subdir.iterdir() if d.is_dir())
            if has_manhuato:
                print(f"--- {subdir} ---")
                process_library_dir(subdir, apply=args.apply, update_xml=args.update_xml)
    else:
        process_library_dir(root, apply=args.apply, update_xml=args.update_xml)


if __name__ == "__main__":
    main()
