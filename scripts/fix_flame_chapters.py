#!/usr/bin/env python3
"""
fix_flame_chapters.py — Fix FlameComics chapter numbering in downloaded CBZ files.

Problem: FlameComics chapter links render as e.g. "Chapter 1<span>3 years ago</span>"
which get_text(strip=True) concatenates to "Chapter 13 years ago", causing the scraper
to record chapter 1 as chapter 13, chapter 10 as chapter 103, etc.

This script:
  1. Finds all [Flame] series directories in the library
  2. Sorts CBZ files by current (wrong) chapter number
  3. Re-numbers them sequentially: 1, 2, 3 …
  4. Renames CBZ files on disk
  5. Patches ComicInfo.xml inside each CBZ
  6. Optionally updates chapter records in mangashelf.db

Usage:
  # Dry run — shows mapping but makes no changes
  python fix_flame_chapters.py --library /path/to/library

  # Apply — rename files + patch ComicInfo.xml
  python fix_flame_chapters.py --library /path/to/library --apply

  # Apply + update the database so the reader doesn't lose file paths
  python fix_flame_chapters.py --library /path/to/library --apply \\
      --db /path/to/mangashelf/data/mangashelf.db

  # Only fix one specific series
  python fix_flame_chapters.py --library /path/to/library --apply \\
      --series "Auto-Hunting"
"""

import argparse
import os
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_chapter_number(filename: str) -> float:
    """Extract the chapter number from a CBZ filename."""
    m = re.search(r'Chapter\s+(\d+(?:\.\d+)?)', filename, re.I)
    return float(m.group(1)) if m else 0.0


def replace_chapter_number_in_name(stem: str, new_num) -> str:
    """Return the filename stem with its chapter number replaced by new_num."""
    num_str = str(int(new_num)) if float(new_num).is_integer() else str(new_num)
    return re.sub(
        r'(Chapter\s+)\d+(?:\.\d+)?',
        lambda m: f"{m.group(1)}{num_str}",
        stem,
        flags=re.I,
    )


def patch_comic_info(cbz_path: Path, new_number: int, new_title: str) -> bool:
    """Rewrite ComicInfo.xml inside a CBZ with the corrected chapter number/title."""
    tmp = cbz_path.with_suffix('.cbz.tmp')
    try:
        with zipfile.ZipFile(cbz_path, 'r') as zin:
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
                for name in zin.namelist():
                    data = zin.read(name)
                    if name == 'ComicInfo.xml':
                        xml = data.decode('utf-8', errors='replace')
                        xml = re.sub(
                            r'<Number>[^<]*</Number>',
                            f'<Number>{new_number}</Number>',
                            xml,
                        )
                        xml = re.sub(
                            r'<Title>[^<]*</Title>',
                            f'<Title>{new_title}</Title>',
                            xml,
                        )
                        data = xml.encode('utf-8')
                    zout.writestr(name, data)
        cbz_path.unlink()
        tmp.rename(cbz_path)
        return True
    except Exception as e:
        print(f"    ERROR patching ComicInfo.xml in {cbz_path.name}: {e}")
        if tmp.exists():
            tmp.unlink()
        return False


def find_flame_dirs(library_path: Path):
    """Return all series directories that contain Flame Comics CBZ files."""
    flame_dirs = []
    for type_dir in sorted(library_path.iterdir()):
        if not type_dir.is_dir():
            continue
        for series_dir in sorted(type_dir.iterdir()):
            if not series_dir.is_dir():
                continue
            cbzs = list(series_dir.glob('*.cbz'))
            if not cbzs:
                continue

            # Check directory name or CBZ prefix
            is_flame = series_dir.name.startswith('[Flame]') or any(
                f.name.startswith('[Flame]') for f in cbzs
            )

            if not is_flame:
                # Peek inside first CBZ for source tag
                try:
                    with zipfile.ZipFile(cbzs[0]) as z:
                        if 'ComicInfo.xml' in z.namelist():
                            xml = z.read('ComicInfo.xml').decode('utf-8', errors='replace')
                            if re.search(r'flamecomics', xml, re.I):
                                is_flame = True
                except Exception:
                    pass

            if is_flame:
                flame_dirs.append(series_dir)
    return flame_dirs


# ---------------------------------------------------------------------------
# Per-series fix
# ---------------------------------------------------------------------------

