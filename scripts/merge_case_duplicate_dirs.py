#!/usr/bin/env python3
"""Merge series directories that differ only by letter case.

The library lives on ext4, which is case-sensitive, while every title match in
the scraper is not.  A source that changes its title casing between runs — or a
merge that adopts another source's spelling — creates a second directory beside
the first:

    [Manhuato] Evolution Begins with a Big Tree   502 cbz
    [Manhuato] Evolution Begins With a Big Tree   427 cbz

The scanner merges those back into one series by slug, so every chapter shows
up twice in the reader, and the scraper re-downloads the back catalogue because
its existence check scanned whichever folder it built the name for.

This script finds each group of same-parent directories whose names match
ignoring case, keeps the one holding the most chapters, and moves the others'
chapters into it.  Chapter files carry the series title in their own filename,
so they are renamed onto the surviving directory's spelling as they move.

    # report only
    python scripts/merge_case_duplicate_dirs.py --library library

    # actually merge
    python scripts/merge_case_duplicate_dirs.py --library library --apply

A chapter already present in the surviving directory is left alone by default
and reported as a conflict; --prefer-larger keeps whichever file is bigger,
which is usually the more complete rip.  Nothing is ever deleted: conflicting
files stay where they are unless --drop-conflicts is passed, and a source
directory is removed only once it is empty.

Directories under different parents (Manhua/ vs Manhwa/) are NOT touched — a
series filed under two types is a separate problem with a different fix.

Python 3.8-compatible: typing.List rather than list[...], no `X | Y` unions.
"""

import argparse
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

# Files this project writes alongside the chapters.  A directory holding only
# these and no CBZ is a shell left behind by a title-casing change.
ARTIFACTS = frozenset((
    '.mangadot_versions.json', '.mangadot_meta.json',
    'cover.webp', 'cover.jpg', 'cover.jpeg', 'cover.png',
    'ComicInfo.xml', '.DS_Store', 'Thumbs.db',
))

CHAPTER_RE = re.compile(r'^(?P<title>.*) - Chapter (?P<num>[0-9]+(?:\.[0-9]+)?)\.cbz$',
                        re.IGNORECASE)


def cbz_files(path):
    # type: (str) -> List[str]
    try:
        return sorted(n for n in os.listdir(path) if n.lower().endswith('.cbz'))
    except OSError:
        return []


def find_groups(library_root):
    # type: (str) -> List[Tuple[str, List[str]]]
    """Groups of sibling directories whose names differ only by case."""
    groups = []  # type: List[Tuple[str, List[str]]]
    try:
        parents = [os.path.join(library_root, d) for d in sorted(os.listdir(library_root))]
    except OSError:
        return groups
    for parent in parents:
        if not os.path.isdir(parent):
            continue
        by_key = {}  # type: Dict[str, List[str]]
        try:
            names = sorted(os.listdir(parent))
        except OSError:
            continue
        for name in names:
            full = os.path.join(parent, name)
            if not os.path.isdir(full):
                continue
            by_key.setdefault(name.lower(), []).append(name)
        for key in sorted(by_key):
            if len(by_key[key]) > 1:
                groups.append((parent, by_key[key]))
    return groups


def target_name(names, parent):
    # type: (List[str], str) -> str
    """Keep the directory holding the most chapters; ties break alphabetically."""
    return sorted(names, key=lambda n: (-len(cbz_files(os.path.join(parent, n))), n))[0]


def destination_for(filename, keep_dir_name):
    # type: (str, str) -> Optional[str]
    """Rewrite a chapter filename onto the surviving directory's title spelling."""
    match = CHAPTER_RE.match(filename)
    if not match:
        return None
    return "%s - Chapter %s.cbz" % (keep_dir_name, match.group('num'))


