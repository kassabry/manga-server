"""
fix_manhuato_titles.py — Remove trailing type labels from ManhuaTo CBZ filenames
and series directories.

ManhuaTo started appending "Manhwa", "Manhua", "Manga", or "Comics" to series
titles in listing-page alt text, producing filenames like:

    [Manhuato] Return Of The Mad Demon Manhwa - Chapter 188.cbz

when previously the same series was stored as:

    [Manhuato] Return Of The Mad Demon - Chapter 188.cbz

This mismatch causes the scraper to treat every chapter as missing and
re-download everything.  This script:

  1. Finds every series directory under the library root whose name ends with
     one of the type labels (case-insensitive).
  2. Renames the CBZ files inside (strips the suffix from filenames).
  3. Updates the <Series> field in ComicInfo.xml inside each CBZ.
  4. Renames the directory itself.

Usage:
    python fix_manhuato_titles.py --library /path/to/library   (dry-run)
    python fix_manhuato_titles.py --library /path/to/library --apply
"""

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

# Labels that ManhuaTo appends to series titles.
_SUFFIX_RE = re.compile(r'\s+\b(Manhwa|Manhua|Manga|Comics)\b\s*$', re.IGNORECASE)


def strip_suffix(name: str) -> str:
    return _SUFFIX_RE.sub('', name).strip()


def needs_fix(name: str) -> bool:
    return bool(_SUFFIX_RE.search(name))


def update_comic_info(cbz_path: Path, old_series: str, new_series: str, apply: bool) -> bool:
    """Rewrite the <Series> tag in ComicInfo.xml inside a CBZ.

    Returns True if a change was made (or would be made in dry-run).
    """
    try:
        with zipfile.ZipFile(cbz_path, 'r') as zin:
            names = zin.namelist()
            if 'ComicInfo.xml' not in names:
                return False
            xml_bytes = zin.read('ComicInfo.xml')

        xml_text = xml_bytes.decode('utf-8', errors='replace')
        # Match <Series>...</Series> and replace the content
        new_xml, count = re.subn(
            r'(<Series>)' + re.escape(old_series) + r'(</Series>)',
            r'\g<1>' + new_series + r'\2',
            xml_text,
        )
        if count == 0:
            return False

        if not apply:
            return True

        # Rewrite the ZIP in-place: read all files, write new archive
        buf = io.BytesIO()
        with zipfile.ZipFile(cbz_path, 'r') as zin:
            with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    if item.filename == 'ComicInfo.xml':
                        zout.writestr(item, new_xml.encode('utf-8'))
                    else:
                        zout.writestr(item, zin.read(item.filename))

        cbz_path.write_bytes(buf.getvalue())
        return True

    except Exception as exc:
        print(f"    WARNING: could not update ComicInfo.xml in {cbz_path.name}: {exc}")
        return False


def process_directory(series_dir: Path, apply: bool) -> int:
    """Rename CBZ files and update ComicInfo.xml inside a series directory.

    Returns the number of files renamed.
    """
    dir_name = series_dir.name          # e.g. "[Manhuato] Return Of The Mad Demon Manhwa"
    new_dir_name = strip_suffix(dir_name)  # "[Manhuato] Return Of The Mad Demon"

    renamed = 0
    for cbz in sorted(series_dir.glob('*.cbz')):
        stem = cbz.stem   # e.g. "[Manhuato] Return Of The Mad Demon Manhwa - Chapter 188"
        if not needs_fix(stem):
            continue

        new_stem = strip_suffix(stem)
        new_cbz = cbz.with_name(new_stem + '.cbz')

        # Work out the bare series title parts for ComicInfo.xml
        # The <Series> field in ComicInfo.xml is the display_title, which
        # includes the "[Manhuato]" prefix.
        print(f"  {'RENAME' if apply else 'WOULD RENAME'}: {cbz.name}")
        print(f"        → {new_cbz.name}")

        xml_changed = update_comic_info(cbz, dir_name, new_dir_name, apply)
        if xml_changed:
            print(f"    {'UPDATED' if apply else 'WOULD UPDATE'} ComicInfo.xml <Series>")

        if apply:
            cbz.rename(new_cbz)
        renamed += 1

    return renamed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--library', required=True,
                        help='Root library directory to scan (e.g. /mnt/manga-storage/library)')
    parser.add_argument('--apply', action='store_true',
                        help='Actually rename files (default is dry-run)')
    args = parser.parse_args()

    library = Path(args.library)
    if not library.is_dir():
        print(f"ERROR: {library} is not a directory", file=sys.stderr)
        sys.exit(1)

    apply = args.apply
    mode = 'APPLY' if apply else 'DRY-RUN'
    print(f"\n=== fix_manhuato_titles.py [{mode}] ===")
    print(f"Library: {library}\n")

    total_dirs = 0
    total_files = 0

    # Walk one level of subdirectories under the library root.
    # Library structure: library/<Category>/<SeriesDir>/chapter.cbz
    # or flat:           library/<SeriesDir>/chapter.cbz
    # We search two levels deep to handle both.
    candidates = []
    for entry in library.rglob('*.cbz'):
        series_dir = entry.parent
        if series_dir not in candidates and needs_fix(series_dir.name):
            candidates.append(series_dir)

    if not candidates:
        print("No series directories with type-label suffixes found.")
        return

    for series_dir in sorted(candidates):
        dir_name = series_dir.name
        new_dir_name = strip_suffix(dir_name)
        print(f"Series: {dir_name}")
        print(f"  → {new_dir_name}")

        renamed = process_directory(series_dir, apply)
        total_files += renamed

        # Rename the directory itself last (after files are renamed inside it)
        new_dir = series_dir.with_name(new_dir_name)
        if apply:
            if new_dir.exists():
                print(f"  WARNING: target directory already exists, skipping dir rename: {new_dir}")
            else:
                series_dir.rename(new_dir)
                print(f"  RENAMED dir → {new_dir_name}")
        else:
            print(f"  WOULD RENAME dir → {new_dir_name}")

        total_dirs += 1
        print()

    print(f"{'='*55}")
    print(f"Directories affected : {total_dirs}")
    print(f"CBZ files renamed    : {total_files}")
    if not apply:
        print("\nThis was a DRY-RUN. Re-run with --apply to make changes.")


if __name__ == '__main__':
    main()
