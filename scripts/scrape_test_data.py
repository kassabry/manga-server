#!/usr/bin/env python3
"""
Quick script to scrape 10 series x 10 chapters from ManhuaTo for testing MangaShelf.
Downloads into the library/Manhwa folder.
"""

import sys
import os
import logging

# Add scripts dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from manhwa_scraper import ManhuaToScraper, ProgressTracker, Series
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_SERIES = 10
MAX_CHAPTERS_PER_SERIES = 10
OUTPUT_DIR = Path(__file__).parent.parent / "library" / "Manhwa"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = OUTPUT_DIR / '.download_progress.pkl'
    tracker = ProgressTracker(cache_file)

    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info(f"Will download up to {MAX_SERIES} series, {MAX_CHAPTERS_PER_SERIES} chapters each")

    # Initialize scraper (headless browser)
    scraper = ManhuaToScraper(headless=True, limit=MAX_SERIES)

    try:
        # Step 1: Get series list
        logger.info("Fetching series list from ManhuaTo...")
        series_list = scraper.get_all_series(content_type="manhwa")

        if not series_list:
            logger.error("No series found! The site may be blocking requests.")
            return

        # Limit to MAX_SERIES
        series_list = series_list[:MAX_SERIES]
        logger.info(f"Found {len(series_list)} series to download")

        # Step 2: Download chapters for each series
        for i, series in enumerate(series_list, 1):
            logger.info(f"\n[{i}/{len(series_list)}] Processing: {series.title}")

            try:
                # Get full series details (metadata, genres, etc.)
                series = scraper.get_series_details(series)
                logger.info(f"  Genres: {', '.join(series.genres)}")
                logger.info(f"  Status: {series.status}")

                # Get chapter list
                chapters = scraper.get_chapters(series)
                logger.info(f"  Found {len(chapters)} chapters total")

                if not chapters:
                    logger.warning(f"  No chapters found for {series.title}, skipping")
                    continue

                # Only download first MAX_CHAPTERS_PER_SERIES chapters
                chapters_to_download = chapters[:MAX_CHAPTERS_PER_SERIES]
                logger.info(f"  Downloading {len(chapters_to_download)} chapters...")

                for j, chapter in enumerate(chapters_to_download, 1):
                    logger.info(f"  [{j}/{len(chapters_to_download)}] Chapter {chapter.number}")
                    try:
                        scraper.download_chapter(
                            chapter, series.title, OUTPUT_DIR, tracker, series
                        )
                    except Exception as e:
                        logger.error(f"    Error downloading chapter {chapter.number}: {e}")
                        continue

            except Exception as e:
                logger.error(f"  Error processing {series.title}: {e}")
                continue

        logger.info(f"\nDone! Downloaded test data to: {OUTPUT_DIR}")

    finally:
        scraper._close_driver()


if __name__ == "__main__":
    main()
