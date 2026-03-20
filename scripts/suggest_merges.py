#!/usr/bin/env python3
"""
suggest_merges.py — Find near-duplicate [Manhuato] series directories and merge them.

Workflow
--------
Step 1 — Generate suggestions:
    python suggest_merges.py /mnt/manga-storage/Manhua --suggest merges.csv

    This writes a CSV like:
        dir_a, dir_b, similarity, chapters_a, chapters_b, action
        "[Manhuato] Gatekeeper Of The Boundless World", "[Manhuato] Gatekeeper Of The Boundless Worlds", 0.94, 45, 3,

Step 2 — Review the CSV:
    Open merges.csv in any spreadsheet / text editor.
    Fill the `action` column for each row:
        merge_into_a  →  move everything from dir_b into dir_a then delete dir_b
        merge_into_b  →  move everything from dir_a into dir_b then delete dir_a
        skip          →  do nothing (or leave it blank, both mean skip)

Step 3 — Apply approved merges:
    python suggest_merges.py /mnt/manga-storage/Manhua --apply --from-csv merges.csv

Options
-------
  --suggest FILE        Write candidate pairs to FILE (CSV). Dry run only.
  --from-csv FILE       Read a previously generated CSV and apply it.
  --apply               Required together with --from-csv to actually move files.
  --threshold N         Similarity threshold 0–100 (default 80). Lower = more candidates.
  --recursive           Scan all immediate subdirectories of library_dir.
  --update-xml          Also rewrite <Series> tag in ComicInfo.xml inside each CBZ.
"""

import argparse
import csv
import io
import re
import sys
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared normalization (mirrors fix_manhuato_duplicates.py)
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

# Additional stop-words used only for similarity comparison (not for naming).
_STOP_WORDS = _MINOR_WORDS | {'is', 'was', 'are', 'were'}


def _title_case(text: str) -> str:
    """Title-case that skips minor words and never capitalises after apostrophes."""
    words = text.split()
    result = []
    for i, word in enumerate(words):
        lower = word.lower()
        if i == 0 or lower not in _MINOR_WORDS:
            result.append(word[0].upper() + word[1:] if word else word)
        else:
            result.append(lower)
    return ' '.join(result)


def _strip_suffix(title: str) -> str:
    return _SUFFIX_RE.sub('', title).strip()


def _bare_title(dir_name: str) -> str:
    """Extract the series title without the [Manhuato] prefix or type suffix."""
    t = dir_name[len(_PREFIX):] if dir_name.startswith(_PREFIX) else dir_name
    return _title_case(_strip_suffix(t))


def _compare_key(title: str) -> str:
    """Lowercase, remove punctuation, drop stop-words for similarity comparison."""
    t = re.sub(r"[^\w\s]", " ", title.lower())
    words = [w for w in t.split() if w not in _STOP_WORDS]
    return " ".join(words)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _compare_key(a), _compare_key(b)).ratio()


def cbz_count(directory: Path) -> int:
    try:
        return len(list(directory.glob("*.cbz")))
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def canonical_cbz_name(cbz_stem: str, new_series_title: str) -> str:
    """Rename a CBZ stem to use the new series title."""
    m = re.match(r'^\[Manhuato\] .+? - (Chapter .+)$', cbz_stem)
    if not m:
        return cbz_stem
    return f"[Manhuato] {new_series_title} - {m.group(1)}"


def update_comicinfo(cbz_path: Path, new_series_title: str) -> None:
    try:
        with zipfile.ZipFile(cbz_path, 'r') as zin:
            if 'ComicInfo.xml' not in zin.namelist():
                return
            old_xml = zin.read('ComicInfo.xml').decode('utf-8', errors='replace')
        new_xml = re.sub(
            r'<Series>[^<]*</Series>',
            f'<Series>{new_series_title}</Series>',
            old_xml,
        )
        if new_xml == old_xml:
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(cbz_path, 'r') as zin, \
             zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = new_xml.encode('utf-8') if item.filename == 'ComicInfo.xml' \
                       else zin.read(item.filename)
                zout.writestr(item, data)
        cbz_path.write_bytes(buf.getvalue())
    except Exception as e:
        print(f"    WARNING: could not update ComicInfo.xml in {cbz_path.name}: {e}")


