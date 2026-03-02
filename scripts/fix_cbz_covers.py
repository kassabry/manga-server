#!/usr/bin/env python3
"""
fix_cbz_covers.py - Detect and remove sidebar cover images from chapter CBZ files

Some chapters have series cover images mixed in with the actual chapter pages
(typically at the start or end). This script detects them by comparing image
dimensions — cover images have a different aspect ratio from manga pages.

Usage:
    python fix_cbz_covers.py /path/to/library/Manhwa
    python fix_cbz_covers.py /path/to/library/Manhwa --dry-run
    python fix_cbz_covers.py /path/to/library/Manhwa --series "Absolute Sword Sense"
"""

import io
import os
import sys
import zipfile
import logging
import argparse
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}


def get_image_dimensions(data: bytes) -> tuple:
    """Get (width, height) from image bytes without PIL.

    Supports JPEG, PNG, WebP, and GIF by reading file headers.
    """
    if len(data) < 30:
        return (0, 0)

    # PNG: bytes 16-23 contain width and height as 4-byte big-endian
    if data[:4] == b'\x89PNG':
        w = int.from_bytes(data[16:20], 'big')
        h = int.from_bytes(data[20:24], 'big')
        return (w, h)

    # WebP: RIFF header, then 'WEBP'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        # VP8 lossy
        if data[12:16] == b'VP8 ':
            # Width and height at offset 26-29 (little-endian 16-bit)
            if len(data) > 29:
                w = int.from_bytes(data[26:28], 'little') & 0x3FFF
                h = int.from_bytes(data[28:30], 'little') & 0x3FFF
                return (w, h)
        # VP8L lossless
        elif data[12:16] == b'VP8L':
            if len(data) > 24:
                bits = int.from_bytes(data[21:25], 'little')
                w = (bits & 0x3FFF) + 1
                h = ((bits >> 14) & 0x3FFF) + 1
                return (w, h)
        # VP8X extended
        elif data[12:16] == b'VP8X':
            if len(data) > 29:
                w = int.from_bytes(data[24:27], 'little') + 1
                h = int.from_bytes(data[27:30], 'little') + 1
                return (w, h)
        return (0, 0)

    # GIF
    if data[:3] in (b'GIF', ):
        w = int.from_bytes(data[6:8], 'little')
        h = int.from_bytes(data[8:10], 'little')
        return (w, h)

    # JPEG: scan for SOF markers
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            # SOF0-SOF3, SOF5-SOF7, SOF9-SOF11, SOF13-SOF15
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h = int.from_bytes(data[i+5:i+7], 'big')
                w = int.from_bytes(data[i+7:i+9], 'big')
                return (w, h)
            elif marker == 0xD9:  # EOI
                break
            elif marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0x01):
                i += 2
            else:
                if i + 3 < len(data):
                    seg_len = int.from_bytes(data[i+2:i+4], 'big')
                    i += 2 + seg_len
                else:
                    break
        return (0, 0)

    return (0, 0)


def analyze_cbz(cbz_path: Path, dry_run: bool = False) -> dict:
    """Analyze a CBZ file for contaminating cover images.

    Returns dict with:
      - 'status': 'clean', 'contaminated', or 'error'
      - 'removed': list of filenames removed
      - 'total': total page images
    """
    result = {'status': 'clean', 'removed': [], 'total': 0, 'path': str(cbz_path)}

    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            # Get numbered page images (skip !000_cover.* and ComicInfo.xml)
            page_files = []
            for name in sorted(zf.namelist()):
                lower = name.lower()
                if lower.startswith('!') or lower == 'comicinfo.xml':
                    continue
                ext = os.path.splitext(lower)[1]
                if ext in IMAGE_EXTENSIONS:
                    page_files.append(name)

            result['total'] = len(page_files)

            if len(page_files) <= 3:
                return result  # Too few pages to analyze

            # Get dimensions for all page images
            dims = []
            for name in page_files:
                data = zf.read(name)
                w, h = get_image_dimensions(data)
                dims.append((w, h, name))

            # Filter out unreadable images
            valid_dims = [(w, h, n) for w, h, n in dims if w > 0 and h > 0]
            if len(valid_dims) < 3:
                return result

            # Calculate aspect ratios
            ratios = [(w / h if h > 0 else 0, n) for w, h, n in valid_dims]

            # Find the most common width (the "chapter page" width)
            widths = [w for w, h, n in valid_dims]
            width_counts = Counter(widths)
            common_width = width_counts.most_common(1)[0][0]

            # Pages whose width differs significantly from the common width are suspects
            # Cover images tend to have a noticeably different width
            suspects = []
            for i, (w, h, name) in enumerate(valid_dims):
                width_diff = abs(w - common_width) / common_width if common_width > 0 else 0
                # Only flag images at the START or END of the chapter
                is_edge = i < 3 or i >= len(valid_dims) - 3
                if width_diff > 0.15 and is_edge:  # >15% width difference
                    suspects.append(name)

            if not suspects:
                return result

            # Verify: suspects should be a small fraction of total pages
            if len(suspects) > len(page_files) * 0.3:
                # Too many suspects — probably not a contamination issue
                logger.debug(f"  Skipping {cbz_path.name}: too many dimension mismatches ({len(suspects)}/{len(page_files)})")
                return result

            result['status'] = 'contaminated'
            result['removed'] = suspects

            if not dry_run:
                # Rewrite CBZ without the suspect images
                rewrite_cbz(cbz_path, set(suspects))

    except Exception as e:
        result['status'] = 'error'
        logger.error(f"Error analyzing {cbz_path.name}: {e}")

    return result


