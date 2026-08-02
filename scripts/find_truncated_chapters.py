#!/usr/bin/env python3
"""Find (and clear) MangaDot chapters that were downloaded incomplete.

The MangaDot reader lazy-loads its images, and the scraper used to walk it
with a fixed number of scroll jumps. Any chapter taller than that stopped
early, producing a CBZ that looks fine but is missing its ending — a 147-page
chapter could land as 34 pages with nothing to indicate it.

`.mangadot_versions.json` records how many pages each chapter was advertised
as having, so the damage is measurable after the fact: compare that against
the images actually inside the CBZ.

    # report only
    python scripts/find_truncated_chapters.py --library library

    # delete the short ones so the next scrape refetches them
    python scripts/find_truncated_chapters.py --library library --apply

Then just re-run the MangaDot scraper as usual — no extra flag. Deleting the
CBZ is the whole trigger: download_chapter only honours its progress tracker
while the file is still on disk, and otherwise clears the entry itself and
refetches. `--tracker` merely keeps that progress file tidy.

A little slack is allowed by default because the downloader legitimately drops
a few promo images per chapter (_filter_outlier_images_by_dimension), so an
exact match is not expected even for a healthy file.

Python 3.8-compatible: typing.List rather than list[...], no `X | Y` unions.
"""

import argparse
import json
import os
import re
import sys
import zipfile
from typing import Dict, List, Optional, Tuple

VERSION_MANIFEST = '.mangadot_versions.json'
IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')

# Below this fraction of the advertised page count, a chapter is treated as
# truncated rather than merely trimmed.
DEFAULT_TOLERANCE = 0.9


def cbz_image_count(path: str) -> Optional[int]:
    """Number of image entries in a CBZ, or None if it cannot be read."""
    try:
        with zipfile.ZipFile(path) as zf:
            return sum(
                1 for n in zf.namelist()
                if n.lower().endswith(IMAGE_SUFFIXES) and 'cover' not in n.lower()
            )
    except Exception:
        return None


def chapter_number_from_name(name: str) -> Optional[str]:
    """Pull the chapter number out of '{Title} - Chapter {N}.cbz'."""
    match = re.search(r'chapter\s+([0-9]+(?:\.[0-9]+)?)\s*\.cbz$', name, re.I)
    return match.group(1) if match else None


