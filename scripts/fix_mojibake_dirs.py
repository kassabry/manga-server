#!/usr/bin/env python3
"""
fix_mojibake_dirs.py — Find and delete series directories whose names contain
UTF-8 mojibake characters caused by responses being decoded as Latin-1.

The most common case: the RIGHT SINGLE QUOTATION MARK U+2019 (') has UTF-8
bytes E2 80 99, which when read as Latin-1 produce the visible character 'â'
followed by two control/invisible chars.  Folder names like

    [Asura] Omniscient Readerâs Viewpoint

are the result.  This script finds every top-level series directory under the
given library root(s) that contains any of these mojibake sequences and offers
to delete them.

Usage
-----
    # Dry run — show what would be deleted (safe, default)
    python scripts/fix_mojibake_dirs.py /mnt/manga-storage

    # Also scan sub-libraries explicitly
    python scripts/fix_mojibake_dirs.py /mnt/manga-storage/Manhwa /mnt/manga-storage/Manhua

    # Apply — actually delete the directories
    python scripts/fix_mojibake_dirs.py /mnt/manga-storage --apply

The script checks whether a "corrected" sibling directory already exists
(i.e. the same folder name after fixing the encoding).  If it does, the
mojibake directory is safe to delete — the good version is already there.
If no corrected sibling exists yet, the script warns you so you can decide
whether to delete or wait for the scraper to create the corrected version first.
"""

import argparse
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Mojibake detection
# ---------------------------------------------------------------------------

# Characters produced when UTF-8 multi-byte sequences are decoded as Latin-1.
# Each tuple is (mojibake_str, correct_unicode_char).
# We check for the VISIBLE mojibake char (â) since the trailing bytes are often
# invisible control characters that may or may not survive the terminal/FS layer.
MOJIBAKE_MAP = [
    # UTF-8 bytes of U+2019 RIGHT SINGLE QUOTATION MARK decoded as Latin-1
    ("\u00e2\u0080\u0099", "\u2019"),   # â€™  →  '
    # UTF-8 bytes of U+2018 LEFT SINGLE QUOTATION MARK
    ("\u00e2\u0080\u0098", "\u2018"),   # â€˜  →  '
    # UTF-8 bytes of U+201C LEFT DOUBLE QUOTATION MARK
    ("\u00e2\u0080\u009c", "\u201c"),   # â€œ  →  "
    # UTF-8 bytes of U+201D RIGHT DOUBLE QUOTATION MARK
    ("\u00e2\u0080\u009d", "\u201d"),   # â€   →  "
    # UTF-8 bytes of U+2013 EN DASH
    ("\u00e2\u0080\u0093", "\u2013"),   # â€"  →  –
    # UTF-8 bytes of U+2014 EM DASH
    ("\u00e2\u0080\u0094", "\u2014"),   # â€"  →  —
    # UTF-8 bytes of U+2026 HORIZONTAL ELLIPSIS
    ("\u00e2\u0080\u00a6", "\u2026"),   # â€¦  →  …
]

# Simple heuristic: the visible 'â' followed immediately by a control/high-byte
# character is the tell-tale sign.  We also accept the full 3-char sequence.
def _is_mojibake(name: str) -> bool:
    """Return True if the directory name contains any known mojibake sequence."""
    for bad, _ in MOJIBAKE_MAP:
        if bad in name:
            return True
    # Fallback: lone â followed by a non-ASCII char (catches partial sequences
    # that the OS may have normalised slightly differently)
    for i, ch in enumerate(name):
        if ch == "\u00e2" and i + 1 < len(name) and ord(name[i + 1]) > 127:
            return True
    return False


def _fix_name(name: str) -> str:
    """Return the corrected version of a mojibake directory name."""
    result = name
    for bad, good in MOJIBAKE_MAP:
        result = result.replace(bad, good)
    return result


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_roots(roots: list[Path]) -> list[Path]:
    """Return all immediate child directories of roots that have mojibake names."""
    bad_dirs: list[Path] = []
    for root in roots:
        if not root.is_dir():
            print(f"WARNING: {root} is not a directory — skipping", file=sys.stderr)
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and _is_mojibake(child.name):
                bad_dirs.append(child)
    return bad_dirs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find and delete series directories with mojibake (UTF-8 decoded as Latin-1) in their names."
    )
    parser.add_argument(
        "roots",
        nargs="+",
        metavar="PATH",
        help="Library root directory (or directories) to scan, e.g. /mnt/manga-storage",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the directories (default is dry-run)",
    )
    args = parser.parse_args()

    roots = [Path(p) for p in args.roots]
    dry_run = not args.apply

    bad_dirs = scan_roots(roots)

    if not bad_dirs:
        print("No mojibake directories found.")
        return

    print(f"{'DRY RUN — ' if dry_run else ''}Found {len(bad_dirs)} mojibake director{'y' if len(bad_dirs) == 1 else 'ies'}:\n")

    to_delete_safely: list[Path] = []
    to_delete_warn: list[Path] = []

    for d in bad_dirs:
        fixed_name = _fix_name(d.name)
        fixed_path = d.parent / fixed_name
        has_corrected = fixed_path.exists() and fixed_path != d

        cbz_count = sum(1 for f in d.rglob("*.cbz"))
        status = "SAFE (corrected sibling exists)" if has_corrected else "WARN (no corrected sibling yet)"

        print(f"  [{status}]")
        print(f"    BAD:  {d}")
        if has_corrected:
            print(f"    GOOD: {fixed_path}")
        else:
            print(f"    WOULD BE: {fixed_path}")
        print(f"    Contents: {cbz_count} CBZ file(s)")
        print()

        if has_corrected:
            to_delete_safely.append(d)
        else:
            to_delete_warn.append(d)

    print("-" * 60)
    print(f"  Safe to delete (corrected sibling exists): {len(to_delete_safely)}")
    print(f"  Needs review   (no corrected sibling yet): {len(to_delete_warn)}")
    print("-" * 60)

    if dry_run:
        print("\nDry run — no changes made.")
        print("Re-run with --apply to delete the mojibake directories.")
        if to_delete_warn:
            print(
                "\nNOTE: For directories marked WARN, consider running the scraper first\n"
                "so it creates the correctly-named directory before you delete the old one."
            )
        return

    # --- Apply mode ---
    deleted = 0
    skipped = 0

    if to_delete_warn:
        print(
            f"\nWARNING: {len(to_delete_warn)} directory/directories have no corrected sibling yet.\n"
            "Deleting them now means losing those chapters until the scraper re-downloads them.\n"
        )
        answer = input("Delete ALL (including unmatched ones)? [y/N] ").strip().lower()
        if answer != "y":
            print("Skipping unmatched directories.")
            to_delete_warn = []

    all_to_delete = to_delete_safely + to_delete_warn

    for d in all_to_delete:
        try:
            shutil.rmtree(d)
            print(f"  DELETED: {d}")
            deleted += 1
        except Exception as e:
            print(f"  ERROR deleting {d}: {e}", file=sys.stderr)
            skipped += 1

    print(f"\nDone. Deleted {deleted}, skipped/errored {skipped}.")


if __name__ == "__main__":
    main()
