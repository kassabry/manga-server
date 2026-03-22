#!/usr/bin/env python3
"""
fix_lightnovel_dirs.py — Move flat EPUB files into per-series subdirectories.

EPUBs in the LightNovels root that were written before the subdirectory fix
will have names like:
  [Lightnovelpub] Complete Martial Arts Attributes Vol. 1.epub

This script moves them into:
  [Lightnovelpub] Complete Martial Arts Attributes/
    [Lightnovelpub] Complete Martial Arts Attributes Vol. 1.epub

Usage:
  python fix_lightnovel_dirs.py /library/LightNovels          # dry run
  python fix_lightnovel_dirs.py /library/LightNovels --apply  # apply changes
"""

import argparse
import re
import shutil
import sys
from pathlib import Path


def series_title_from_epub(epub_name: str) -> str:
    """Strip ' Vol. N' suffix to get the series title."""
    # Handles "Title Vol. 1.epub", "Title Vol. 12.epub"
    stem = Path(epub_name).stem  # strip .epub
    cleaned = re.sub(r'\s+Vol\.\s*\d+$', '', stem, flags=re.IGNORECASE)
    return cleaned.strip()


def main():
    parser = argparse.ArgumentParser(description="Move flat LightNovels EPUBs into series subdirectories")
    parser.add_argument("library", help="Path to LightNovels directory")
    parser.add_argument("--apply", action="store_true", help="Actually move files (default: dry run)")
    args = parser.parse_args()

    root = Path(args.library)
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    epub_files = [f for f in root.iterdir() if f.is_file() and f.suffix.lower() == '.epub']

    if not epub_files:
        print("No flat EPUB files found — nothing to do.")
        return

    moves: list[tuple[Path, Path]] = []
    for epub in sorted(epub_files):
        title = series_title_from_epub(epub.name)
        dest_dir = root / title
        dest_file = dest_dir / epub.name
        moves.append((epub, dest_file))

    print(f"{'DRY RUN — ' if not args.apply else ''}Found {len(moves)} EPUB(s) to move:\n")
    for src, dst in moves:
        print(f"  {src.name}")
        print(f"    → {dst.relative_to(root)}")

    if not args.apply:
        print(f"\nRun with --apply to move files.")
        return

    print()
    errors = 0
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            print(f"  SKIP (already exists): {dst.name}")
            continue
        try:
            shutil.move(str(src), str(dst))
            print(f"  Moved: {src.name} → {dst.parent.name}/")
        except Exception as e:
            print(f"  ERROR moving {src.name}: {e}", file=sys.stderr)
            errors += 1

    print(f"\nDone. {len(moves) - errors} moved, {errors} error(s).")


if __name__ == "__main__":
    main()