def merge_group(parent, names, apply_changes, prefer_larger, drop_conflicts):
    # type: (str, List[str], bool, bool, bool) -> Tuple[int, int, int]
    """Returns (moved, conflicts, unparsed)."""
    keep = target_name(names, parent)
    keep_path = os.path.join(parent, keep)
    moved = conflicts = unparsed = 0

    print('  keep : %s (%d cbz)' % (keep, len(cbz_files(keep_path))))
    for name in names:
        if name == keep:
            continue
        src_dir = os.path.join(parent, name)
        files = cbz_files(src_dir)
        print('  merge: %s (%d cbz)' % (name, len(files)))
        for filename in files:
            dest_name = destination_for(filename, keep)
            if dest_name is None:
                # Not "{title} - Chapter {n}.cbz" — do not guess at it.
                print('     ?  %s (unrecognised name, left in place)' % filename)
                unparsed += 1
                continue
            src = os.path.join(src_dir, filename)
            dst = os.path.join(keep_path, dest_name)

            if os.path.exists(dst):
                src_size = os.path.getsize(src)
                dst_size = os.path.getsize(dst)
                bigger_is_src = src_size > dst_size
                if prefer_larger and bigger_is_src:
                    print('     >  %s replaces the kept copy (%d KB vs %d KB)'
                          % (dest_name, src_size // 1024, dst_size // 1024))
                    if apply_changes:
                        os.replace(src, dst)
                    moved += 1
                    continue
                conflicts += 1
                note = 'kept copy is larger' if not bigger_is_src else 'kept copy is smaller'
                print('     !  %s already present (%s)' % (dest_name, note))
                if drop_conflicts and apply_changes:
                    os.remove(src)
                continue

            if apply_changes:
                shutil.move(src, dst)
            moved += 1

        # Sidecars: only carry across what the survivor does not already have.
        for extra in ARTIFACTS:
            src = os.path.join(src_dir, extra)
            dst = os.path.join(keep_path, extra)
            if os.path.exists(src) and not os.path.exists(dst) and apply_changes:
                try:
                    shutil.move(src, dst)
                except OSError:
                    pass

        # A directory left holding no chapters at all is a shell: the casing
        # changed between runs and this spelling never received one.  Its cover
        # and sidecars are not worth keeping on their own, so clear them out —
        # but only ever the artifacts we know we wrote.
        remaining = sorted(os.listdir(src_dir)) if os.path.isdir(src_dir) else []
        if remaining and not cbz_files(src_dir):
            leftovers = [n for n in remaining if n not in ARTIFACTS]
            if leftovers:
                print('     .  %s holds %d unrecognised file(s), left in place: %s'
                      % (name, len(leftovers), ', '.join(leftovers[:3])))
            elif apply_changes:
                for n in remaining:
                    try:
                        os.remove(os.path.join(src_dir, n))
                    except OSError:
                        pass
                remaining = sorted(os.listdir(src_dir))

        if apply_changes:
            remaining = os.listdir(src_dir) if os.path.isdir(src_dir) else []
            if not remaining:
                try:
                    os.rmdir(src_dir)
                    print('     -  removed empty %s' % name)
                except OSError as exc:
                    print('     -  could not remove %s: %s' % (name, exc))
            else:
                print('     .  %s still holds %d file(s), left in place'
                      % (name, len(remaining)))
    return moved, conflicts, unparsed


def main():
    # type: () -> int
    parser = argparse.ArgumentParser(
        description='Merge series directories that differ only by letter case.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--library', required=True,
                        help='Library root (contains Manga/, Manhwa/, ...)')
    parser.add_argument('--apply', action='store_true',
                        help='Actually move files (default: report only)')
    parser.add_argument('--prefer-larger', action='store_true',
                        help='On a filename clash keep whichever file is bigger '
                             '(default: keep the surviving directory\'s copy)')
    parser.add_argument('--series',
                        help='Only groups whose directory name contains this '
                             'substring (case-insensitive)')
    parser.add_argument('--drop-conflicts', action='store_true',
                        help='Delete the losing copy on a clash instead of leaving '
                             'it in place. Only meaningful with --apply')
    args = parser.parse_args()

    if not os.path.isdir(args.library):
        print('ERROR: library not found: %s' % args.library)
        return 1

    mode = 'APPLYING' if args.apply else 'DRY RUN (nothing moved)'
    print('\n%s' % ('=' * 70))
    print('  merge_case_duplicate_dirs.py — %s' % mode)
    print('  Library: %s' % args.library)
    print('%s\n' % ('=' * 70))

    groups = find_groups(args.library)
    if args.series:
        needle = args.series.lower()
        groups = [(p, n) for p, n in groups if any(needle in x.lower() for x in n)]
    if not groups:
        print('No case-duplicate directories found.')
        return 0

    total_moved = total_conflicts = total_unparsed = 0
    for parent, names in groups:
        print('%s' % os.path.basename(parent))
        moved, conflicts, unparsed = merge_group(
            parent, names, args.apply, args.prefer_larger, args.drop_conflicts)
        total_moved += moved
        total_conflicts += conflicts
        total_unparsed += unparsed
        print()

    print('%s' % ('-' * 70))
    print('%d group(s); %d chapter(s) %s, %d clash, %d unrecognised'
          % (len(groups), total_moved, 'moved' if args.apply else 'would move',
             total_conflicts, total_unparsed))
    if not args.apply:
        print('\nDry run — re-run with --apply to perform the merge.')
    else:
        print('\nRescan the library so the duplicate chapter rows disappear.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
