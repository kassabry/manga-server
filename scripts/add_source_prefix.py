#!/usr/bin/env python3
"""
add_source_prefix.py - Retroactively add [Source] prefix to series directories and CBZ files

Usage:
    python add_source_prefix.py /path/to/library/Manhwa --source Asura --exclude "Series Name 1,Series Name 2"
    python add_source_prefix.py /path/to/library/Manhwa --source Manhuato --only "Series Name 1,Series Name 2"
    python add_source_prefix.py /path/to/library/Manhwa --source Asura --dry-run

Examples (run both to prefix everything):
    # First: prefix the ManhuaTo series
    python add_source_prefix.py ./library/Manhwa --source Manhuato --only "Assassin's Creed Forgotten Temple,Hero Killer,..." --dry-run
    # Then: prefix everything else as Asura
    python add_source_prefix.py ./library/Manhwa --source Asura --dry-run
"""

import os
import re
import sys
import zipfile
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def rename_series(library_path: Path, source: str, only: list = None,
                  exclude: list = None, dry_run: bool = False) -> int:
    """Add [Source] prefix to series directories and their CBZ files."""
    prefix = f"[{source}] "
    renamed = 0

    for entry in sorted(library_path.iterdir()):
        if not entry.is_dir() or entry.name.startswith('.'):
            continue

        # Skip directories that already have a source prefix
        if re.match(r'^\[.+?\] ', entry.name):
            logger.debug(f"Skipping (already prefixed): {entry.name}")
            continue

        # Apply --only / --exclude filters
        if only and entry.name not in only:
            continue
        if exclude and entry.name in exclude:
            continue

        new_dir_name = f"{prefix}{entry.name}"
        new_dir_path = library_path / new_dir_name

        if new_dir_path.exists():
            logger.warning(f"Skipping (target exists): {new_dir_name}")
            continue

        logger.info(f"Rename dir: {entry.name} -> {new_dir_name}")

        # Rename CBZ files inside the directory
        cbz_count = 0
        for cbz_file in sorted(entry.glob('*.cbz')):
            old_cbz_name = cbz_file.name
            # Replace the series title prefix in the CBZ filename
            # Pattern: "Series Title - Chapter N.cbz" -> "[Source] Series Title - Chapter N.cbz"
            new_cbz_name = f"{prefix}{old_cbz_name}"

            if not dry_run:
                new_cbz_path = cbz_file.parent / new_cbz_name
                cbz_file.rename(new_cbz_path)

            cbz_count += 1
            logger.debug(f"  CBZ: {old_cbz_name} -> {new_cbz_name}")

        # Rename the directory itself
        if not dry_run:
            entry.rename(new_dir_path)

        logger.info(f"  Renamed {cbz_count} CBZ files")
        renamed += 1

    return renamed


def main():
    parser = argparse.ArgumentParser(
        description='Add [Source] prefix to series directories and CBZ files')
    parser.add_argument('library_path',
                        help='Path to library type directory (e.g., ./library/Manhwa)')
    parser.add_argument('--source', required=True,
                        help='Source name to use as prefix (e.g., Asura, Manhuato, Flame)')
    parser.add_argument('--only',
                        help='Comma-separated list of series names to prefix (only these)')
    parser.add_argument('--exclude',
                        help='Comma-separated list of series names to skip')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be renamed without making changes')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    library_path = Path(args.library_path)
    if not library_path.is_dir():
        logger.error(f"Directory not found: {library_path}")
        sys.exit(1)

    only = [s.strip() for s in args.only.split(',')] if args.only else None
    exclude = [s.strip() for s in args.exclude.split(',')] if args.exclude else None

    if args.dry_run:
        logger.info("=== DRY RUN — no changes will be made ===")

    renamed = rename_series(library_path, args.source, only=only,
                            exclude=exclude, dry_run=args.dry_run)

    logger.info(f"\n{'Would rename' if args.dry_run else 'Renamed'} {renamed} series")
    if renamed > 0 and not args.dry_run:
        logger.info("Run a scan on ORVault to pick up the changes.")
        logger.info("The old series entries will be auto-cleaned from the database.")


if __name__ == '__main__':
    main()
