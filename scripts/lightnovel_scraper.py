#!/usr/bin/env python3
"""
lightnovel_scraper.py - Light Novel scraper with EPUB output for Kavita

Features:
- Scrape light novels from popular sites
- Export as EPUB (Kavita-compatible)
- Include metadata (title, author, description, cover)
- Chapter-by-chapter or full volume downloads
- Resume interrupted downloads

Supports:
- lightnovelpub.org
- novelbin.me
- readlightnovel.me

Usage:
    # List all novels from a site
    python lightnovel_scraper.py --site lightnovelpub --list-all -o novels.yaml
    
    # Download a specific novel
    python lightnovel_scraper.py --site lightnovelpub --novel "solo-leveling" -o ./library/LightNovels
    
    # Download from a curated list
    python lightnovel_scraper.py --config my_novels.yaml -o ./library/LightNovels
"""

import argparse
import copy
import os
import re
import sys
import time
import json
import random
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import pickle

try:
    import requests
    from bs4 import BeautifulSoup
    import yaml
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install requests beautifulsoup4 pyyaml")
    sys.exit(1)

# EPUB creation
try:
    from ebooklib import epub
    HAS_EBOOKLIB = True
except ImportError:
    HAS_EBOOKLIB = False
    print("Warning: ebooklib not installed. Install with: pip install ebooklib")
    print("EPUB creation will be disabled.")

# Optional Selenium for JS-heavy sites
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# Prefer undetected-chromedriver for anti-bot bypass
try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Chapter:
    """Represents a light novel chapter"""
    number: str
    title: str
    url: str
    content: str = ""


@dataclass
class Novel:
    """Represents a light novel"""
    title: str
    url: str
    source: str
    author: str = ""
    genres: List[str] = field(default_factory=list)
    status: str = ""
    chapters_count: int = 0
    rating: float = 0.0
    description: str = ""
    cover_url: str = ""
    enabled: bool = True


class ProgressTracker:
    """Track download progress to allow resuming"""
    
    def __init__(self, cache_file: Path):
        self.cache_file = cache_file
        self.downloaded: set = set()
        self._load()
    
    def _load(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'rb') as f:
                    self.downloaded = pickle.load(f)
            except:
                self.downloaded = set()
    
    def _save(self):
        with open(self.cache_file, 'wb') as f:
            pickle.dump(self.downloaded, f)
    
    def is_downloaded(self, url: str) -> bool:
        return url in self.downloaded
    
    def mark_downloaded(self, url: str):
        self.downloaded.add(url)
        self._save()