def merge_into(src: Path, dst: Path, new_title: str, update_xml: bool) -> None:
    """Move all CBZs from src into dst, renaming them to use new_title."""
    dst.mkdir(parents=True, exist_ok=True)
    for cbz in list(src.glob("*.cbz")):
        new_stem = canonical_cbz_name(cbz.stem, new_title)
        dest_file = dst / f"{new_stem}.cbz"
        if dest_file.exists():
            # Destination already has this chapter — source is a true duplicate, delete it.
            print(f"    DELETE duplicate: {cbz.name}")
            cbz.unlink()
        else:
            print(f"    MOVE: {cbz.name}")
            print(f"       -> {dest_file.name}")
            cbz.rename(dest_file)
            if update_xml:
                update_comicinfo(dest_file, new_title)

    # Move cover if target doesn't have one
    for cover in src.iterdir():
        if cover.stem.lower() == 'cover':
            dest_cover = dst / cover.name
            if not dest_cover.exists():
                print(f"    MOVE cover: {cover.name}")
                cover.rename(dest_cover)

    # Rename CBZs already in dst that still use old naming
    for cbz in list(dst.glob("*.cbz")):
        new_stem = canonical_cbz_name(cbz.stem, new_title)
        if new_stem != cbz.stem:
            new_path = dst / f"{new_stem}.cbz"
            if not new_path.exists():
                cbz.rename(new_path)

    remaining = list(src.iterdir())
    if not remaining:
        src.rmdir()
        print(f"    REMOVED empty dir: {src.name!r}")
    else:
        print(f"    WARNING: {src.name!r} not empty — {len(remaining)} file(s) remain")


# ---------------------------------------------------------------------------
# Step 1: suggest
# ---------------------------------------------------------------------------

def find_manhuato_dirs(root: Path) -> list[Path]:
    try:
        return sorted(d for d in root.iterdir()
                      if d.is_dir() and d.name.startswith(_PREFIX))
    except OSError:
        return []


def build_candidates(dirs: list[Path], threshold: float) -> list[dict]:
    """Return all pairs above the similarity threshold, sorted by similarity desc."""
    candidates = []
    titles = [(d, _bare_title(d.name)) for d in dirs]
    n = len(titles)
    for i in range(n):
        for j in range(i + 1, n):
            dir_a, title_a = titles[i]
            dir_b, title_b = titles[j]
            if title_a == title_b:
                continue  # identical after normalization — handled by fix_manhuato_duplicates
            sim = similarity(title_a, title_b)
            if sim >= threshold:
                candidates.append({
                    "dir_a": dir_a.name,
                    "dir_b": dir_b.name,
                    "similarity": round(sim, 4),
                    "title_a": title_a,
                    "title_b": title_b,
                    "chapters_a": cbz_count(dir_a),
                    "chapters_b": cbz_count(dir_b),
                    "action": "",
                })
    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    return candidates


CSV_FIELDS = ["dir_a", "dir_b", "similarity", "title_a", "title_b",
              "chapters_a", "chapters_b", "action"]