def rewrite_cbz(cbz_path: Path, remove_files: set):
    """Rewrite a CBZ file, excluding specified files and renumbering remaining pages."""
    temp_path = cbz_path.with_suffix('.cbz.tmp')

    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf_in:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zf_out:
                # Copy non-page files as-is (cover, ComicInfo.xml)
                page_num = 1
                for name in sorted(zf_in.namelist()):
                    data = zf_in.read(name)
                    lower = name.lower()

                    if name in remove_files:
                        continue

                    # Renumber page images to keep them sequential
                    ext = os.path.splitext(name)[1]
                    if not lower.startswith('!') and lower != 'comicinfo.xml' and ext.lower() in IMAGE_EXTENSIONS:
                        new_name = f"{page_num:03d}{ext}"
                        zf_out.writestr(new_name, data)
                        page_num += 1
                    else:
                        zf_out.writestr(name, data)

        # Replace original with cleaned version
        cbz_path.unlink()
        temp_path.rename(cbz_path)
        logger.info(f"  Cleaned: {cbz_path.name} (removed {len(remove_files)} cover image(s))")

    except Exception as e:
        logger.error(f"Error rewriting {cbz_path.name}: {e}")
        if temp_path.exists():
            temp_path.unlink()


def process_series(series_dir: Path, dry_run: bool = False) -> dict:
    """Process all CBZ files in a series directory."""
    cbz_files = sorted(series_dir.glob('*.cbz'))
    if not cbz_files:
        return {'total': 0, 'contaminated': 0, 'cleaned': 0}

    stats = {'total': len(cbz_files), 'contaminated': 0, 'cleaned': 0}
    logger.info(f"Scanning: {series_dir.name} ({len(cbz_files)} chapters)")

    for cbz_path in cbz_files:
        result = analyze_cbz(cbz_path, dry_run=dry_run)
        if result['status'] == 'contaminated':
            stats['contaminated'] += 1
            action = "Would remove" if dry_run else "Removed"
            logger.info(f"  {cbz_path.name}: {action} {len(result['removed'])} cover image(s) from {result['total']} pages")
            for name in result['removed']:
                logger.debug(f"    - {name}")
            if not dry_run:
                stats['cleaned'] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description='Fix CBZ files contaminated with sidebar cover images')
    parser.add_argument('library_path', help='Path to library directory (e.g., ./library/Manhwa)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fixed without making changes')
    parser.add_argument('--series', help='Only process a specific series by name')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    library_path = Path(args.library_path)
    if not library_path.is_dir():
        logger.error(f"Directory not found: {library_path}")
        sys.exit(1)

    if args.dry_run:
        logger.info("=== DRY RUN MODE — no changes will be made ===")

    total_stats = {'total': 0, 'contaminated': 0, 'cleaned': 0}

    if args.series:
        series_dir = library_path / args.series
        if not series_dir.is_dir():
            logger.error(f"Series directory not found: {series_dir}")
            sys.exit(1)
        stats = process_series(series_dir, dry_run=args.dry_run)
        for k in total_stats:
            total_stats[k] += stats[k]
    else:
        for entry in sorted(library_path.iterdir()):
            if entry.is_dir() and not entry.name.startswith('.'):
                stats = process_series(entry, dry_run=args.dry_run)
                for k in total_stats:
                    total_stats[k] += stats[k]

    logger.info(f"\n=== Summary ===")
    logger.info(f"Total chapters scanned: {total_stats['total']}")
    logger.info(f"Contaminated chapters: {total_stats['contaminated']}")
    if args.dry_run:
        logger.info(f"Would clean: {total_stats['contaminated']} chapters")
    else:
        logger.info(f"Cleaned: {total_stats['cleaned']} chapters")


if __name__ == '__main__':
    main()
