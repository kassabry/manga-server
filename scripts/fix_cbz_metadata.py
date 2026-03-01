#!/usr/bin/env python3
"""
fix_cbz_metadata.py - Fix chapter titles in existing CBZ files

Patches ComicInfo.xml inside each CBZ to clean up concatenated date strings
in chapter titles (e.g., "Chapter 2July 12th 2025" -> "Chapter 2").

Usage:
    python fix_cbz_metadata.py /path/to/library/Manhwa
    python fix_cbz_metadata.py /path/to/library/Manhwa --dry-run  # preview only
"""

import os
import re
import sys
import zipfile
import tempfile
import shutil
from pathlib import Path


def fix_title(title: str) -> str:
    """Clean a chapter title by removing concatenated date/junk text"""
    if not title:
        return title

    # Pattern: "Chapter 2July 12th 2025" or "First ChapterChapter1"
    # If title has a month name concatenated after chapter text, strip it
    match = re.match(
        r'(chapter\s*\d+(?:\.\d+)?)\s*'
        r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec).*',
        title, re.I
    )
    if match:
        return match.group(1)

    # Pattern: "First ChapterChapter1" - duplicate "Chapter" text
    match = re.match(r'(.+?)(chapter\s*\d+)', title, re.I)
    if match and 'chapter' in match.group(1).lower():
        return match.group(2)

    # Pattern: title followed by a date like "2025" or "12th"
    match = re.match(
        r'(chapter\s*\d+(?:\.\d+)?)\s*\d{1,2}(?:st|nd|rd|th)',
        title, re.I
    )
    if match:
        return match.group(1)

    return title


def fix_cbz_file(cbz_path: Path, dry_run: bool = False) -> bool:
    """Fix ComicInfo.xml inside a CBZ file. Returns True if modified."""
    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            if 'ComicInfo.xml' not in zf.namelist():
                return False

            xml_content = zf.read('ComicInfo.xml').decode('utf-8')

        # Extract current title
        title_match = re.search(r'<Title>(.*?)</Title>', xml_content)
        if not title_match:
            return False

        old_title = title_match.group(1)
        new_title = fix_title(old_title)

        if old_title == new_title:
            return False

        if dry_run:
            print(f"  Would fix: '{old_title}' -> '{new_title}'")
            return True

        # Replace title in XML
        new_xml = xml_content.replace(
            f'<Title>{old_title}</Title>',
            f'<Title>{new_title}</Title>'
        )

        # Rewrite the CBZ with updated XML
        temp_path = cbz_path.with_suffix('.cbz.tmp')
        with zipfile.ZipFile(cbz_path, 'r') as zf_in:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_STORED) as zf_out:
                for item in zf_in.infolist():
                    if item.filename == 'ComicInfo.xml':
                        zf_out.writestr(item, new_xml.encode('utf-8'))
                    else:
                        zf_out.writestr(item, zf_in.read(item.filename))

        # Replace original with fixed version
        temp_path.replace(cbz_path)
        print(f"  Fixed: '{old_title}' -> '{new_title}'")
        return True

    except Exception as e:
        print(f"  Error processing {cbz_path.name}: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_cbz_metadata.py /path/to/library [--dry-run]")
        sys.exit(1)

    library_path = Path(sys.argv[1])
    dry_run = '--dry-run' in sys.argv

    if not library_path.is_dir():
        print(f"Error: {library_path} is not a directory")
        sys.exit(1)

    if dry_run:
        print("DRY RUN - no files will be modified\n")

    fixed_count = 0
    total_count = 0

    for cbz_file in sorted(library_path.rglob('*.cbz')):
        total_count += 1
        if fix_cbz_file(cbz_file, dry_run):
            fixed_count += 1

    print(f"\nScanned {total_count} CBZ files, {'would fix' if dry_run else 'fixed'} {fixed_count}")


if __name__ == '__main__':
    main()