def write_csv(candidates: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(candidates)
    print(f"Wrote {len(candidates)} candidate pair(s) to {path}")
    print()
    print("Fill the 'action' column in the CSV:")
    print("  merge_into_a  — move dir_b's chapters into dir_a")
    print("  merge_into_b  — move dir_a's chapters into dir_b")
    print("  skip          — leave both as-is (blank also means skip)")
    print()
    print("Then run:")
    print(f"  python suggest_merges.py <library_dir> --apply --from-csv {path}")


# ---------------------------------------------------------------------------
# Step 2: apply from CSV
# ---------------------------------------------------------------------------

def apply_csv(csv_path: Path, library_dir: Path, update_xml: bool) -> None:
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    actionable = [r for r in rows if r.get("action", "").strip().lower()
                  in ("merge_into_a", "merge_into_b")]

    if not actionable:
        print("No rows with action=merge_into_a or merge_into_b found. Nothing to do.")
        return

    print(f"Processing {len(actionable)} merge(s)...\n")

    for row in actionable:
        action = row["action"].strip().lower()
        dir_a = library_dir / row["dir_a"]
        dir_b = library_dir / row["dir_b"]

        if action == "merge_into_a":
            src, dst = dir_b, dir_a
        else:
            src, dst = dir_a, dir_b

        new_title = _bare_title(dst.name)
        print(f"MERGE: {src.name!r}")
        print(f"  ->   {dst.name!r}  (title: {new_title!r})")

        if not src.exists():
            print(f"  SKIP: source dir does not exist (already merged?)\n")
            continue
        if not dst.exists():
            print(f"  SKIP: destination dir does not exist\n")
            continue

        merge_into(src, dst, new_title, update_xml)
        print()

    print("Done.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def collect_dirs(library_dir: Path, recursive: bool) -> list[tuple[Path, list[Path]]]:
    """Return (root, dirs) pairs to process."""
    if recursive:
        result = []
        for sub in sorted(library_dir.iterdir()):
            if sub.is_dir():
                dirs = find_manhuato_dirs(sub)
                if dirs:
                    result.append((sub, dirs))
        return result
    return [(library_dir, find_manhuato_dirs(library_dir))]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find near-duplicate [Manhuato] dirs and merge them."
    )
    parser.add_argument("library_dir", help="Directory containing [Manhuato] folders")
    parser.add_argument("--suggest", metavar="FILE",
                        help="Write candidate pairs to CSV file")
    parser.add_argument("--from-csv", metavar="FILE",
                        help="Apply merges from a reviewed CSV file")
    parser.add_argument("--apply", action="store_true",
                        help="Required with --from-csv to actually move files")
    parser.add_argument("--threshold", type=int, default=80,
                        help="Similarity threshold 0-100 (default 80)")
    parser.add_argument("--recursive", action="store_true",
                        help="Scan immediate subdirectories of library_dir")
    parser.add_argument("--update-xml", action="store_true",
                        help="Rewrite <Series> tag inside CBZ ComicInfo.xml files")
    args = parser.parse_args()

    library_dir = Path(args.library_dir)
    if not library_dir.is_dir():
        print(f"ERROR: {library_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # --- Apply mode ---
    if args.from_csv:
        if not args.apply:
            print("ERROR: --from-csv requires --apply to make changes.", file=sys.stderr)
            print("  Add --apply to the command to proceed.")
            sys.exit(1)
        apply_csv(Path(args.from_csv), library_dir, args.update_xml)
        return

    # --- Suggest mode ---
    if not args.suggest:
        parser.print_help()
        sys.exit(0)

    threshold = args.threshold / 100.0
    roots = collect_dirs(library_dir, args.recursive)

    all_candidates: list[dict] = []
    for root, dirs in roots:
        print(f"Scanning {root} ({len(dirs)} [Manhuato] dirs)...")
        candidates = build_candidates(dirs, threshold)
        # Prefix dir names with subdir for --recursive so apply_csv can find them
        if args.recursive:
            rel = root.relative_to(library_dir)
            for c in candidates:
                c["dir_a"] = str(rel / c["dir_a"])
                c["dir_b"] = str(rel / c["dir_b"])
        all_candidates.extend(candidates)

    if not all_candidates:
        print(f"No pairs above {args.threshold}% similarity found.")
        return

    print(f"\nFound {len(all_candidates)} candidate pair(s) above {args.threshold}% similarity:\n")
    for c in all_candidates:
        pct = int(c["similarity"] * 100)
        print(f"  {pct:3d}%  {c['title_a']!r}  ({c['chapters_a']} ch)")
        print(f"        {c['title_b']!r}  ({c['chapters_b']} ch)")
        print()

    write_csv(all_candidates, Path(args.suggest))


if __name__ == "__main__":
    main()