def fix_series(
    series_dir: Path,
    apply: bool,
    db_conn,
) -> dict:
    """Plan (and optionally apply) sequential renumbering for one series."""
    cbzs = sorted(
        series_dir.glob('*.cbz'),
        key=lambda f: parse_chapter_number(f.name),
    )
    if not cbzs:
        return {'renames': 0}

    print(f"\n{'─' * 70}")
    print(f"  {series_dir.name}  ({len(cbzs)} files)")

    # Build rename plan: sort order → new sequential number
    plan = []   # list of (old_path, new_path, new_num)
    for new_num, cbz in enumerate(cbzs, start=1):
        new_stem = replace_chapter_number_in_name(cbz.stem, new_num)
        new_path = cbz.parent / (new_stem + cbz.suffix)
        plan.append((cbz, new_path, new_num))

    # Report
    any_change = any(old.name != new.name for old, new, _ in plan)
    if not any_change:
        print("  Already correctly numbered — nothing to do.")
        return {'renames': 0}

    col = 62
    print(f"  {'CURRENT FILENAME':<{col}}  NEW FILENAME")
    print(f"  {'─' * col}  {'─' * col}")
    for old, new, num in plan:
        if old.name != new.name:
            print(f"  {old.name:<{col}}  {new.name}")
        else:
            print(f"  {old.name:<{col}}  [unchanged]")

    if not apply:
        print(f"\n  [DRY RUN] Pass --apply to make these changes.")
        return {'renames': 0}

    # -----------------------------------------------------------------------
    # Apply — two-pass to avoid name collisions
    # -----------------------------------------------------------------------
    # Pass 1: rename all files to unique temp names
    temp_map = []  # list of (tmp_path, final_path, num)
    for old, new, num in plan:
        tmp = old.with_name(f'__renumber_tmp_{old.name}')
        old.rename(tmp)
        temp_map.append((tmp, new, num))

    # Pass 2: rename temp → final name, patch ComicInfo.xml
    renames = 0
    for tmp, final, num in temp_map:
        tmp.rename(final)
        patch_comic_info(final, num, f"Chapter {num}")
        renames += 1

    # -----------------------------------------------------------------------
    # DB update
    # -----------------------------------------------------------------------
    if db_conn is not None:
        # Build old-path → new-path mapping from original plan
        old_to_new: dict[str, tuple[Path, int]] = {
            str(old): (new, num) for old, new, num in plan
        }
        cursor = db_conn.cursor()
        updated_db = 0
        for old_path_str, (new_path, num) in old_to_new.items():
            cursor.execute(
                "UPDATE Chapter SET number=?, title=?, filePath=? WHERE filePath=?",
                (num, f"Chapter {num}", str(new_path), old_path_str),
            )
            updated_db += cursor.rowcount
        db_conn.commit()
        print(f"\n  DB: updated {updated_db} chapter record(s).")

    print(f"\n  Done: {renames} file(s) renamed.")
    return {'renames': renames}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description='Fix FlameComics chapter numbering in downloaded CBZ files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--library', required=True,
        help='Root library directory (contains Manga/, Manhwa/, etc.)',
    )
    parser.add_argument(
        '--apply', action='store_true',
        help='Apply changes (default: dry run — no files are modified)',
    )
    parser.add_argument(
        '--db',
        help='Path to mangashelf.db to update chapter filePath/number records',
    )
    parser.add_argument(
        '--series',
        help='Only process series whose directory name contains this substring',
    )
    args = parser.parse_args()

    library_path = Path(args.library)
    if not library_path.exists():
        print(f"ERROR: library path not found: {library_path}")
        return 1

    mode = 'APPLYING CHANGES' if args.apply else 'DRY RUN (no files modified)'
    print(f"\n{'=' * 70}")
    print(f"  fix_flame_chapters.py — {mode}")
    print(f"  Library : {library_path}")
    if args.db:
        print(f"  Database: {args.db}")
    print(f"{'=' * 70}")

    flame_dirs = find_flame_dirs(library_path)
    if args.series:
        flame_dirs = [d for d in flame_dirs if args.series.lower() in d.name.lower()]

    if not flame_dirs:
        print("\nNo FlameComics series directories found.")
        return 0

    print(f"\nFound {len(flame_dirs)} FlameComics series:")
    for d in flame_dirs:
        print(f"  {d.name}")

    # Open DB connection if requested
    db_conn = None
    if args.apply and args.db:
        try:
            db_conn = sqlite3.connect(args.db)
            print(f"\nConnected to database: {args.db}")
        except Exception as e:
            print(f"\nWARNING: Could not open database ({e}).")
            print("  Files will be renamed but chapter records won't be updated.")
            print("  Run a library scan in OrvaultShelf afterward to fix the DB.")

    total_renames = 0
    for d in flame_dirs:
        result = fix_series(d, apply=args.apply, db_conn=db_conn)
        total_renames += result.get('renames', 0)

    if db_conn:
        db_conn.close()

    print(f"\n{'=' * 70}")
    if args.apply:
        print(f"  Total files renamed: {total_renames}")
        if not args.db:
            print()
            print("  NOTE: Database not updated. Trigger a library scan in")
            print("  OrvaultShelf (Admin → Library → Scan) to sync chapter records.")
    else:
        print("  DRY RUN complete — no files were modified.")
        print("  Run with --apply to apply the changes shown above.")
    print(f"{'=' * 70}\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