class BaseLightNovelScraper:
    """Base class for light novel scrapers"""
    
    BASE_URL = ""
    SITE_NAME = ""
    
    def __init__(self, headless: bool = True, limit: int = None):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        self.headless = headless
        self.limit = limit
        self.driver = None
    
    def _detect_chrome_version(self) -> Optional[int]:
        """Detect installed Chrome version"""
        import subprocess
        try:
            # Windows
            result = subprocess.run(
                ['reg', 'query', r'HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon', '/v', 'version'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                match = re.search(r'(\d+)\.', result.stdout)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        # Linux - try multiple browser names
        for browser in ['google-chrome', 'chromium-browser', 'chromium']:
            try:
                import subprocess as sp
                result = sp.run([browser, '--version'], capture_output=True, text=True, timeout=5)
                match = re.search(r'(\d+)\.', result.stdout)
                if match:
                    return int(match.group(1))
            except Exception:
                pass
        return None

    def _is_arm(self):
        """Check if running on ARM architecture"""
        import platform
        machine = platform.machine().lower()
        return machine in ('aarch64', 'armv7l', 'armv6l', 'arm64')

    def _find_system_chromedriver(self):
        """Find system-installed chromedriver binary"""
        import shutil
        for name in ['chromedriver', 'chromium.chromedriver']:
            path = shutil.which(name)
            if path:
                return path
        for path in ['/usr/bin/chromedriver', '/usr/lib/chromium/chromedriver',
                     '/usr/lib/chromium-browser/chromedriver', '/snap/bin/chromium.chromedriver']:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return None

    def _find_chromium_binary(self):
        """Find system-installed Chromium browser binary"""
        import shutil
        for name in ['chromium', 'chromium-browser', 'google-chrome']:
            path = shutil.which(name)
            if path:
                return path
        for path in ['/usr/bin/chromium', '/usr/bin/chromium-browser',
                     '/snap/bin/chromium']:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return None

    def _init_selenium(self):
        """Initialize Selenium WebDriver (prefers undetected-chromedriver)"""
        if self.driver is not None:
            return

        if HAS_UC:
            logger.info("Using undetected-chromedriver")
            options = uc.ChromeOptions()
            if self.headless:
                options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')

            try:
                chrome_version = self._detect_chrome_version()
                if chrome_version:
                    logger.info(f"Detected Chrome version: {chrome_version}")
                    self.driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_version)
                else:
                    self.driver = uc.Chrome(options=options, use_subprocess=True)
                self.driver.implicitly_wait(10)
                return
            except Exception as e:
                logger.warning(f"undetected-chromedriver failed: {e}, falling back to regular selenium")

        if not HAS_SELENIUM:
            raise RuntimeError("Selenium not installed")

        options = Options()
        if self.headless:
            options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

        # On ARM (Raspberry Pi), use system-installed chromedriver directly
        if self._is_arm():
            chromium_bin = self._find_chromium_binary()
            if chromium_bin:
                logger.info(f"ARM detected - using Chromium binary: {chromium_bin}")
                options.binary_location = chromium_bin
            system_driver = self._find_system_chromedriver()
            if system_driver:
                logger.info(f"ARM detected - using system chromedriver: {system_driver}")
                service = Service(system_driver)
                self.driver = webdriver.Chrome(service=service, options=options)
            else:
                self.driver = webdriver.Chrome(options=options)
        else:
            self.driver = webdriver.Chrome(options=options)
    
    def _close_driver(self):
        """Close Selenium driver"""
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    def _get_soup(self, url: str, use_selenium: bool = False) -> BeautifulSoup:
        """Get BeautifulSoup object from URL"""
        if use_selenium:
            self._init_selenium()
            self.driver.get(url)
            time.sleep(2)  # Wait for JS
            html = self.driver.page_source
        else:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            html = response.text
        
        return BeautifulSoup(html, 'html.parser')
    
    def get_all_novels(self) -> List[Novel]:
        """Get all novels from the site - override in subclass"""
        raise NotImplementedError

    def get_popular_novels(self, max_pages: int = 10) -> List[Novel]:
        """Get most popular novels from the site - override in subclass.
        Defaults to get_all_novels() if not overridden."""
        return self.get_all_novels()

    def get_novel_details(self, novel: Novel) -> Novel:
        """Fetch full details for a novel - override in subclass"""
        raise NotImplementedError
    
    def get_chapters(self, novel: Novel) -> List[Chapter]:
        """Get all chapters for a novel - override in subclass"""
        raise NotImplementedError
    
    def get_chapter_content(self, chapter: Chapter) -> str:
        """Get content for a chapter - override in subclass"""
        raise NotImplementedError
    
    def download_cover(self, novel: Novel, output_dir: Path) -> Optional[Path]:
        """Download cover image"""
        if not novel.cover_url:
            return None
        
        try:
            response = self.session.get(novel.cover_url, timeout=30)
            response.raise_for_status()
            
            # Determine extension
            content_type = response.headers.get('content-type', '')
            if 'png' in content_type:
                ext = '.png'
            elif 'gif' in content_type:
                ext = '.gif'
            else:
                ext = '.jpg'
            
            cover_path = output_dir / f"cover{ext}"
            with open(cover_path, 'wb') as f:
                f.write(response.content)
            
            return cover_path
        except Exception as e:
            logger.warning(f"Failed to download cover: {e}")
            return None
    
    def create_epub(self, novel: Novel, chapters: List[Chapter], output_dir: Path, volume_number: int = 1) -> Path:
        """Create EPUB file from novel and chapters with Kavita-compatible metadata.

        Kavita reads the following OPF metadata from EPUB files:
        - dc:title         -> Chapter/Book Title
        - dc:creator       -> Author (with role meta for writer/artist/etc.)
        - dc:description   -> Summary
        - dc:subject       -> Genres (one per entry)
        - dc:publisher     -> Publisher
        - dc:language      -> Language
        - dc:identifier    -> Unique ID / ISBN
        - calibre:series   -> Series Name (groups volumes together)
        - calibre:series_index -> Volume number within series
        - calibre:rating   -> Rating (0-5 scale)
        - belongs-to-collection (EPUB3) -> Collection grouping

        IMPORTANT: Kavita requires 'Vol.' in the filename to parse EPUB files.
        Without it, the scanner reports 'Unable to parse any meaningful information'.
        """
        if not HAS_EBOOKLIB:
            raise RuntimeError("ebooklib not installed. Install with: pip install ebooklib")

        safe_title = self._sanitize_filename(novel.title)
        epub_path = output_dir / f"{safe_title} Vol. {volume_number}.epub"

        # Create EPUB book
        book = epub.EpubBook()

        # Core metadata
        book.set_identifier(f"lightnovel-{novel.source}-{safe_title}")
        book.set_title(novel.title)
        book.set_language('en')

        if novel.author:
            book.add_author(novel.author)

        if novel.description:
            book.add_metadata('DC', 'description', novel.description)

        # Genres as dc:subject (Kavita reads each as a tag/genre)
        for genre in novel.genres:
            book.add_metadata('DC', 'subject', genre)

        # Publisher - use source site name
        source_publishers = {
            'lightnovelpub': 'LightNovelPub',
            'novelbin': 'NovelBin',
            'readlightnovel': 'ReadLightNovel',
        }
        publisher = source_publishers.get(novel.source, novel.source.title() if novel.source else '')
        if publisher:
            book.add_metadata('DC', 'publisher', publisher)

        # Calibre series metadata (Kavita uses this to group books into a series)
        book.add_metadata(None, 'meta', novel.title, {'name': 'calibre:series'})
        book.add_metadata(None, 'meta', str(volume_number), {'name': 'calibre:series_index'})

        # Rating as calibre metadata (Kavita reads calibre:rating)
        if novel.rating > 0:
            book.add_metadata(None, 'meta', str(novel.rating), {'name': 'calibre:rating'})

        # EPUB3 collection metadata (Kavita also reads belongs-to-collection)
        book.add_metadata(None, 'meta', novel.title,
                          {'property': 'belongs-to-collection', 'id': 'series-id'})
        book.add_metadata(None, 'meta', str(volume_number),
                          {'refines': '#series-id', 'property': 'group-position'})
        book.add_metadata(None, 'meta', 'series',
                          {'refines': '#series-id', 'property': 'collection-type'})

        # Status as custom metadata
        if novel.status:
            book.add_metadata(None, 'meta', novel.status, {'name': 'calibre:user_metadata:status'})

        # Add cover if available
        if novel.cover_url:
            try:
                response = self.session.get(novel.cover_url, timeout=30)
                if response.status_code == 200:
                    cover_content = response.content
                    # Determine type from URL or content-type header
                    content_type = response.headers.get('content-type', '')
                    if novel.cover_url.endswith('.png') or 'png' in content_type:
                        cover_name = 'cover.png'
                    else:
                        cover_name = 'cover.jpg'

                    book.set_cover(cover_name, cover_content)
            except Exception as e:
                logger.warning(f"Failed to add cover: {e}")

        # Create chapters
        epub_chapters = []
        for i, chapter in enumerate(chapters, 1):
            c = epub.EpubHtml(
                title=chapter.title,
                file_name=f'chapter_{i:04d}.xhtml',
                lang='en'
            )

            # Clean and format content
            content = self._clean_chapter_content(chapter.content)
            c.content = (
                '<html><head><title>' + chapter.title + '</title>'
                '<link rel="stylesheet" type="text/css" href="../style/nav.css"/>'
                '</head><body>'
                '<h1>' + chapter.title + '</h1>'
                + content +
                '</body></html>'
            )

            book.add_item(c)
            epub_chapters.append(c)

        # Add navigation
        book.toc = [(epub.Section('Chapters'), epub_chapters)]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # Add CSS
        style = '''
        body { font-family: Georgia, "Times New Roman", serif; line-height: 1.8; padding: 1em 2em; max-width: 40em; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 2em; font-size: 1.5em; }
        p { text-indent: 1.5em; margin: 0.5em 0; }
        .chapter-content p:first-child { text-indent: 0; }
        '''
        nav_css = epub.EpubItem(
            uid="style_nav",
            file_name="style/nav.css",
            media_type="text/css",
            content=style
        )
        book.add_item(nav_css)

        # Set spine
        book.spine = ['nav'] + epub_chapters

        # Write EPUB
        epub.write_epub(str(epub_path), book, {})

        return epub_path
    
    def _clean_chapter_content(self, content: str) -> str:
        """Clean chapter content for EPUB"""
        # If content is already HTML, parse and clean it
        soup = BeautifulSoup(content, 'html.parser')
        
        # Remove scripts, styles, ads
        for tag in soup.find_all(['script', 'style', 'iframe', 'ins', 'amp-ad']):
            tag.decompose()
        
        # Remove common ad class elements
        for tag in soup.find_all(class_=re.compile(r'(ad|ads|advert|banner|sponsor)', re.I)):
            tag.decompose()
        
        # Get text content, preserving paragraphs
        paragraphs = []
        for p in soup.find_all(['p', 'div']):
            text = p.get_text(strip=True)
            if text and len(text) > 10:  # Skip very short elements (likely not content)
                paragraphs.append(f"<p>{text}</p>")
        
        if paragraphs:
            return '\n'.join(paragraphs)
        
        # Fallback: just return cleaned text
        text = soup.get_text()
        # Split into paragraphs by double newlines
        parts = re.split(r'\n\s*\n', text)
        return '\n'.join(f"<p>{p.strip()}</p>" for p in parts if p.strip())
    
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize filename for filesystem"""
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        name = re.sub(r'\s+', ' ', name)
        name = name.strip()
        return name[:200]
    
    def enrich_with_details(self, novels: List[Novel], show_progress: bool = True) -> List[Novel]:
        """Fetch full details for all novels"""
        total = len(novels)
        for i, novel in enumerate(novels, 1):
            if show_progress:
                logger.info(f"[{i}/{total}] Getting details for: {novel.title}")
            
            novel = self.get_novel_details(novel)
            
            if show_progress:
                rating_str = f" ★{novel.rating}" if novel.rating > 0 else ""
                status_str = f" ({novel.status})" if novel.status else ""
                logger.info(f"    → {novel.chapters_count} chapters{status_str}{rating_str}")
            
            time.sleep(random.uniform(0.5, 1.5))
        
        return novels


class LightNovelPubScraper(BaseLightNovelScraper):
    """Scraper for lightnovelpub.org"""

    BASE_URL = "https://lightnovelpub.org"
    SITE_NAME = "lightnovelpub"

    def __init__(self, headless: bool = True, limit: int = None):
        # LightNovelPub requires non-headless mode for chapter content access
        if headless:
            logger.info("LightNovelPub requires non-headless mode for chapter content. Overriding to visible browser.")
        super().__init__(headless=False, limit=limit)

    def get_popular_novels(self, max_pages: int = 10) -> List[Novel]:
        """Get most popular novels from LightNovelPub.

        Scrapes from https://lightnovelpub.org/list/most-popular-novels/
        which is sorted by popularity (most popular first).

        Args:
            max_pages: Number of pages to scrape (default 10, ~20 novels per page)
        """
        logger.info(f"Fetching most popular novels from LightNovelPub (up to {max_pages} pages)...")

        all_novels = []
        seen_urls = set()

        for page in range(1, max_pages + 1):
            url = f"{self.BASE_URL}/list/most-popular-novels/{page}"
            logger.info(f"Fetching popular page {page}/{max_pages}...")

            try:
                soup = self._get_soup(url, use_selenium=True)

                # Popular list uses .novel-item or .recommendation-card
                items = soup.select('.novel-item, li.novel-item, .recommendation-card')

                if not items:
                    # Fallback: look for any novel links in list format
                    items = soup.select('[class*="novel"] a[href*="/novel/"]')
                    if items:
                        # Wrap bare links so the parsing below works
                        items = [a.parent for a in items]

                if not items:
                    logger.info(f"No novels found on page {page}, stopping")
                    break

                found_new = False
                for item in items:
                    try:
                        link = item.select_one('a[href*="/novel/"]')
                        if not link:
                            # item itself might be an anchor
                            if item.name == 'a' and '/novel/' in item.get('href', ''):
                                link = item
                            else:
                                continue

                        href = link.get('href', '')
                        if not href or '/novel/' not in href:
                            continue

                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)

                        # Title
                        title_elem = item.select_one('.card-title, .novel-title, h3, h4')
                        title = title_elem.get_text(strip=True) if title_elem else ''
                        if not title:
                            title = link.get_text(strip=True)
                        if not title:
                            img = item.select_one('img[alt]')
                            if img:
                                title = img.get('alt', '')
                        if not title or len(title) < 2:
                            continue

                        # Chapter count
                        chapters_count = 0
                        ch_elem = item.select_one('.chapters, .card-meta .chapters')
                        if ch_elem:
                            match = re.search(r'(\d+)', ch_elem.get_text())
                            if match:
                                chapters_count = int(match.group(1))

                        # Cover URL
                        cover_url = ''
                        cover_img = item.select_one('img[src]')
                        if cover_img:
                            cover_url = cover_img.get('src', '')
                            if cover_url and not cover_url.startswith('http'):
                                cover_url = self.BASE_URL + cover_url

                        novel = Novel(
                            title=title,
                            url=full_url,
                            source=self.SITE_NAME,
                            chapters_count=chapters_count,
                            cover_url=cover_url
                        )
                        all_novels.append(novel)
                        found_new = True
                        logger.debug(f"Found: {title} ({chapters_count} chapters)")

                        if self.limit and len(all_novels) >= self.limit:
                            logger.info(f"Reached limit of {self.limit} novels")
                            break
                    except Exception as e:
                        logger.debug(f"Error parsing item: {e}")
                        continue

                if self.limit and len(all_novels) >= self.limit:
                    break

                if not found_new:
                    logger.info(f"No new novels found on page {page}, stopping")
                    break

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                break

        logger.info(f"Total popular novels found: {len(all_novels)}")
        return all_novels

    def get_all_novels(self) -> List[Novel]:
        """Get all novels from LightNovelPub"""
        logger.info("Fetching all novels from LightNovelPub...")

        all_novels = []
        page = 1
        seen_urls = set()

        while True:
            url = f"{self.BASE_URL}/genre-all/?page={page}" if page > 1 else f"{self.BASE_URL}/genre-all/"
            logger.info(f"Fetching page {page}...")

            try:
                soup = self._get_soup(url, use_selenium=True)

                # Find novel cards (current site structure uses .recommendation-card)
                items = soup.select('.recommendation-card')

                if not items:
                    # Fallback: try older selectors
                    items = soup.select('.novel-item, li.novel-item')

                if not items:
                    logger.info(f"No more novels found on page {page}")
                    break

                found_new = False
                for item in items:
                    try:
                        # Get link from card
                        link = item.select_one('a[href*="/novel/"]')
                        if not link:
                            continue

                        href = link.get('href', '')
                        if not href or '/novel/' not in href:
                            continue

                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)

                        # Get title from .card-title or h3
                        title_elem = item.select_one('.card-title, .novel-title, h3, h4')
                        title = title_elem.get_text(strip=True) if title_elem else ''

                        # Fallback: img alt text
                        if not title:
                            img = item.select_one('img[alt]')
                            if img:
                                title = img.get('alt', '')

                        if not title or len(title) < 2:
                            continue

                        # Get chapter count from .chapters span
                        chapters_count = 0
                        ch_elem = item.select_one('.chapters, .card-meta .chapters')
                        if ch_elem:
                            match = re.search(r'(\d+)', ch_elem.get_text())
                            if match:
                                chapters_count = int(match.group(1))

                        # Get cover URL
                        cover_url = ''
                        cover_img = item.select_one('img[src]')
                        if cover_img:
                            cover_url = cover_img.get('src', '')
                            if cover_url and not cover_url.startswith('http'):
                                cover_url = self.BASE_URL + cover_url

                        novel = Novel(
                            title=title,
                            url=full_url,
                            source=self.SITE_NAME,
                            chapters_count=chapters_count,
                            cover_url=cover_url
                        )
                        all_novels.append(novel)
                        found_new = True
                        logger.debug(f"Found: {title} ({chapters_count} chapters)")

                        if self.limit and len(all_novels) >= self.limit:
                            logger.info(f"Reached limit of {self.limit} novels")
                            break
                    except Exception as e:
                        logger.debug(f"Error parsing item: {e}")
                        continue

                if self.limit and len(all_novels) >= self.limit:
                    break

                if not found_new:
                    break

                page += 1

                if page > 500:  # Safety limit
                    logger.warning("Reached page limit")
                    break

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                break

        logger.info(f"Total novels found: {len(all_novels)}")
        return all_novels
    
    def get_novel_details(self, novel: Novel) -> Novel:
        """Fetch full details for a novel"""
        try:
            soup = self._get_soup(novel.url, use_selenium=True)
            
            # Get author
            author_elem = soup.select_one('.author a, [itemprop="author"], .novel-author')
            if author_elem:
                novel.author = author_elem.get_text(strip=True)
            
            # Get description
            desc_elem = soup.select_one('.summary, .description, [itemprop="description"], .novel-body')
            if desc_elem:
                novel.description = desc_elem.get_text(strip=True)[:2000]
            
            # Get genres
            genre_elems = soup.select('.categories a, .genre a, [itemprop="genre"]')
            novel.genres = [g.get_text(strip=True) for g in genre_elems]
            
            # Get status
            status_elem = soup.select_one('.status, .novel-status')
            if status_elem:
                text = status_elem.get_text(strip=True).lower()
                if 'complete' in text:
                    novel.status = 'Completed'
                elif 'ongoing' in text:
                    novel.status = 'Ongoing'
                elif 'hiatus' in text:
                    novel.status = 'Hiatus'
            
            # Get rating
            rating_elem = soup.select_one('.rating-num, .score, [itemprop="ratingValue"]')
            if rating_elem:
                try:
                    rating = float(re.search(r'(\d+\.?\d*)', rating_elem.get_text()).group(1))
                    if rating > 5:
                        rating = rating / 2  # Normalize 10-point to 5-point
                    novel.rating = round(min(rating, 5.0), 2)
                except:
                    pass
            
            # Get cover
            cover_elem = soup.select_one('.novel-cover img, .cover img, [itemprop="image"]')
            if cover_elem:
                novel.cover_url = cover_elem.get('src', '') or cover_elem.get('data-src', '')
            
            # Get chapter count
            chapters = self.get_chapters(novel)
            novel.chapters_count = len(chapters)
            
        except Exception as e:
            logger.debug(f"Error getting novel details: {e}")
        
        return novel
    
    def get_chapters(self, novel: Novel) -> List[Chapter]:
        """Get all chapters for a novel"""
        chapters = []

        try:
            # First try to get chapters from the novel page
            soup = self._get_soup(novel.url, use_selenium=True)

            # Try to find chapter links directly
            chapter_links = soup.select('a[href*="/chapter/"], a[href*="/chapter-"]')
            # Filter out non-chapter links (READ NOW, etc.)
            chapter_links = [l for l in chapter_links if re.search(r'/chapter/?\d', l.get('href', ''))]

            # Filter out "READ NOW" / "Latest Chapter" type links - keep only real chapter list links
            real_chapter_links = [l for l in chapter_links
                                  if not any(kw in l.get_text(strip=True).upper()
                                             for kw in ['READ NOW', 'READ FIRST', 'LATEST', 'START READING'])]

            # Only use scraped links if we found a real chapter list (more than 2 links)
            if len(real_chapter_links) > 2:
                seen = set()
                for link in real_chapter_links:
                    href = link.get('href', '')
                    title = link.get_text(strip=True)
                    if not href or href in seen:
                        continue
                    seen.add(href)

                    match = re.search(r'chapter[/\- ]?(\d+(?:\.\d+)?)', href, re.I)
                    number = match.group(1) if match else title
                    full_url = href if href.startswith('http') else self.BASE_URL + href

                    chapters.append(Chapter(
                        number=str(number),
                        title=title or f"Chapter {number}",
                        url=full_url
                    ))

            # If no real chapter list found, generate from chapter count
            if not chapters:
                ch_count = novel.chapters_count
                if ch_count == 0:
                    # Try to extract from page
                    info_text = soup.get_text()
                    match = re.search(r'(\d+)\s*Chapters', info_text)
                    if match:
                        ch_count = int(match.group(1))

                if ch_count > 0:
                    # Generate chapter URLs from the novel URL pattern
                    base = novel.url.rstrip('/')
                    for i in range(1, ch_count + 1):
                        chapters.append(Chapter(
                            number=str(i),
                            title=f"Chapter {i}",
                            url=f"{base}/chapter/{i}/"
                        ))
                    logger.info(f"Generated {ch_count} chapter URLs from count")

        except Exception as e:
            logger.error(f"Error getting chapters: {e}")

        # Sort by chapter number
        chapters.sort(key=lambda x: float(x.number) if x.number.replace('.', '').isdigit() else 0)
        return chapters

    def get_chapter_content(self, chapter: Chapter) -> str:
        """Get content for a chapter"""
        try:
            soup = self._get_soup(chapter.url, use_selenium=True)

            # Find content container - try multiple selectors
            for sel in ['#chapter-content', '.chapter-content', '.chapter-body',
                        '.content', 'article', '#chapter-container']:
                content_elem = soup.select_one(sel)
                if content_elem and len(content_elem.get_text(strip=True)) > 50:
                    return str(content_elem)

            return ""
        except Exception as e:
            logger.error(f"Error getting chapter content: {e}")
            return ""


class NovelBinScraper(BaseLightNovelScraper):
    """Scraper for novelbin.me"""

    BASE_URL = "https://novelbin.me"
    SITE_NAME = "novelbin"

    def __init__(self, headless: bool = True, limit: int = None):
        # NovelBin chapter pages require non-headless for Cloudflare bypass
        if headless:
            logger.info("NovelBin requires non-headless mode for chapter content. Overriding to visible browser.")
        super().__init__(headless=False, limit=limit)

    def _wait_for_cloudflare(self, timeout: int = 30):
        """Wait for Cloudflare challenge to resolve"""
        if not self.driver:
            return
        start = time.time()
        while time.time() - start < timeout:
            try:
                title = self.driver.title.lower()
                if 'just a moment' not in title and 'checking' not in title:
                    return True
            except Exception:
                pass
            time.sleep(2)
        logger.warning("Cloudflare challenge did not resolve within timeout")
        return False

    def _get_soup(self, url: str, use_selenium: bool = False) -> BeautifulSoup:
        """Override to handle Cloudflare on chapter pages"""
        self._init_selenium()
        self.driver.get(url)
        self._wait_for_cloudflare()
        time.sleep(2)
        return BeautifulSoup(self.driver.page_source, 'html.parser')

    def get_popular_novels(self, max_pages: int = 10) -> List[Novel]:
        """Get most popular novels from NovelBin.

        Scrapes from https://novelbin.me/sort/novelbin-popular
        which is sorted by popularity (most popular first).

        Args:
            max_pages: Number of pages to scrape (default 10, ~20 novels per page)
        """
        logger.info(f"Fetching most popular novels from NovelBin (up to {max_pages} pages)...")

        all_novels = []
        seen_urls = set()

        for page in range(1, max_pages + 1):
            url = f"{self.BASE_URL}/sort/novelbin-popular?page={page}"
            logger.info(f"Fetching popular page {page}/{max_pages}...")

            try:
                soup = self._get_soup(url, use_selenium=True)

                novel_links = soup.select('.novel-title a[href*="/novel-book/"], a[href*="/novel-book/"]')

                if not novel_links:
                    novel_links = soup.select('a[href*="/novel-"]')

                found_new = False
                for link in novel_links:
                    try:
                        href = link.get('href', '')
                        title = link.get_text(strip=True)

                        if not href or not title or len(title) < 2:
                            continue

                        if '/chapter' in href.lower() or 'cchapter' in href.lower():
                            continue

                        path = href.split('novelbin.me')[-1] if 'novelbin.me' in href else href
                        path_parts = [p for p in path.strip('/').split('/') if p]
                        if len(path_parts) != 2 or path_parts[0] != 'novel-book':
                            continue

                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)

                        novel = Novel(
                            title=title,
                            url=full_url,
                            source=self.SITE_NAME
                        )
                        all_novels.append(novel)
                        found_new = True
                        logger.debug(f"Found: {title}")

                        if self.limit and len(all_novels) >= self.limit:
                            logger.info(f"Reached limit of {self.limit} novels")
                            break
                    except:
                        continue

                if self.limit and len(all_novels) >= self.limit:
                    break

                if not found_new:
                    logger.info(f"No new novels found on page {page}, stopping")
                    break

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                break

        logger.info(f"Total popular novels found: {len(all_novels)}")
        return all_novels

    def get_all_novels(self) -> List[Novel]:
        """Get all novels from NovelBin"""
        logger.info("Fetching all novels from NovelBin...")

        all_novels = []
        page = 1
        seen_urls = set()

        while True:
            url = f"{self.BASE_URL}/sort/novelbin-popular?page={page}"
            logger.info(f"Fetching page {page}...")

            try:
                soup = self._get_soup(url, use_selenium=True)

                # Novel links are in .novel-title containers with /novel-book/ href
                novel_links = soup.select('.novel-title a[href*="/novel-book/"], a[href*="/novel-book/"]')

                if not novel_links:
                    # Fallback
                    novel_links = soup.select('a[href*="/novel-"]')

                found_new = False
                for link in novel_links:
                    try:
                        href = link.get('href', '')
                        title = link.get_text(strip=True)

                        if not href or not title or len(title) < 2:
                            continue

                        # Skip chapter links (contain /chapter or cchapter in path)
                        if '/chapter' in href.lower() or 'cchapter' in href.lower():
                            continue

                        # Must match pattern: /novel-book/SLUG (no extra path segments)
                        path = href.split('novelbin.me')[-1] if 'novelbin.me' in href else href
                        path_parts = [p for p in path.strip('/').split('/') if p]
                        if len(path_parts) != 2 or path_parts[0] != 'novel-book':
                            continue

                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)

                        novel = Novel(
                            title=title,
                            url=full_url,
                            source=self.SITE_NAME
                        )
                        all_novels.append(novel)
                        found_new = True
                        logger.debug(f"Found: {title}")

                        if self.limit and len(all_novels) >= self.limit:
                            logger.info(f"Reached limit of {self.limit} novels")
                            break
                    except:
                        continue

                if self.limit and len(all_novels) >= self.limit:
                    break

                if not found_new:
                    break

                page += 1
                if page > 100:
                    break

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                break

        logger.info(f"Total novels found: {len(all_novels)}")
        return all_novels
    
    def get_novel_details(self, novel: Novel) -> Novel:
        """Fetch full details for a novel"""
        try:
            soup = self._get_soup(novel.url, use_selenium=True)
            
            # Author
            author_elem = soup.select_one('.author a, [itemprop="author"]')
            if author_elem:
                novel.author = author_elem.get_text(strip=True)
            
            # Description
            desc_elem = soup.select_one('.desc-text, .description, #tab-description')
            if desc_elem:
                novel.description = desc_elem.get_text(strip=True)[:2000]
            
            # Genres
            genre_elems = soup.select('.info a[href*="genre"], .categories a')
            novel.genres = [g.get_text(strip=True) for g in genre_elems]
            
            # Status
            info_text = soup.get_text().lower()
            if 'completed' in info_text:
                novel.status = 'Completed'
            elif 'ongoing' in info_text:
                novel.status = 'Ongoing'
            
            # Rating
            rating_elem = soup.select_one('.rating, .score')
            if rating_elem:
                try:
                    rating = float(re.search(r'(\d+\.?\d*)', rating_elem.get_text()).group(1))
                    if rating > 5:
                        rating = rating / 2
                    novel.rating = round(min(rating, 5.0), 2)
                except:
                    pass
            
            # Cover
            cover_elem = soup.select_one('.book img, .cover img')
            if cover_elem:
                novel.cover_url = cover_elem.get('src', '') or cover_elem.get('data-src', '')
            
            # Chapter count
            chapters = self.get_chapters(novel)
            novel.chapters_count = len(chapters)
            
        except Exception as e:
            logger.debug(f"Error getting novel details: {e}")
        
        return novel
    
    def get_chapters(self, novel: Novel) -> List[Chapter]:
        """Get all chapters for a novel"""
        chapters = []
        seen_urls = set()

        try:
            soup = self._get_soup(novel.url, use_selenium=True)

            # NovelBin has chapter list in #list-chapter or #tab-chap
            chapter_links = soup.select('#list-chapter a, #tab-chap a, .list-chapter a')

            if not chapter_links:
                # Fallback: any chapter links
                chapter_links = soup.select('a[href*="chapter"]')

            for link in chapter_links:
                href = link.get('href', '')
                title = link.get_text(strip=True)

                if not href or 'chapter' not in href.lower():
                    continue

                # Skip tab links
                if href.startswith('#'):
                    continue

                full_url = href if href.startswith('http') else self.BASE_URL + href
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href, re.I)
                number = match.group(1) if match else title

                chapters.append(Chapter(
                    number=str(number),
                    title=title or f"Chapter {number}",
                    url=full_url
                ))

        except Exception as e:
            logger.error(f"Error getting chapters: {e}")

        # Sort by chapter number
        chapters.sort(key=lambda x: float(x.number) if x.number.replace('.', '').isdigit() else 0)
        return chapters

    def get_chapter_content(self, chapter: Chapter) -> str:
        """Get content for a chapter"""
        try:
            soup = self._get_soup(chapter.url, use_selenium=True)

            # NovelBin uses #chr-content for chapter text
            for sel in ['#chr-content', '#chapter-content', '.chapter-content', '#chapter-c']:
                content_elem = soup.select_one(sel)
                if content_elem and len(content_elem.get_text(strip=True)) > 50:
                    return str(content_elem)

            return ""
        except Exception as e:
            logger.error(f"Error getting chapter content: {e}")
            return ""


# Site registry
SCRAPERS = {
    'lightnovelpub': LightNovelPubScraper,
    'lightnovelpub.org': LightNovelPubScraper,
    'novelbin': NovelBinScraper,
    'novelbin.me': NovelBinScraper,
}

PRIMARY_SITES = {
    'lightnovelpub': LightNovelPubScraper,
    'novelbin': NovelBinScraper,
}


def get_scraper(site: str, headless: bool = True, limit: int = None) -> BaseLightNovelScraper:
    """Get scraper instance by site name"""
    site_lower = site.lower()

    for key, scraper_class in SCRAPERS.items():
        if key in site_lower:
            return scraper_class(headless=headless, limit=limit)

    raise ValueError(f"Unknown site: {site}. Available: {list(SCRAPERS.keys())}")


def get_all_scrapers(headless: bool = True, limit: int = None) -> Dict[str, BaseLightNovelScraper]:
    """Get all primary scrapers"""
    scrapers = {}
    for name, scraper_class in PRIMARY_SITES.items():
        scrapers[name] = scraper_class(headless=headless, limit=limit)
    return scrapers


def export_novel_list(novels: List[Novel], output_file: Path):
    """Export novel list to YAML file"""
    
    total_chapters = sum(n.chapters_count for n in novels)
    novels_with_ratings = [n for n in novels if n.rating > 0]
    avg_rating = sum(n.rating for n in novels_with_ratings) / len(novels_with_ratings) if novels_with_ratings else 0
    
    status_counts = {}
    for n in novels:
        status = n.status or 'Unknown'
        status_counts[status] = status_counts.get(status, 0) + 1
    
    data = {
        'generated': datetime.now().isoformat(),
        'total_novels': len(novels),
        'total_chapters': total_chapters,
        'novels_with_ratings': len(novels_with_ratings),
        'average_rating': round(avg_rating, 2),
        'status_breakdown': status_counts,
        'novels': []
    }
    
    # Sort by rating, then chapters
    sorted_novels = sorted(novels, key=lambda n: (n.rating, n.chapters_count), reverse=True)
    
    for n in sorted_novels:
        entry = {
            'title': n.title,
            'url': n.url,
            'source': n.source,
            'author': n.author,
            'status': n.status or 'Unknown',
            'rating': n.rating,
            'chapters': n.chapters_count,
            'genres': n.genres,
            'description': n.description[:500] if n.description else '',
            'cover_url': n.cover_url,
            'enabled': True
        }
        data['novels'].append(entry)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    logger.info(f"Exported {len(novels)} novels to {output_file}")


def load_novel_list(config_file: Path) -> List[Novel]:
    """Load novel list from YAML file"""
    with open(config_file, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    novels = []
    for item in data.get('novels', []):
        if item.get('enabled', True):
            novels.append(Novel(
                title=item['title'],
                url=item['url'],
                source=item.get('source', 'unknown'),
                author=item.get('author', ''),
                genres=item.get('genres', []),
                status=item.get('status', ''),
                chapters_count=item.get('chapters', 0),
                rating=item.get('rating', 0.0),
                description=item.get('description', ''),
                cover_url=item.get('cover_url', '')
            ))
    
    return novels


def filter_novels(novels: List[Novel], filter_terms: List[str]) -> List[Novel]:
    """Filter novels by genre, title, or author (OR logic)"""
    if not filter_terms:
        return novels
    
    filtered = []
    for n in novels:
        searchable = f"{n.title} {n.author} {' '.join(n.genres)} {n.status}".lower()
        if any(term.lower() in searchable for term in filter_terms):
            filtered.append(n)
    
    return filtered


def filter_novels_all(novels: List[Novel], filter_terms: List[str]) -> List[Novel]:
    """Filter novels (AND logic - must match ALL terms)"""
    if not filter_terms:
        return novels
    
    filtered = []
    for n in novels:
        searchable = f"{n.title} {n.author} {' '.join(n.genres)} {n.status}".lower()
        if all(term.lower() in searchable for term in filter_terms):
            filtered.append(n)
    
    return filtered


def filter_by_rating(novels: List[Novel], min_rating: float) -> List[Novel]:
    """Filter novels by minimum rating"""
    if min_rating <= 0:
        return novels
    return [n for n in novels if n.rating >= min_rating]


def filter_by_chapters(novels: List[Novel], min_chapters: int = 0, max_chapters: int = None) -> List[Novel]:
    """Filter novels by chapter count"""
    filtered = []
    for n in novels:
        if n.chapters_count >= min_chapters:
            if max_chapters is None or n.chapters_count <= max_chapters:
                filtered.append(n)
    return filtered


def filter_by_status(novels: List[Novel], statuses: List[str]) -> List[Novel]:
    """Filter novels by status"""
    if not statuses:
        return novels
    
    normalized = [s.lower().strip() for s in statuses]
    filtered = []
    for n in novels:
        status = (n.status or '').lower()
        if status in normalized or any(ns in status for ns in normalized):
            filtered.append(n)
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description='Scrape light novels and create EPUBs for Kavita',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all novels from a site
  python lightnovel_scraper.py --site lightnovelpub --list-all -o novels.yaml

  # List only the most popular novels (first 10 pages, ~200 novels)
  python lightnovel_scraper.py --site lightnovelpub --list-all --popular -o popular.yaml

  # List top 5 pages of popular novels (~100 novels)
  python lightnovel_scraper.py --site lightnovelpub --list-all --popular --pages 5 -o popular.yaml

  # Download only the most popular novels
  python lightnovel_scraper.py --site lightnovelpub --download-all --popular --pages 10 -o ./library/LightNovels

  # List with details (chapters, rating, etc.)
  python lightnovel_scraper.py --site lightnovelpub --list-all --with-details -o novels.yaml

  # Download all novels (as EPUBs)
  python lightnovel_scraper.py --site lightnovelpub --download-all -o ./library/LightNovels

  # Download only completed novels with 100+ chapters
  python lightnovel_scraper.py --site lightnovelpub --download-all --status completed --min-chapters 100 -o ./library

  # Download highly-rated fantasy novels
  python lightnovel_scraper.py --site lightnovelpub --download-all --filter "fantasy" --min-rating 4.0 -o ./library

  # Download from all sites
  python lightnovel_scraper.py --site all --download-all -o ./library/LightNovels

  # Download from a curated YAML list
  python lightnovel_scraper.py --config my_novels.yaml -o ./library/LightNovels
        """
    )
    
    parser.add_argument('--site', '-s', help='Site to scrape (lightnovelpub, novelbin, or "all")')
    parser.add_argument('--list-all', action='store_true', help='List all novels and export to YAML')
    parser.add_argument('--download-all', action='store_true', help='Download all novels as EPUBs')
    parser.add_argument('--popular', action='store_true',
                        help='Only scrape from the most-popular pages instead of all novels. '
                             'Use with --pages to control how many pages (default 10, ~20 novels/page)')
    parser.add_argument('--pages', type=int, default=10,
                        help='Number of popular pages to scrape (default: 10). Only used with --popular')
    parser.add_argument('--config', '-c', help='YAML config file with novel list')
    parser.add_argument('--output', '-o', required=True, help='Output directory or YAML file')
    parser.add_argument('--filter', '-f', help='Filter terms (OR logic)')
    parser.add_argument('--filter-all', help='Filter terms (AND logic)')
    parser.add_argument('--min-chapters', type=int, default=0, help='Minimum chapter count')
    parser.add_argument('--max-chapters', type=int, help='Maximum chapter count')
    parser.add_argument('--min-rating', type=float, default=0.0, help='Minimum rating (0-5)')
    parser.add_argument('--status', help='Filter by status (completed, ongoing)')
    parser.add_argument('--with-details', action='store_true', help='Fetch full details (slower)')
    parser.add_argument('--visible', action='store_true', help='Show browser window')
    parser.add_argument('--limit', type=int, help='Limit number of novels')
    
    args = parser.parse_args()
    
    if not HAS_EBOOKLIB and (args.download_all or args.config):
        print("Error: ebooklib is required for downloading. Install with: pip install ebooklib")
        sys.exit(1)
    
    headless = not args.visible
    output_path = Path(args.output)
    
    # Mode 1: List novels
    if args.list_all and args.site:
        all_novels = []

        if args.site.lower() == 'all':
            scrapers = get_all_scrapers(headless, limit=args.limit)
            for site_name, scraper in scrapers.items():
                logger.info(f"\n{'='*50}")
                logger.info(f"Scraping: {site_name.upper()}")
                logger.info(f"{'='*50}")

                try:
                    if args.popular:
                        novels = scraper.get_popular_novels(max_pages=args.pages)
                    else:
                        novels = scraper.get_all_novels()
                    for n in novels:
                        n.source = site_name

                    if args.with_details:
                        novels = scraper.enrich_with_details(novels)

                    all_novels.extend(novels)
                except Exception as e:
                    logger.error(f"Error: {e}")
                finally:
                    scraper._close_driver()
        else:
            scraper = get_scraper(args.site, headless, limit=args.limit)
            if args.popular:
                all_novels = scraper.get_popular_novels(max_pages=args.pages)
            else:
                all_novels = scraper.get_all_novels()

            if args.with_details:
                all_novels = scraper.enrich_with_details(all_novels)

            scraper._close_driver()
        
        # Apply filters
        if args.filter:
            terms = [t.strip() for t in args.filter.split(',')]
            all_novels = filter_novels(all_novels, terms)
        
        if args.filter_all:
            terms = [t.strip() for t in args.filter_all.split(',')]
            all_novels = filter_novels_all(all_novels, terms)
        
        if args.min_chapters > 0 or args.max_chapters:
            all_novels = filter_by_chapters(all_novels, args.min_chapters, args.max_chapters)
        
        if args.min_rating > 0:
            all_novels = filter_by_rating(all_novels, args.min_rating)
        
        if args.status:
            statuses = [s.strip() for s in args.status.split(',')]
            all_novels = filter_by_status(all_novels, statuses)
        
        if args.limit:
            all_novels = all_novels[:args.limit]
        
        export_novel_list(all_novels, output_path)
        return
    
    # Mode 2: Download novels
    if args.download_all and args.site:
        output_path.mkdir(parents=True, exist_ok=True)
        cache_file = output_path / '.download_progress.pkl'
        tracker = ProgressTracker(cache_file)
        
        if args.site.lower() == 'all':
            scrapers = get_all_scrapers(headless, limit=args.limit)
            for site_name, scraper in scrapers.items():
                logger.info(f"\n{'='*50}")
                logger.info(f"Downloading from: {site_name.upper()}")
                logger.info(f"{'='*50}")

                try:
                    if args.popular:
                        novels = scraper.get_popular_novels(max_pages=args.pages)
                    else:
                        novels = scraper.get_all_novels()

                    # Apply filters
                    if args.filter:
                        novels = filter_novels(novels, [t.strip() for t in args.filter.split(',')])
                    if args.filter_all:
                        novels = filter_novels_all(novels, [t.strip() for t in args.filter_all.split(',')])
                    
                    # Need details for chapter/rating/status filters
                    if args.min_chapters > 0 or args.max_chapters or args.min_rating > 0 or args.status:
                        novels = scraper.enrich_with_details(novels)
                        
                        if args.min_chapters > 0 or args.max_chapters:
                            novels = filter_by_chapters(novels, args.min_chapters, args.max_chapters)
                        if args.min_rating > 0:
                            novels = filter_by_rating(novels, args.min_rating)
                        if args.status:
                            novels = filter_by_status(novels, [s.strip() for s in args.status.split(',')])
                    
                    if args.limit:
                        novels = novels[:args.limit]
                    
                    # Download each novel
                    for i, novel in enumerate(novels, 1):
                        if tracker.is_downloaded(novel.url):
                            logger.info(f"[{i}/{len(novels)}] Skipping (already downloaded): {novel.title}")
                            continue
                        
                        logger.info(f"[{i}/{len(novels)}] Downloading: {novel.title}")
                        
                        try:
                            # Get full details if not already
                            if not novel.description:
                                novel = scraper.get_novel_details(novel)
                            
                            # Get chapters
                            chapters = scraper.get_chapters(novel)
                            logger.info(f"  Found {len(chapters)} chapters")
                            
                            # Get content for each chapter
                            for j, chapter in enumerate(chapters, 1):
                                logger.info(f"  [{j}/{len(chapters)}] Fetching: {chapter.title}")
                                chapter.content = scraper.get_chapter_content(chapter)
                                time.sleep(0.5)
                            
                            # Create EPUB
                            epub_path = scraper.create_epub(novel, chapters, output_path)
                            logger.info(f"  Created: {epub_path.name}")
                            
                            tracker.mark_downloaded(novel.url)
                            
                        except Exception as e:
                            logger.error(f"  Error: {e}")
                
                except Exception as e:
                    logger.error(f"Error with {site_name}: {e}")
                finally:
                    scraper._close_driver()
        
        else:
            scraper = get_scraper(args.site, headless, limit=args.limit)
            if args.popular:
                novels = scraper.get_popular_novels(max_pages=args.pages)
            else:
                novels = scraper.get_all_novels()

            # Apply filters
            if args.filter:
                novels = filter_novels(novels, [t.strip() for t in args.filter.split(',')])
            if args.filter_all:
                novels = filter_novels_all(novels, [t.strip() for t in args.filter_all.split(',')])
            
            if args.min_chapters > 0 or args.max_chapters or args.min_rating > 0 or args.status:
                novels = scraper.enrich_with_details(novels)
                
                if args.min_chapters > 0 or args.max_chapters:
                    novels = filter_by_chapters(novels, args.min_chapters, args.max_chapters)
                if args.min_rating > 0:
                    novels = filter_by_rating(novels, args.min_rating)
                if args.status:
                    novels = filter_by_status(novels, [s.strip() for s in args.status.split(',')])
            
            if args.limit:
                novels = novels[:args.limit]
            
            logger.info(f"Will download {len(novels)} novels")
            
            for i, novel in enumerate(novels, 1):
                if tracker.is_downloaded(novel.url):
                    logger.info(f"[{i}/{len(novels)}] Skipping: {novel.title}")
                    continue
                
                logger.info(f"[{i}/{len(novels)}] Downloading: {novel.title}")
                
                try:
                    if not novel.description:
                        novel = scraper.get_novel_details(novel)
                    
                    chapters = scraper.get_chapters(novel)
                    logger.info(f"  Found {len(chapters)} chapters")
                    
                    for j, chapter in enumerate(chapters, 1):
                        logger.info(f"  [{j}/{len(chapters)}] Fetching: {chapter.title}")
                        chapter.content = scraper.get_chapter_content(chapter)
                        time.sleep(0.5)
                    
                    epub_path = scraper.create_epub(novel, chapters, output_path)
                    logger.info(f"  Created: {epub_path.name}")
                    
                    tracker.mark_downloaded(novel.url)
                    
                except Exception as e:
                    logger.error(f"  Error: {e}")
            
            scraper._close_driver()
        
        logger.info("Download complete!")
        return
    
    # Mode 3: Download from config
    if args.config:
        novels = load_novel_list(Path(args.config))
        
        if args.limit:
            novels = novels[:args.limit]
        
        output_path.mkdir(parents=True, exist_ok=True)
        cache_file = output_path / '.download_progress.pkl'
        tracker = ProgressTracker(cache_file)
        
        # Group by source
        by_source = {}
        for n in novels:
            by_source.setdefault(n.source, []).append(n)
        
        for source, source_novels in by_source.items():
            scraper = get_scraper(source, headless)
            
            for i, novel in enumerate(source_novels, 1):
                if tracker.is_downloaded(novel.url):
                    logger.info(f"[{i}/{len(source_novels)}] Skipping: {novel.title}")
                    continue
                
                logger.info(f"[{i}/{len(source_novels)}] Downloading: {novel.title}")
                
                try:
                    if not novel.description:
                        novel = scraper.get_novel_details(novel)
                    
                    chapters = scraper.get_chapters(novel)
                    
                    for j, chapter in enumerate(chapters, 1):
                        logger.info(f"  [{j}/{len(chapters)}] {chapter.title}")
                        chapter.content = scraper.get_chapter_content(chapter)
                        time.sleep(0.5)
                    
                    epub_path = scraper.create_epub(novel, chapters, output_path)
                    logger.info(f"  Created: {epub_path.name}")
                    
                    tracker.mark_downloaded(novel.url)
                    
                except Exception as e:
                    logger.error(f"  Error: {e}")
            
            scraper._close_driver()
        
        logger.info("Download complete!")
        return
    
    parser.print_help()


if __name__ == '__main__':
    main()
