#!/usr/bin/env python3
"""
Fix genres in already-downloaded CBZ files by re-scraping series pages
and updating ComicInfo.xml inside ALL CBZ files for each series.
"""

import sys
import os
import re
import zipfile
import tempfile
import shutil
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from manhwa_scraper import ManhuaToScraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LIBRARY_DIR = Path(__file__).parent.parent / "library" / "Manhwa"

# Map series folder names to ManhuaTo URLs
# We'll auto-detect from the ComicInfo.xml <Web> tag inside CBZ files


def get_web_url_from_cbz(cbz_path: Path) -> str:
    """Extract the Web URL from ComicInfo.xml inside a CBZ file."""
    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            if 'ComicInfo.xml' in zf.namelist():
                content = zf.read('ComicInfo.xml').decode('utf-8')
                match = re.search(r'<Web>(.*?)</Web>', content)
                if match:
                    url = match.group(1)
                    # Convert chapter URL to series URL
                    # e.g., https://manhuato.com/manhua/hero-killer-chapter-1-ch29910
                    # -> https://manhuato.com/manhua/hero-killer/
                    url = url.replace('&amp;', '&')
                    # Extract series slug from chapter URL
                    slug_match = re.search(r'/manhua/([a-z0-9-]+?)(?:-chapter-\d|$)', url)
                    if slug_match:
                        return f"https://manhuato.com/manhua/{slug_match.group(1)}/"
    except Exception as e:
        logger.debug(f"Error reading CBZ {cbz_path}: {e}")
    return ""


def update_comicinfo_genres(cbz_path: Path, genres: list, status: str = ""):
    """Update the Genre and Tags fields in ComicInfo.xml inside a CBZ file."""
    try:
        genre_str = ', '.join(genres)

        # Read existing CBZ
        temp_path = cbz_path.with_suffix('.tmp')

        with zipfile.ZipFile(cbz_path, 'r') as zf_in:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zf_out:
                for item in zf_in.namelist():
                    data = zf_in.read(item)

                    if item == 'ComicInfo.xml':
                        content = data.decode('utf-8')

                        # Update Genre
                        if '<Genre>' in content:
                            content = re.sub(
                                r'<Genre>.*?</Genre>',
                                f'<Genre>{escape_xml(genre_str)}</Genre>',
                                content
                            )
                        else:
                            content = content.replace(
                                '</ComicInfo>',
                                f'  <Genre>{escape_xml(genre_str)}</Genre>\n</ComicInfo>'
                            )

                        # Update Tags
                        if '<Tags>' in content:
                            content = re.sub(
                                r'<Tags>.*?</Tags>',
                                f'<Tags>{escape_xml(genre_str)}</Tags>',
                                content
                            )
                        else:
                            content = content.replace(
                                '</ComicInfo>',
                                f'  <Tags>{escape_xml(genre_str)}</Tags>\n</ComicInfo>'
                            )

                        # Update status in Notes if available
                        if status and status != 'Unknown':
                            notes_text = f'Status: {status}'
                            if '<Notes>' in content:
                                content = re.sub(
                                    r'<Notes>.*?</Notes>',
                                    f'<Notes>{escape_xml(notes_text)}</Notes>',
                                    content
                                )
                            else:
                                content = content.replace(
                                    '</ComicInfo>',
                                    f'  <Notes>{escape_xml(notes_text)}</Notes>\n</ComicInfo>'
                                )

                        data = content.encode('utf-8')

                    zf_out.writestr(item, data)

        # Replace original with updated
        cbz_path.unlink()
        temp_path.rename(cbz_path)
        return True

    except Exception as e:
        logger.error(f"Error updating {cbz_path}: {e}")
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()
        return False


def escape_xml(text: str) -> str:
    if not text:
        return ""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;'))


def main():
    if not LIBRARY_DIR.exists():
        logger.error(f"Library directory not found: {LIBRARY_DIR}")
        return

    # Get all series directories
    series_dirs = [d for d in LIBRARY_DIR.iterdir() if d.is_dir()]
    logger.info(f"Found {len(series_dirs)} series directories")

    # Initialize scraper for fetching genre info
    scraper = ManhuaToScraper(headless=True)

    try:
        for series_dir in sorted(series_dirs):
            series_name = series_dir.name
            cbz_files = sorted(series_dir.glob("*.cbz"))

            if not cbz_files:
                continue

            # Get the series URL from the first CBZ
            series_url = get_web_url_from_cbz(cbz_files[0])

            if not series_url or 'manhuato.com' not in series_url:
                logger.info(f"Skipping {series_name} - no ManhuaTo URL found")
                continue

            logger.info(f"\nProcessing: {series_name}")
            logger.info(f"  URL: {series_url}")

            # Fetch genres from the series page
            try:
                from manhwa_scraper import Series
                series_obj = Series(
                    title=series_name,
                    url=series_url,
                    source="manhuato"
                )
                series_obj = scraper.get_series_details(series_obj)

                genres = series_obj.genres
                status = series_obj.status

                if not genres or genres == ['Manhwa']:
                    logger.warning(f"  No genres extracted for {series_name}")
                    continue

                logger.info(f"  Genres: {', '.join(genres)}")
                logger.info(f"  Status: {status}")

                # Update ALL CBZ files in this series
                updated = 0
                for cbz in cbz_files:
                    if update_comicinfo_genres(cbz, genres, status):
                        updated += 1

                logger.info(f"  Updated {updated}/{len(cbz_files)} CBZ files")

            except Exception as e:
                logger.error(f"  Error fetching details for {series_name}: {e}")
                continue

    finally:
        scraper._close_driver()

    logger.info("\nDone! Run a library scan in MangaShelf to pick up the updated genres.")


if __name__ == "__main__":
    main()