def normalize_key(value: str) -> str:
    """Manifest keys are str(float) or str(int) — compare them numerically."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number == int(number) else str(number)


def scan_series(series_dir: str, tolerance: float) -> List[dict]:
    """Compare every CBZ in a series against its recorded page count."""
    manifest_path = os.path.join(series_dir, VERSION_MANIFEST)
    try:
        with open(manifest_path, encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception:
        return []

    by_number = {}  # type: Dict[str, dict]
    for key, entry in manifest.items():
        if isinstance(entry, dict):
            by_number[normalize_key(key)] = entry

    findings = []
    for name in sorted(os.listdir(series_dir)):
        if not name.lower().endswith('.cbz'):
            continue
        number = chapter_number_from_name(name)
        if number is None:
            continue
        entry = by_number.get(normalize_key(number))
        if not entry:
            # No manifest entry — nothing to compare against. Deliberately not
            # reported: chapters predating version tracking are not evidence
            # of truncation.
            continue

        expected = int(entry.get('pages') or 0)
        if expected <= 0:
            continue

        path = os.path.join(series_dir, name)
        actual = cbz_image_count(path)
        # The URL has to be captured now: the manifest entry is removed when
        # the file is cleared, and the tracker still needs it to forget the
        # download.
        url = entry.get('url') or ''

        if actual is None:
            findings.append({'path': path, 'name': name, 'number': number,
                             'expected': expected, 'actual': -1, 'url': url,
                             'reason': 'unreadable', 'entry_key': number})
            continue

        if actual < expected * tolerance:
            findings.append({'path': path, 'name': name, 'number': number,
                             'expected': expected, 'actual': actual, 'url': url,
                             'reason': 'truncated', 'entry_key': number})
    return findings


def find_series_dirs(library_root: str) -> List[str]:
    """Every directory carrying a MangaDot version manifest."""
    out = []
    for dirpath, dirnames, filenames in os.walk(library_root):
        if VERSION_MANIFEST in filenames:
            out.append(dirpath)
        # Chapters live directly in a series dir; no need to descend further.
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
    return sorted(out)


def rewrite_manifest(series_dir: str, drop_numbers: List[str]) -> None:
    """Remove cleared chapters so the scraper refetches instead of upgrading."""
    path = os.path.join(series_dir, VERSION_MANIFEST)
    try:
        with open(path, encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception:
        return

    wanted = set(normalize_key(n) for n in drop_numbers)
    remaining = {k: v for k, v in manifest.items()
                 if normalize_key(k) not in wanted}
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(remaining, f, indent=1, ensure_ascii=False)
    except Exception as e:
        print('  WARNING: could not rewrite %s (%s)' % (path, e))


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Find MangaDot chapters downloaded with missing pages.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--library', required=True,
                        help='Library root (contains Manga/, Manhwa/, ...)')
    parser.add_argument('--apply', action='store_true',
                        help='Delete short CBZs so they are refetched '
                             '(default: report only)')
    parser.add_argument('--tracker',
                        help='Optional: downloader progress JSON to prune the '
                             'refetched URLs from. Not required — the scraper '
                             'already refetches any chapter whose CBZ is gone')
    parser.add_argument('--tolerance', type=float, default=DEFAULT_TOLERANCE,
                        help='Fraction of the advertised page count a chapter '
                             'must reach (default: %.2f)' % DEFAULT_TOLERANCE)
    parser.add_argument('--series', help='Only series whose directory name '
                                         'contains this substring')
    args = parser.parse_args()

    if not os.path.isdir(args.library):
        print('ERROR: library not found: %s' % args.library)
        return 1

    mode = 'APPLYING' if args.apply else 'DRY RUN (nothing deleted)'
    print('\n%s' % ('=' * 70))
    print('  find_truncated_chapters.py — %s' % mode)
    print('  Library  : %s' % args.library)
    print('  Tolerance: %.0f%% of advertised pages' % (args.tolerance * 100))
    print('%s\n' % ('=' * 70))

    series_dirs = find_series_dirs(args.library)
    if args.series:
        needle = args.series.lower()
        series_dirs = [d for d in series_dirs if needle in os.path.basename(d).lower()]

    if not series_dirs:
        print('No MangaDot series found (looked for %s).' % VERSION_MANIFEST)
        print('Only chapters downloaded with version tracking can be checked.')
        return 0

    print('Checking %d MangaDot series...\n' % len(series_dirs))

    total_checked = 0
    all_findings = []  # type: List[Tuple[str, List[dict]]]
    for series_dir in series_dirs:
        findings = scan_series(series_dir, args.tolerance)
        total_checked += 1
        if not findings:
            continue
        all_findings.append((series_dir, findings))
        print('%s' % os.path.basename(series_dir))
        for f in findings:
            if f['reason'] == 'unreadable':
                print('   Ch.%-8s UNREADABLE  %s' % (f['number'], f['name']))
            else:
                pct = 100.0 * f['actual'] / f['expected']
                print('   Ch.%-8s %3d of %3d pages (%.0f%%)'
                      % (f['number'], f['actual'], f['expected'], pct))
        print()

    short = sum(len(f) for _, f in all_findings)
    print('%s' % ('-' * 70))
    print('%d series checked, %d chapter(s) look incomplete' % (total_checked, short))

    if not short:
        print('Nothing to do.')
        return 0

    if not args.apply:
        print('\nDry run — re-run with --apply to delete these so the next')
        print('scrape refetches them with the fixed scroll logic.')
        if not args.tracker:
            print('Pass --tracker too, or the scraper will consider them done.')
        return 0

    removed = 0
    cleared_urls = []  # type: List[str]
    for series_dir, findings in all_findings:
        cleared = []
        for f in findings:
            try:
                os.remove(f['path'])
                cleared.append(f['entry_key'])
                if f.get('url'):
                    cleared_urls.append(f['url'])
                removed += 1
            except OSError as e:
                print('  could not delete %s: %s' % (f['name'], e))
        if cleared:
            rewrite_manifest(series_dir, cleared)

    print('\nDeleted %d incomplete chapter file(s).' % removed)

    print('Re-run the MangaDot scraper to refetch them — no extra flags needed.')

    if not args.tracker:
        # Deleting the file is enough on its own: download_chapter only trusts
        # the tracker while the CBZ is still there, and otherwise drops the
        # entry itself and refetches.
        return 0

    try:
        with open(args.tracker, encoding='utf-8') as fh:
            downloaded = set(json.load(fh))
    except Exception as e:
        print('WARNING: could not read tracker %s (%s).' % (args.tracker, e))
        print('The scraper may skip the deleted chapters.')
        return 0

    before = len(downloaded)
    downloaded.difference_update(cleared_urls)
    dropped = before - len(downloaded)
    try:
        with open(args.tracker, 'w', encoding='utf-8') as fh:
            json.dump(sorted(downloaded), fh)
        print('Cleared %d of %d tracker entr(ies); %d remain.'
              % (dropped, before, len(downloaded)))
    except Exception as e:
        print('WARNING: could not write tracker %s (%s).' % (args.tracker, e))
        print('Harmless — the scraper refetches any chapter whose CBZ is gone.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
