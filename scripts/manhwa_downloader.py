#!/usr/bin/env python3
"""
manhwa_downloader.py - Download manhwa/manhua from specific scanlation sites

Supports:
- asuracomic.net (Asura Scans)
- flamecomics.xyz (Flame Comics)  
- drakecomic.org (Drake Comics)
- Similar sites using common themes

Usage:
    python manhwa_downloader.py --url "https://asuracomic.net/series/..." --output /path/to/library/Manhwa
    python manhwa_downloader.py --config sources.yaml --auto
"""

import argparse
import os
import re
import sys
import time
import json
import yaml
import zipfile
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install requests beautifulsoup4 selenium webdriver-manager pyyaml")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Chapter:
    """Represents a manga chapter"""
    number: str
    title: str
    url: str
    downloaded: bool = False


@dataclass
class Series:
    """Represents a manga series"""
    title: str
    url: str
    source: str
    chapters: List[Chapter] = field(default_factory=list)
    

class BaseScraper:
    """Base class for all scrapers"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def _init_driver(self):
        """Initialize Selenium WebDriver"""
        if self.driver:
            return
            
        options = Options()
        if self.headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.implicitly_wait(10)
    
    def _close_driver(self):
        """Close WebDriver"""
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    def _get_soup(self, url: str, use_selenium: bool = False) -> BeautifulSoup:
        """Get BeautifulSoup object from URL"""
        if use_selenium:
            self._init_driver()
            self.driver.get(url)
            time.sleep(2)  # Wait for dynamic content
            html = self.driver.page_source
        else:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            html = response.text
        
        return BeautifulSoup(html, 'html.parser')
    
    def search(self, query: str) -> List[Series]:
        """Search for manga - override in subclass"""
        raise NotImplementedError
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        """Get chapters for a series - override in subclass"""
        raise NotImplementedError
    
    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter - override in subclass"""
        raise NotImplementedError
    
    def download_chapter(self, chapter: Chapter, series_title: str, output_dir: Path) -> bool:
        """Download a chapter and create CBZ"""
        safe_title = self._sanitize_filename(series_title)
        safe_chapter = self._sanitize_filename(chapter.number)

        series_dir = output_dir / safe_title
        # Guard against path traversal: series_dir must stay inside output_dir
        try:
            series_dir.resolve().relative_to(output_dir.resolve())
        except ValueError:
            logger.error(f"Path traversal detected for title '{series_title}' — skipping")
            return False
        series_dir.mkdir(parents=True, exist_ok=True)
        
        cbz_name = f"{safe_title} - Chapter {safe_chapter}.cbz"
        cbz_path = series_dir / cbz_name
        
        if cbz_path.exists():
            logger.info(f"Already exists: {cbz_name}")
            return True
        
        logger.info(f"Downloading: {series_title} - Chapter {chapter.number}")
        
        try:
            pages = self.get_pages(chapter)
            if not pages:
                logger.error(f"No pages found for chapter {chapter.number}")
                return False
            
            # Create temp directory for images
            temp_dir = series_dir / f".temp_{safe_chapter}"
            temp_dir.mkdir(exist_ok=True)
            
            # Download images
            success_count = 0
            for i, page_url in enumerate(pages, 1):
                ext = self._get_extension(page_url)
                img_path = temp_dir / f"{i:03d}{ext}"

                if not self._download_image(page_url, img_path, chapter.url):
                    logger.warning(f"Failed to download page {i}")
                    continue
                success_count += 1

            if success_count == 0:
                logger.error(f"No images downloaded for chapter {chapter.number} — skipping CBZ creation")
                for f in temp_dir.iterdir():
                    f.unlink()
                temp_dir.rmdir()
                return False

            # Create CBZ
            self._create_cbz(temp_dir, cbz_path)

            # Cleanup
            for f in temp_dir.iterdir():
                f.unlink()
            temp_dir.rmdir()

            logger.info(f"Created: {cbz_name} ({success_count} pages)")
            return True
            
        except Exception as e:
            logger.error(f"Error downloading chapter: {e}")
            return False
    
    # Allowlisted CDN/image domains — only images from these are downloaded
    _ALLOWED_IMAGE_DOMAINS = (
        'asuracomic.net', 'asura.gg', 'asuratoon.com',
        'flamecomics.xyz', 'flamecomics.me',
        'drakecomic.org',
        'manhuato.com', 'cdn.manhuato.com',
        'webtoons.com', 'webtoon.com',
        'imgur.com', 'i.imgur.com',
        'cloudflare.com', 'cdnjs.cloudflare.com',
    )

    def _is_allowed_image_url(self, url: str) -> bool:
        """Return True only if the URL's host is in the allowed-domains list."""
        from urllib.parse import urlparse
        try:
            host = urlparse(url).hostname or ''
            return any(host == d or host.endswith('.' + d) for d in self._ALLOWED_IMAGE_DOMAINS)
        except Exception:
            return False

    def _download_image(self, url: str, path: Path, referer: str) -> bool:
        """Download an image file from an allowed domain only."""
        if not self._is_allowed_image_url(url):
            logger.warning(f"Blocked image download from untrusted host: {url}")
            return False
        try:
            headers = {
                'Referer': referer,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = self.session.get(url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()
            # Enforce a 50 MB per-image size cap to prevent disk exhaustion
            max_bytes = 50 * 1024 * 1024
            data = b''
            for chunk in response.iter_content(65536):
                data += chunk
                if len(data) > max_bytes:
                    logger.warning(f"Image too large (>{max_bytes // 1024 // 1024} MB), skipping: {url}")
                    return False
            if len(data) < 512:
                return False
            path.write_bytes(data)
            return True
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return False
    
    def _create_cbz(self, source_dir: Path, output_path: Path):
        """Create CBZ archive from images"""
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for img_file in sorted(source_dir.iterdir()):
                if img_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                    zf.write(img_file, img_file.name)
    
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize filename for filesystem, preventing path traversal."""
        # Remove null bytes and control characters
        name = name.replace('\x00', '')
        # Remove filesystem-invalid characters
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        # Collapse whitespace
        name = re.sub(r'\s+', ' ', name)
        name = name.strip()
        # Remove leading dots to prevent hidden-file or traversal tricks (e.g. "..", ".")
        # Strip again after removing dots to catch ".. evil" -> " evil" -> "evil"
        name = name.lstrip('.').strip()
        if not name:
            name = '_unnamed'
        return name[:200]
    
    @staticmethod
    def _get_extension(url: str) -> str:
        """Get file extension from the URL path (not query string or fragment)."""
        from urllib.parse import urlparse
        from pathlib import PurePosixPath
        try:
            path = PurePosixPath(urlparse(url).path)
            ext = path.suffix.lower()
            if ext in ('.png', '.webp', '.gif', '.jpg', '.jpeg'):
                return ext
        except Exception:
            pass
        return '.jpg'


class AsuraScraper(BaseScraper):
    """Scraper for asuracomic.net"""
    
    BASE_URL = "https://asuracomic.net"
    
    def search(self, query: str) -> List[Series]:
        url = f"{self.BASE_URL}/series?name={query.replace(' ', '+')}"
        soup = self._get_soup(url, use_selenium=True)
        
        results = []
        for item in soup.select('.grid > a[href*="/series/"]'):
            title_elem = item.select_one('span.block')
            if title_elem:
                results.append(Series(
                    title=title_elem.text.strip(),
                    url=item['href'] if item['href'].startswith('http') else self.BASE_URL + item['href'],
                    source='asura'
                ))
        
        return results
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        soup = self._get_soup(series.url, use_selenium=True)
        
        chapters = []
        for link in soup.select('div[class*="scrollbar"] a[href*="chapter"]'):
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', text, re.I)
            if match:
                num = match.group(1)
            else:
                num = text
            
            chapters.append(Chapter(
                number=num,
                title=text,
                url=href if href.startswith('http') else self.BASE_URL + href
            ))
        
        # Reverse to get oldest first
        chapters.reverse()
        return chapters
    
    def get_pages(self, chapter: Chapter) -> List[str]:
        soup = self._get_soup(chapter.url, use_selenium=True)
        
        pages = []
        for img in soup.select('img[alt*="chapter"], div[class*="container"] img'):
            src = img.get('src', '')
            if src and 'logo' not in src.lower() and 'icon' not in src.lower():
                if src not in pages:
                    pages.append(src)
        
        return pages


class FlameComicsScraper(BaseScraper):
    """Scraper for flamecomics.xyz"""
    
    BASE_URL = "https://flamecomics.xyz"
    
    def search(self, query: str) -> List[Series]:
        url = f"{self.BASE_URL}/?s={query.replace(' ', '+')}&post_type=wp-manga"
        soup = self._get_soup(url, use_selenium=True)
        
        results = []
        for item in soup.select('.c-tabs-item__content, .post-title'):
            link = item.select_one('a')
            if link and link.get('href'):
                results.append(Series(
                    title=link.text.strip(),
                    url=link['href'],
                    source='flame'
                ))
        
        return results
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        soup = self._get_soup(series.url, use_selenium=True)
        
        chapters = []
        for link in soup.select('.wp-manga-chapter a'):
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', text, re.I)
            num = match.group(1) if match else text
            
            chapters.append(Chapter(
                number=num,
                title=text,
                url=href
            ))
        
        chapters.reverse()
        return chapters
    
    def get_pages(self, chapter: Chapter) -> List[str]:
        soup = self._get_soup(chapter.url, use_selenium=True)
        
        pages = []
        for img in soup.select('.reading-content img'):
            src = img.get('data-src') or img.get('src', '')
            src = src.strip()
            if src and 'logo' not in src.lower():
                pages.append(src)
        
        return pages


class DrakeComicsScraper(BaseScraper):
    """Scraper for drakecomic.org"""
    
    BASE_URL = "https://drakecomic.org"
    
    def search(self, query: str) -> List[Series]:
        url = f"{self.BASE_URL}/?s={query.replace(' ', '+')}"
        soup = self._get_soup(url, use_selenium=True)
        
        results = []
        for item in soup.select('.listupd .bsx a, .bs a'):
            href = item.get('href', '')
            title = item.get('title') or item.select_one('.tt, .title')
            if title:
                title = title.text.strip() if hasattr(title, 'text') else title
                results.append(Series(
                    title=title,
                    url=href if href.startswith('http') else self.BASE_URL + href,
                    source='drake'
                ))
        
        return results
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        soup = self._get_soup(series.url, use_selenium=True)
        
        chapters = []
        for link in soup.select('#chapterlist li a, .eplister li a'):
            href = link.get('href', '')
            num_elem = link.select_one('.chapternum, .epl-num')
            text = num_elem.text.strip() if num_elem else link.get_text(strip=True)
            
            match = re.search(r'(\d+(?:\.\d+)?)', text)
            num = match.group(1) if match else text
            
            chapters.append(Chapter(
                number=num,
                title=text,
                url=href if href.startswith('http') else self.BASE_URL + href
            ))
        
        chapters.reverse()
        return chapters
    
    def get_pages(self, chapter: Chapter) -> List[str]:
        soup = self._get_soup(chapter.url, use_selenium=True)
        
        pages = []
        for img in soup.select('#readerarea img, .chapter-content img'):
            src = img.get('data-src') or img.get('src', '')
            src = src.strip()
            if src and 'logo' not in src.lower() and 'icon' not in src.lower():
                pages.append(src)
        
        return pages


# Factory to get scraper by source name
SCRAPERS = {
    'asura': AsuraScraper,
    'asuracomic': AsuraScraper,
    'asuracomic.net': AsuraScraper,
    'flame': FlameComicsScraper,
    'flamecomics': FlameComicsScraper,
    'flamecomics.xyz': FlameComicsScraper,
    'drake': DrakeComicsScraper,
    'drakecomic': DrakeComicsScraper,
    'drakecomic.org': DrakeComicsScraper,
}


def get_scraper(source: str, headless: bool = True) -> BaseScraper:
    """Get scraper instance by source name or URL"""
    source_lower = source.lower()
    
    for key, scraper_class in SCRAPERS.items():
        if key in source_lower:
            return scraper_class(headless=headless)
    
    raise ValueError(f"Unknown source: {source}")


def download_from_url(url: str, output_dir: Path, headless: bool = True):
    """Download all chapters from a series URL"""
    from urllib.parse import urlparse
    scraper = get_scraper(url, headless)

    # Create a series object from the URL
    series = Series(title="", url=url, source="auto")

    # Get series info
    soup = scraper._get_soup(url, use_selenium=True)
    title_elem = soup.select_one('h1, .entry-title, .post-title')
    if title_elem:
        series.title = title_elem.get_text(strip=True).strip()

    # Fall back to the last path segment of the URL so we never collide on "Unknown"
    if not series.title:
        path_parts = [p for p in urlparse(url).path.rstrip('/').split('/') if p]
        series.title = path_parts[-1].replace('-', ' ').title() if path_parts else 'Unknown'
        logger.warning(f"Could not detect series title, using URL slug: {series.title}")

    logger.info(f"Found series: {series.title}")
    
    # Get chapters
    chapters = scraper.get_chapters(series)
    logger.info(f"Found {len(chapters)} chapters")
    
    # Download all chapters
    for chapter in chapters:
        scraper.download_chapter(chapter, series.title, output_dir)
    
    scraper._close_driver()


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file"""
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description='Download manhwa from various sources')
    parser.add_argument('--url', help='URL of series to download')
    parser.add_argument('--output', '-o', default='./library/Manhwa', help='Output directory')
    parser.add_argument('--config', '-c', help='Config file with series list')
    parser.add_argument('--headless', action='store_true', default=True, help='Run browser headless')
    parser.add_argument('--visible', action='store_true', help='Show browser window')
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    headless = not args.visible
    
    if args.url:
        download_from_url(args.url, output_dir, headless)
    elif args.config:
        config = load_config(Path(args.config))
        for series_config in config.get('series', []):
            url = series_config.get('url')
            if url:
                download_from_url(url, output_dir, headless)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
