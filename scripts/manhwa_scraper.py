#!/usr/bin/env python3
"""
manhwa_scraper.py - Full site scraper for manhwa/manhua sites

Features:
- Scrape ALL series from a site
- Export series list to YAML for selective downloading
- Download all or filtered series
- Resume interrupted downloads
- Rate limiting to avoid bans

Supports:
- asuracomic.net
- flamecomics.xyz
- drakecomic.org

Usage:
    # List all series from a site (creates series list file)
    python manhwa_scraper.py --site asura --list-all --output series_list.yaml
    
    # Download ALL series from a site (careful - lots of data!)
    python manhwa_scraper.py --site asura --download-all --output /path/to/library
    
    # Download only series matching a filter
    python manhwa_scraper.py --site asura --download-all --filter "cultivation,martial" --output /path/to/library
    
    # Download from a curated list
    python manhwa_scraper.py --config my_series.yaml --output /path/to/library
"""

import argparse
import copy
import os
import re
import sys
import time
import json
import random
import zipfile
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    from bs4 import BeautifulSoup
    import yaml
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install requests beautifulsoup4 pyyaml")
    sys.exit(1)

# Optional Selenium for JS-heavy sites
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
    
    # Try to import undetected-chromedriver for better bot detection bypass
    try:
        import undetected_chromedriver as uc
        UC_AVAILABLE = True
    except ImportError:
        UC_AVAILABLE = False
        
except ImportError:
    SELENIUM_AVAILABLE = False
    UC_AVAILABLE = False
    print("Warning: Selenium not available. Some sites may not work.")
    print("Install with: pip install selenium webdriver-manager")

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
    genres: List[str] = field(default_factory=list)
    status: str = ""
    chapters_count: int = 0
    last_updated: str = ""
    rating: float = 0.0  # Rating out of 5.0 or 10.0 (normalized to 5.0)
    description: str = ""
    author: str = ""
    artist: str = ""
    cover_url: str = ""  # URL to series cover/thumbnail image from source site
    enabled: bool = True


class ProgressTracker:
    """Track download progress to allow resuming"""
    
    def __init__(self, cache_file: Path):
        self.cache_file = cache_file
        self.downloaded: Set[str] = set()
        self.load()
    
    def load(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'rb') as f:
                    self.downloaded = pickle.load(f)
                logger.info(f"Loaded progress: {len(self.downloaded)} chapters already downloaded")
            except Exception as e:
                logger.warning(f"Could not load progress cache: {e}")
                self.downloaded = set()
    
    def save(self):
        try:
            with open(self.cache_file, 'wb') as f:
                pickle.dump(self.downloaded, f)
        except Exception as e:
            logger.warning(f"Could not save progress cache: {e}")
    
    def is_downloaded(self, chapter_url: str) -> bool:
        return chapter_url in self.downloaded
    
    def mark_downloaded(self, chapter_url: str):
        self.downloaded.add(chapter_url)
        self.save()


class BaseSiteScraper:
    """Base class for site-wide scraping"""
    
    BASE_URL = ""
    SITE_NAME = ""
    
    # Rate limiting
    MIN_DELAY = 2  # Minimum seconds between requests
    MAX_DELAY = 5  # Maximum seconds between requests

    # Cloudflare-protected sites that benefit from FlareSolverr
    CLOUDFLARE_SITE = False

    def __init__(self, headless: bool = True, limit: int = None):
        self.headless = headless
        self.driver = None
        self.limit = limit  # Stop after finding this many series
        self._use_flaresolverr = False
        self._fs_cookies_applied = False
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        # Auto-detect FlareSolverr for Cloudflare sites on ARM
        if self.CLOUDFLARE_SITE and self._is_arm() and not UC_AVAILABLE:
            if self._flaresolverr_available():
                logger.info(f"ARM detected - using FlareSolverr for {self.SITE_NAME}")
                self._use_flaresolverr = True
    
    def _delay(self):
        """Random delay between requests to avoid rate limiting"""
        if self._use_flaresolverr and self._fs_cookies_applied:
            # Using cached cookies — lighter delay since we're not hitting Cloudflare
            time.sleep(random.uniform(0.5, 1.5))
        else:
            delay = random.uniform(self.MIN_DELAY, self.MAX_DELAY)
            time.sleep(delay)
    
    def _detect_chrome_version(self):
        """Detect installed Chrome version for undetected-chromedriver compatibility"""
        import subprocess
        import re as regex
        try:
            # Windows - read from registry
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            winreg.CloseKey(key)
            return int(version.split('.')[0])
        except:
            pass
        # Linux - try multiple browser names
        for browser in ['google-chrome', 'chromium-browser', 'chromium']:
            try:
                result = subprocess.run([browser, '--version'], capture_output=True, text=True, timeout=5)
                match = regex.search(r'(\d+)\.', result.stdout)
                if match:
                    return int(match.group(1))
            except:
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
        # Common paths on Debian/Ubuntu/Pi OS
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

    def _flaresolverr_url(self):
        """Get FlareSolverr URL from env or default"""
        return os.environ.get('FLARESOLVERR_URL', 'http://localhost:8191')

    def _flaresolverr_available(self):
        """Check if FlareSolverr is reachable"""
        try:
            resp = requests.get(self._flaresolverr_url(), timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _flaresolverr_get(self, url: str, max_timeout: int = 60000):
        """Use FlareSolverr to fetch a URL, solving Cloudflare challenges.
        Returns (html, cookies_list, user_agent) or raises on failure."""
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": max_timeout,
        }
        resp = requests.post(
            f"{self._flaresolverr_url()}/v1",
            json=payload,
            timeout=max_timeout // 1000 + 30,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "ok":
            raise RuntimeError(f"FlareSolverr error: {data.get('message', 'unknown')}")

        solution = data["solution"]
        html = solution["response"]
        cookies = solution.get("cookies", [])
        user_agent = solution.get("userAgent", "")
        return html, cookies, user_agent

    def _apply_flaresolverr_cookies(self, cookies: list, user_agent: str = ""):
        """Apply cookies from FlareSolverr to the requests session"""
        for c in cookies:
            self.session.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
            )
        if user_agent:
            self.session.headers["User-Agent"] = user_agent
        logger.debug(f"Applied {len(cookies)} FlareSolverr cookies to session")

    def _inject_ad_blocker(self):
        """Inject JavaScript to block ads, popups, and redirects"""
        try:
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': """
                    window.open = function() { return null; };
                    if (Notification) {
                        Notification.requestPermission = function() { return Promise.resolve('denied'); };
                    }
                    
                    // Block redirects to ad domains
                    var adDomains = ['retileupfis', 'tragicuncy', 'uncophys', 'supireekskion', 'humanverify', 'popsmartblocker'];
                    
                    var origAssign = window.location.assign;
                    var origReplace = window.location.replace;
                    
                    window.location.assign = function(url) {
                        if (adDomains.some(d => url.indexOf(d) !== -1)) { console.log('Blocked:', url); return; }
                        origAssign.call(window.location, url);
                    };
                    window.location.replace = function(url) {
                        if (adDomains.some(d => url.indexOf(d) !== -1)) { console.log('Blocked:', url); return; }
                        origReplace.call(window.location, url);
                    };
                    
                    var origSetTimeout = window.setTimeout;
                    window.setTimeout = function(fn, delay) {
                        if (typeof fn === 'string' && fn.indexOf('location') !== -1) { return 0; }
                        return origSetTimeout.apply(window, arguments);
                    };
                """
            })
        except:
            pass

    def _init_driver(self):
        """Initialize WebDriver with undetected-chromedriver if available"""
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium not available - install with: pip install selenium")
        if self.driver:
            return
        
        # Use undetected-chromedriver if available (much better at avoiding detection)
        if UC_AVAILABLE:
            logger.info("Using undetected-chromedriver")
            options = uc.ChromeOptions()
            
            if self.headless:
                options.add_argument('--headless=new')
            
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            
            # Block notifications and popups (anti-ad measures)
            options.add_argument('--disable-notifications')
            prefs = {
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_setting_values.popups": 2,
            }
            options.add_experimental_option("prefs", prefs)
            
            # Block known ad domains
            ad_domains = ["deshystria.com", "uncingle.com", "tragicuncy.com", "pushnow.net", "raposablie.com", "retileupfis.com", "popsmartblocker.pro"]
            block_rules = ",".join([f"MAP *.{d} 127.0.0.1, MAP {d} 127.0.0.1" for d in ad_domains])
            options.add_argument(f'--host-rules={block_rules}')
            
            try:
                # Detect Chrome version to avoid version mismatch errors
                chrome_version = self._detect_chrome_version()
                if chrome_version:
                    logger.info(f"Detected Chrome version: {chrome_version}")
                    self.driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_version)
                else:
                    self.driver = uc.Chrome(options=options, use_subprocess=True)
                
                # Inject ad-blocking script
                self._inject_ad_blocker()
                self.driver.implicitly_wait(10)
                return
                
            except Exception as e:
                logger.warning(f"undetected-chromedriver failed: {e}, falling back to regular selenium")
        
        # Fallback to regular selenium
        logger.info("Using regular selenium (undetected-chromedriver not available or failed)")
        options = Options()

        if self.headless:
            options.add_argument('--headless=new')

        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-notifications')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        # On ARM (Raspberry Pi), use system-installed chromedriver directly
        # webdriver-manager downloads x86 binaries which don't work on ARM
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
                logger.warning("ARM detected but no system chromedriver found. Trying default...")
                self.driver = webdriver.Chrome(options=options)
        else:
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
            except Exception:
                self.driver = webdriver.Chrome(options=options)
        
        # Try to mask automation
        try:
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            })
        except:
            pass
        
        self.driver.implicitly_wait(10)


    def _close_driver(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    @staticmethod
    def _is_cloudflare_challenge(html: str) -> bool:
        """Detect Cloudflare challenge/block pages that aren't real content."""
        markers = [
            'Just a moment...',
            'Checking your browser',
            'cf-challenge-running',
            'cf_chl_opt',
            '_cf_chl_tk',
            'Attention Required! | Cloudflare',
            'Enable JavaScript and cookies to continue',
        ]
        # Quick length check — real chapter pages are large
        if len(html) < 5000:
            return any(m in html for m in markers)
        # For longer pages, only flag if multiple markers present
        hits = sum(1 for m in markers if m in html)
        return hits >= 2

    def _get_soup(self, url: str, use_selenium: bool = False) -> BeautifulSoup:
        """Get BeautifulSoup object from URL.

        Uses FlareSolverr when available (much faster than Selenium on ARM),
        falls back to Selenium, then to plain requests.
        """
        self._delay()

        # FlareSolverr path: no browser needed, ~2-5s per request vs ~15-20s Selenium
        if self._use_flaresolverr and use_selenium:
            # Try cached session cookies first (instant)
            if self._fs_cookies_applied:
                try:
                    resp = self.session.get(url, timeout=30)
                    resp.raise_for_status()
                    if len(resp.text) > 500:
                        # Check if we got a Cloudflare challenge instead of real content
                        if self._is_cloudflare_challenge(resp.text):
                            logger.info(f"Cached cookies returned Cloudflare challenge, refreshing via FlareSolverr")
                            self._fs_cookies_applied = False
                            # Fall through to fresh FlareSolverr below
                        else:
                            return BeautifulSoup(resp.text, 'html.parser')
                except Exception:
                    pass
            # Fall back to FlareSolverr
            try:
                html, cookies, user_agent = self._flaresolverr_get(url)
                self._apply_flaresolverr_cookies(cookies, user_agent)
                self._fs_cookies_applied = True
                return BeautifulSoup(html, 'html.parser')
            except Exception as e:
                logger.warning(f"FlareSolverr failed for {url}: {e}")
                # Fall through to Selenium if available

        if use_selenium:
            self._init_driver()
            self.driver.get(url)

            # Wait for page to load
            wait_time = 5
            time.sleep(wait_time)

            # Try to wait for specific content to appear (grid of series)
            try:
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                from selenium.webdriver.common.by import By

                # Wait for any links to series pages
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="series/"]'))
                )
                time.sleep(1)  # Extra time for all content to render
            except:
                pass  # Continue even if wait fails

            html = self.driver.page_source
        else:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            html = response.text

        return BeautifulSoup(html, 'html.parser')
    
    def get_all_series(self) -> List[Series]:
        """Get ALL series from the site - override in subclass"""
        raise NotImplementedError
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        """Get chapters for a series - override in subclass"""
        raise NotImplementedError
    
    def get_chapter_count(self, series: Series) -> int:
        """Get chapter count for a series (calls get_chapters)"""
        try:
            chapters = self.get_chapters(series)
            return len(chapters)
        except Exception as e:
            logger.debug(f"Error getting chapter count for {series.title}: {e}")
            return 0
    
    def get_series_status(self, series: Series) -> str:
        """Get status for a series (Ongoing, Completed, etc.) - override in subclass for better performance"""
        try:
            soup = self._get_soup(series.url, use_selenium=True)
            
            # Common status patterns across sites
            status_selectors = [
                '.status', '[class*="status"]', '.info-status',
                'span:contains("Status")', 'div:contains("Status")',
                '.imptdt', '.tsinfo', '.spe', '.seriestustat'
            ]
            
            for selector in status_selectors:
                try:
                    elem = soup.select_one(selector)
                    if elem:
                        text = elem.get_text(strip=True).lower()
                        if 'completed' in text or 'finished' in text or 'complete' in text:
                            return 'Completed'
                        elif 'ongoing' in text or 'updating' in text:
                            return 'Ongoing'
                        elif 'hiatus' in text:
                            return 'Hiatus'
                        elif 'dropped' in text or 'cancelled' in text or 'canceled' in text:
                            return 'Dropped'
                except:
                    continue
            
            # Try searching all text for status keywords
            page_text = soup.get_text().lower()
            if 'status: completed' in page_text or 'status:completed' in page_text:
                return 'Completed'
            elif 'status: ongoing' in page_text or 'status:ongoing' in page_text:
                return 'Ongoing'
            elif 'status: hiatus' in page_text:
                return 'Hiatus'
            
            return 'Unknown'
            
        except Exception as e:
            logger.debug(f"Error getting status for {series.title}: {e}")
            return 'Unknown'
    
    def get_series_details(self, series: Series) -> Series:
        """Fetch full details for a series: title, status, rating, description, author, artist"""
        try:
            soup = self._get_soup(series.url, use_selenium=True)
            
            # Get title if not set or is "Unknown"
            if not series.title or series.title == "Unknown":
                series.title = self._extract_title_from_soup(soup) or series.title
            
            # Get status
            if not series.status or series.status in ['', 'Unknown']:
                series.status = self._extract_status_from_soup(soup)
            
            # Get rating
            if series.rating == 0.0:
                series.rating = self._extract_rating_from_soup(soup)
            
            # Get description
            if not series.description:
                series.description = self._extract_description_from_soup(soup)
            
            # Get author/artist
            if not series.author:
                series.author = self._extract_author_from_soup(soup)
            if not series.artist:
                series.artist = self._extract_artist_from_soup(soup)

            # Get genres from the series detail page
            extracted_genres = self._extract_genres_from_soup(soup)
            if extracted_genres:
                series.genres = extracted_genres

            # Get cover image URL
            if not series.cover_url:
                series.cover_url = self._extract_cover_from_soup(soup)

            # Get chapter count if not set
            if series.chapters_count == 0:
                try:
                    chapters = self.get_chapters(series)
                    series.chapters_count = len(chapters)
                except:
                    pass
            
            return series
            
        except Exception as e:
            logger.debug(f"Error getting details for {series.title}: {e}")
            return series
    
    def _extract_title_from_soup(self, soup) -> str:
        """Extract title from parsed soup"""
        # Try og:title first (most reliable, available on most sites)
        og = soup.select_one('meta[property="og:title"]')
        if og:
            title = og.get('content', '').strip()
            if title:
                # Strip common suffixes like " - Asura Scans", " - Flame Comics"
                title = re.sub(r'\s*[-–|]\s*(Asura|Flame|Drake|Webtoon|ManhuaTo)\b.*$', '', title, flags=re.I)
                # Strip common prefixes like "Drake Scans - " at the start
                title = re.sub(r'^(Asura|Flame|Drake|Webtoon|ManhuaTo)\s*(Scans?|Comics?)\s*[-–|]\s*', '', title, flags=re.I)
                # Reject if it's just a generic site tagline
                if (title and len(title) > 2 and
                        'high-quality' not in title.lower() and
                        'translation' not in title.lower() and
                        'scans' not in title.lower()):
                    return title

        title_selectors = [
            'span.text-xl', '.series-title', '.manga-title', '.entry-title',
            '.post-title', '[class*="title"] h1', 'h1[class*="title"]',
            '.seriestuheader h1', 'h1',
        ]

        for selector in title_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True)
                    # Skip common banner/promo text
                    if (text and len(text) > 2 and
                            'READ ON' not in text.upper() and
                            'BETA SITE' not in text.upper() and
                            'SUBSCRIBE' not in text.upper()):
                        return text
            except:
                continue
        return ""
    
    def _extract_status_from_soup(self, soup) -> str:
        """Extract status from parsed soup"""
        status_selectors = [
            '.status', '[class*="status"]', '.info-status',
            '.imptdt', '.tsinfo', '.spe', '.seriestustat'
        ]
        
        for selector in status_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True).lower()
                    if 'completed' in text or 'finished' in text:
                        return 'Completed'
                    elif 'ongoing' in text or 'updating' in text:
                        return 'Ongoing'
                    elif 'hiatus' in text:
                        return 'Hiatus'
                    elif 'dropped' in text:
                        return 'Dropped'
            except:
                continue
        return 'Unknown'
    
    def _extract_rating_from_soup(self, soup) -> float:
        """Extract rating from parsed soup - override in subclass for site-specific parsing"""
        # Common rating selectors
        rating_selectors = [
            '.rating-num', '.score', '.rate', '[class*="rating"]',
            '.num', '.vote', 'span[itemprop="ratingValue"]'
        ]
        
        for selector in rating_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True)
                    # Try to extract a number
                    match = re.search(r'(\d+\.?\d*)', text)
                    if match:
                        rating = float(match.group(1))
                        # Normalize to 5.0 scale if needed
                        if rating > 5.0:
                            rating = rating / 2.0  # Assume 10-point scale
                        return round(min(rating, 5.0), 2)
            except:
                continue
        return 0.0
    
    def _extract_description_from_soup(self, soup) -> str:
        """Extract description/summary from parsed soup"""
        desc_selectors = [
            '.summary', '.synopsis', '.description', '.desc',
            '[class*="summary"]', '[class*="synopsis"]', '[class*="description"]',
            '.entry-content', '.comic-description', 'div[itemprop="description"]'
        ]
        
        for selector in desc_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True)
                    if len(text) > 50:  # Reasonable description length
                        # Clean up the text
                        text = re.sub(r'\s+', ' ', text)
                        return text[:2000]  # Limit length
            except:
                continue
        return ""
    
    def _extract_author_from_soup(self, soup) -> str:
        """Extract author from parsed soup"""
        author_selectors = [
            '.author', '[class*="author"]', 'span:contains("Author")',
            '.writer', '[class*="writer"]'
        ]
        
        for selector in author_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True)
                    # Clean up common prefixes
                    text = re.sub(r'^(Author|Writer|By)[:\s]*', '', text, flags=re.I)
                    if text and len(text) < 100:
                        return text
            except:
                continue
        return ""
    
    def _extract_artist_from_soup(self, soup) -> str:
        """Extract artist from parsed soup"""
        artist_selectors = [
            '.artist', '[class*="artist"]', 'span:contains("Artist")',
            '.illustrator', '[class*="illustrator"]'
        ]
        
        for selector in artist_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True)
                    text = re.sub(r'^(Artist|Illustrator)[:\s]*', '', text, flags=re.I)
                    if text and len(text) < 100:
                        return text
            except:
                continue
        return ""
    
    def _extract_genres_from_soup(self, soup) -> List[str]:
        """Extract genres/tags from parsed soup.

        Tries to find the series-specific genre container rather than
        grabbing all genre links on the page (which includes navigation).
        """
        import re as _re
        genres = []
        seen = set()

        def _add_genres(links):
            """Add genre texts from a list of link elements."""
            for link in links:
                text = link.get_text(strip=True)
                if text and len(text) > 1 and len(text) < 50:
                    key = text.lower()
                    if key not in seen:
                        seen.add(key)
                        genres.append(text)

        # Strategy 1: ManhuaTo / WordPress manga themes
        # Look for a labeled "Genres" container: <div class="line"><span class="line-text">Genres</span>...
        genre_label = soup.find('span', class_='line-text', string=_re.compile(r'Genre', _re.I))
        if genre_label:
            container = genre_label.parent
            if container:
                _add_genres(container.select('a[href*="/genre/"]'))
                if genres:
                    return genres

        # Strategy 2: Look for .mgen (Flavor/Flavor-derived themes)
        mgen = soup.select_one('.mgen')
        if mgen:
            _add_genres(mgen.select('a'))
            if genres:
                return genres

        # Strategy 3: Look for .seriestugenre (SeriesTuContainer themes)
        stgenre = soup.select_one('.seriestugenre')
        if stgenre:
            _add_genres(stgenre.select('a'))
            if genres:
                return genres

        # Strategy 4: Look for dedicated genre containers
        for selector in ['.genres', '.genre', '.info-genre', '.tags-content']:
            container = soup.select_one(selector)
            if container:
                _add_genres(container.select('a'))
                if genres:
                    return genres

        # Strategy 5: Find a label element with "Genre" text and grab adjacent links
        for label_tag in ['span', 'b', 'strong', 'h3', 'h4', 'div', 'dt']:
            label = soup.find(label_tag, string=_re.compile(r'^Genres?\s*:?\s*$', _re.I))
            if label:
                # Check parent container for genre links
                parent = label.parent
                if parent:
                    _add_genres(parent.select('a[href*="/genre/"], a[href*="/tag/"]'))
                    if genres:
                        return genres
                # Check next sibling
                sibling = label.find_next_sibling()
                if sibling:
                    _add_genres(sibling.select('a') if hasattr(sibling, 'select') else [])
                    if genres:
                        return genres

        # Strategy 6: Asura/Flame-style genre spans within a specific info section
        for selector in ['.infox .spe', '.tsinfo', '.series-info']:
            info = soup.select_one(selector)
            if info:
                genre_spans = info.select('span a, span')
                for span in genre_spans:
                    text = span.get_text(strip=True)
                    if text and len(text) > 1 and len(text) < 50 and text.lower() != 'genre':
                        key = text.lower()
                        if key not in seen:
                            seen.add(key)
                            genres.append(text)
                if genres:
                    return genres

        return genres

    def _extract_cover_from_soup(self, soup) -> str:
        """Extract cover/thumbnail image URL from parsed soup.

        Tries multiple approaches since each site structures covers differently:
        1. og:image meta tag (most reliable, used by almost all sites)
        2. Common cover image CSS selectors
        3. Next.js /_next/image wrapper URLs (Flame Comics etc.)
        4. twitter:image meta tag
        """
        import urllib.parse

        def _clean_url(url: str) -> str:
            """Clean and normalize an image URL"""
            url = url.strip()
            if not url or url.startswith('data:'):
                return ''
            if url.startswith('//'):
                url = 'https:' + url
            # Unwrap Next.js image optimization URLs
            if '/_next/image' in url:
                parsed = urllib.parse.urlparse(url)
                params = urllib.parse.parse_qs(parsed.query)
                real_url = params.get('url', [''])[0]
                if real_url:
                    return real_url
            return url

        # 1. Try og:image (most reliable - every site sets this)
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img:
            url = _clean_url(og_img.get('content', ''))
            if url and 'http' in url:
                return url

        # 2. Try common cover image CSS selectors
        cover_selectors = [
            # ManhuaTo / WordPress manga themes
            '.summary_image img', '.thumb img', '.seriestuimg img',
            # Asura / modern sites
            '.series-thumb img', '.manga-thumb img', '.comic-thumb img',
            '.cover img', '[class*="cover"] img', '[class*="thumb"] img',
            # Webtoon
            '.detail_header img', '.thmb img',
            # General fallbacks
            '.info-image img', '.manga-info-pic img',
            '.seriesthumbs img', '.seriesimg img',
            'img[class*="cover"]', 'img[class*="thumb"]',
        ]

        for selector in cover_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    raw = elem.get('data-src') or elem.get('data-lazy-src') or elem.get('src', '')
                    url = _clean_url(raw)
                    if url and len(url) > 10 and not url.endswith('.gif'):
                        return url
            except:
                continue

        # 3. Next.js sites: find img tags with /_next/image src containing 'series'
        for img in soup.find_all('img', src=True):
            src = img.get('src', '')
            if '/_next/image' in src and 'series' in src:
                url = _clean_url(src)
                if url and 'http' in url:
                    return url

        # 4. Try twitter:image meta tag
        tw_img = soup.select_one('meta[name="twitter:image"]')
        if tw_img:
            url = _clean_url(tw_img.get('content', ''))
            if url and 'http' in url:
                return url

        return ""

    def _download_cover(self, cover_url: str, series_dir: Path, referer: str = '') -> Path:
        """Download series cover image and save to series directory.

        Returns the path to the downloaded cover, or None if failed.
        Kavita uses 'cover.jpg' (or cover.png/cover.webp) in the series folder
        as the series-level cover image.
        """
        if not cover_url:
            return None

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            if referer:
                headers['Referer'] = referer

            response = self.session.get(cover_url, headers=headers, timeout=30)
            response.raise_for_status()

            if len(response.content) < 1000:
                logger.debug(f"Cover image too small, likely an error page")
                return None

            # Determine extension from URL or content type
            content_type = response.headers.get('content-type', '').lower()
            if '.png' in cover_url.lower() or 'png' in content_type:
                ext = '.png'
            elif '.webp' in cover_url.lower() or 'webp' in content_type:
                ext = '.webp'
            else:
                ext = '.jpg'

            cover_path = series_dir / f"cover{ext}"
            cover_path.write_bytes(response.content)
            logger.info(f"Downloaded series cover: {cover_path.name} ({len(response.content)} bytes)")
            return cover_path

        except Exception as e:
            logger.warning(f"Failed to download cover from {cover_url}: {e}")
            return None

    def enrich_series_details(self, series: Series) -> Series:
        """Fetch both chapter count and status for a series"""
        series.chapters_count = self.get_chapter_count(series)
        if not series.status or series.status == 'Unknown':
            series.status = self.get_series_status(series)
        return series
    
    def enrich_with_full_details(self, series_list: List[Series], show_progress: bool = True) -> List[Series]:
        """Fetch full details (status, rating, description, etc.) for all series"""
        total = len(series_list)
        for i, series in enumerate(series_list, 1):
            if show_progress:
                logger.info(f"[{i}/{total}] Getting details for: {series.title}")
            
            series = self.get_series_details(series)
            
            if show_progress:
                status_str = f" ({series.status})" if series.status else ""
                rating_str = f" ★{series.rating}" if series.rating > 0 else ""
                logger.info(f"    → {series.chapters_count} chapters{status_str}{rating_str}")
            
            # Small delay to avoid rate limiting
            time.sleep(random.uniform(0.5, 1.5))
        return series_list
    
    def enrich_with_chapter_counts(self, series_list: List[Series], show_progress: bool = True, fetch_status: bool = True) -> List[Series]:
        """Fetch chapter counts and optionally status for all series in list"""
        # Use full details enrichment which includes everything
        return self.enrich_with_full_details(series_list, show_progress)
    
    def _create_comic_info_xml(self, series: Series, chapter: Chapter) -> str:
        """Create ComicInfo.xml content for CBZ metadata (Kavita-compatible)

        Kavita reads ComicInfo.xml v2.1 fields including:
        Series, Number, Title, Genre, Tags, Summary, CommunityRating,
        Writer, Penciller, Publisher, Web, Manga, Notes, Count,
        LanguageISO, Format, AgeRating, SeriesGroup
        """
        # Escape XML special characters
        def escape_xml(text: str) -> str:
            if not text:
                return ""
            return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))

        genres = ', '.join(series.genres) if series.genres else ''

        # Build XML
        xml_parts = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
            f'  <Series>{escape_xml(series.title)}</Series>',
            f'  <Number>{escape_xml(str(chapter.number))}</Number>',
            f'  <Title>{escape_xml(chapter.title)}</Title>',
        ]

        if genres:
            xml_parts.append(f'  <Genre>{escape_xml(genres)}</Genre>')
            # Also add as Tags (Kavita reads both Genre and Tags separately)
            xml_parts.append(f'  <Tags>{escape_xml(genres)}</Tags>')

        if series.description:
            xml_parts.append(f'  <Summary>{escape_xml(series.description)}</Summary>')

        if series.rating > 0:
            # CommunityRating in ComicInfo.xml is on a 5-point scale
            xml_parts.append(f'  <CommunityRating>{series.rating:.1f}</CommunityRating>')

        if series.author:
            xml_parts.append(f'  <Writer>{escape_xml(series.author)}</Writer>')

        if series.artist:
            xml_parts.append(f'  <Penciller>{escape_xml(series.artist)}</Penciller>')

        if series.url:
            xml_parts.append(f'  <Web>{escape_xml(series.url)}</Web>')

        # Total chapter count (Kavita uses Count to determine completion status)
        if series.chapters_count > 0:
            xml_parts.append(f'  <Count>{series.chapters_count}</Count>')

        # Publisher - use the source site name for organizational purposes
        if series.source:
            source_publishers = {
                'asura': 'Asura Scans',
                'flame': 'Flame Comics',
                'drake': 'Drake Comics',
                'manhuato': 'ManhuaTo',
                'webtoon': 'Webtoon',
            }
            publisher = source_publishers.get(series.source, series.source.title())
            xml_parts.append(f'  <Publisher>{escape_xml(publisher)}</Publisher>')

        # Reading direction: Manhwa/Manhua are LEFT-to-right (like Western comics)
        # Japanese Manga is RIGHT-to-left
        # Kavita uses: Yes = manga-style, YesAndRightToLeft = right-to-left
        source_lower = (series.source or '').lower()
        if source_lower in ('webtoon',):
            # Webtoons are vertical scroll, left-to-right
            xml_parts.append('  <Manga>Yes</Manga>')
        elif source_lower in ('manhuato',):
            # Manhua (Chinese) is left-to-right
            xml_parts.append('  <Manga>Yes</Manga>')
        else:
            # Manhwa (Korean) from Asura/Flame/Drake is also left-to-right
            # but many are formatted manga-style, use Yes as default
            xml_parts.append('  <Manga>Yes</Manga>')

        # Language
        xml_parts.append('  <LanguageISO>en</LanguageISO>')

        # Format
        xml_parts.append('  <Format>Web Comic</Format>')

        # Age rating - default to Teen unless we can detect otherwise
        xml_parts.append('  <AgeRating>Teen</AgeRating>')

        # Notes with source attribution
        if series.source:
            status_note = f" | Status: {series.status}" if series.status else ""
            xml_parts.append(f'  <Notes>Source: {escape_xml(series.source)}{status_note}</Notes>')

        xml_parts.append('</ComicInfo>')

        return '\n'.join(xml_parts)
    
    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter - override in subclass"""
        raise NotImplementedError
    
    def download_chapter(self, chapter: Chapter, series_title: str,
                        output_dir: Path, tracker: ProgressTracker,
                        series: Series = None) -> bool:
        """Download a chapter and create CBZ with metadata"""

        safe_title = self._sanitize_filename(series_title)
        safe_chapter = self._sanitize_filename(chapter.number)

        series_dir = output_dir / safe_title
        cbz_name = f"{safe_title} - Chapter {safe_chapter}.cbz"
        cbz_path = series_dir / cbz_name

        # Check if already downloaded — but only trust the cache if the CBZ file
        # actually exists on disk.  If the file was deleted, re-download it.
        if tracker.is_downloaded(chapter.url):
            if cbz_path.exists():
                logger.debug(f"Skipping (already downloaded): {series_title} Ch.{chapter.number}")
                return True
            else:
                # File was deleted — clear from cache so we re-download
                tracker.downloaded.discard(chapter.url)
                tracker.save()
                logger.info(f"Re-downloading (file missing): {cbz_name}")

        series_dir.mkdir(parents=True, exist_ok=True)

        # Download series cover image once (if not already present)
        if series and series.cover_url:
            existing_covers = list(series_dir.glob('cover.*'))
            if not existing_covers:
                self._download_cover(series.cover_url, series_dir, referer=series.url)

        if cbz_path.exists():
            tracker.mark_downloaded(chapter.url)
            logger.info(f"Already exists: {cbz_name}")
            return True

        logger.info(f"Downloading: {series_title} - Chapter {chapter.number}")

        # Store cover media ID so get_pages() can exclude it from chapter images
        self._cover_media_ids = set()
        if series and series.cover_url and 'asuracomic' in series.cover_url:
            m = re.search(r'/media/(\d+)/', series.cover_url)
            if m:
                self._cover_media_ids.add(int(m.group(1)))

        try:
            pages = self.get_pages(chapter)
            if not pages:
                logger.error(f"No pages found for chapter {chapter.number}")
                return False
            
            # Create temp directory for images
            temp_dir = series_dir / f".temp_{safe_chapter}"
            temp_dir.mkdir(exist_ok=True)
            
            # Download images concurrently (CDN images, no rate limiting needed)
            success_count = 0
            download_tasks = []
            for i, page_url in enumerate(pages, 1):
                ext = self._get_extension(page_url)
                img_path = temp_dir / f"{i:03d}{ext}"
                download_tasks.append((i, page_url, img_path))

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(self._download_image, url, path, chapter.url): page_num
                    for page_num, url, path in download_tasks
                }
                for future in as_completed(futures):
                    page_num = futures[future]
                    if future.result():
                        success_count += 1
                    else:
                        logger.warning(f"Failed to download page {page_num}")
            
            if success_count == 0:
                logger.error(f"No images downloaded for chapter {chapter.number}")
                return False
            
            # Create CBZ with metadata
            self._create_cbz(temp_dir, cbz_path, series, chapter)
            
            # Cleanup
            for f in temp_dir.iterdir():
                f.unlink()
            temp_dir.rmdir()
            
            # Mark as downloaded
            tracker.mark_downloaded(chapter.url)
            
            logger.info(f"Created: {cbz_name} ({success_count} pages)")
            return True
            
        except Exception as e:
            logger.error(f"Error downloading chapter: {e}")
            return False
    
    def _download_image(self, url: str, path: Path, referer: str) -> bool:
        """Download an image file"""
        try:
            headers = {
                'Referer': referer,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            if len(response.content) < 1000:  # Likely an error page
                return False
            
            path.write_bytes(response.content)
            return True
        except Exception as e:
            logger.debug(f"Failed to download {url}: {e}")
            return False
    
    def _create_cbz(self, source_dir: Path, output_path: Path, series: Series = None, chapter: Chapter = None):
        """Create CBZ archive from images with optional ComicInfo.xml metadata.

        Kavita selects the first file in the archive that has the word 'cover'
        in its name as the chapter/series cover. If none found, it uses the first
        image sorted naturally. We embed the series cover as '!000_cover.ext' so
        it sorts first and is recognized by Kavita as the cover image.
        """
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add series cover as the designated cover image if available
            # The '!' prefix ensures it sorts before numbered pages (001.jpg, etc.)
            if series and series.cover_url:
                series_dir = output_path.parent
                cover_files = list(series_dir.glob('cover.*'))
                if cover_files:
                    cover_file = cover_files[0]
                    cover_name = f"!000_cover{cover_file.suffix}"
                    zf.write(cover_file, cover_name)

            # Add chapter page images
            for img_file in sorted(source_dir.iterdir()):
                if img_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                    zf.write(img_file, img_file.name)

            # Add ComicInfo.xml if we have metadata
            if series and chapter:
                comic_info = self._create_comic_info_xml(series, chapter)
                zf.writestr('ComicInfo.xml', comic_info.encode('utf-8'))
    
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize filename for filesystem"""
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        name = re.sub(r'\s+', ' ', name)
        name = name.strip()
        return name[:200]
    
    @staticmethod
    def _get_extension(url: str) -> str:
        """Get file extension from URL"""
        url_lower = url.lower()
        if '.png' in url_lower:
            return '.png'
        elif '.webp' in url_lower:
            return '.webp'
        elif '.gif' in url_lower:
            return '.gif'
        return '.jpg'


class AsuraFullScraper(BaseSiteScraper):
    """Full site scraper for asuracomic.net"""

    BASE_URL = "https://asuracomic.net"
    SITE_NAME = "asura"
    CLOUDFLARE_SITE = True
    
    def get_series_details(self, series: Series) -> Series:
        """Fetch full details from Asura's series page.

        Asura uses a Next.js app with Tailwind classes. Key HTML patterns:
        - Genres: <b>Genres:</b> followed by <a href="/series?page=1&genres=N">
        - Synopsis: <h3>Synopsis ...</h3><span ...><p>text</p></span>
        - Status/Type: <h3>Status</h3><h3 class="... capitalize">Ongoing</h3>
        - Author/Artist: <h3>Author</h3><h3>Name</h3> in a grid
        - Rating: <div class="inline-block ml-[5px] ...">9.7</div>
        """
        try:
            soup = self._get_soup(series.url, use_selenium=True)

            # --- Genres ---
            if not series.genres:
                genre_links = soup.select('a[href*="/series?page=1&genres="]')
                if genre_links:
                    genres = []
                    for link in genre_links:
                        text = link.get_text(strip=True).strip(',').strip()
                        if text and text.lower() != 'genres':
                            genres.append(text)
                    if genres:
                        # Deduplicate (page has desktop + mobile copies)
                        seen = set()
                        unique = []
                        for g in genres:
                            if g.lower() not in seen:
                                seen.add(g.lower())
                                unique.append(g)
                        series.genres = unique

            # --- Synopsis ---
            if not series.description:
                html = str(soup)

                # Strategy 1: Look for h3 containing "Synopsis" then grab next sibling's <p>
                for h3 in soup.select('h3'):
                    if 'Synopsis' in h3.get_text():
                        sibling = h3.find_next_sibling('span')
                        if sibling:
                            p = sibling.find('p')
                            text = (p or sibling).get_text(strip=True)
                            # Strip Asura promo prefix like [By ... that brought you ...!]
                            text = re.sub(r'^\s*\[.*?(?:brought you|studio).*?\]\s*', '', text, flags=re.I | re.S)
                            text = text.strip()
                            if len(text) > 20:
                                series.description = re.sub(r'\s+', ' ', text)[:2000]
                                break

                # Strategy 2: Extract from Next.js serialized data
                if not series.description:
                    # Descriptions in Next.js data often appear as "description":"..."
                    desc_matches = re.findall(
                        r'"description"\s*:\s*"((?:[^"\\]|\\.){20,})"',
                        html
                    )
                    for raw_desc in desc_matches:
                        # Unescape JSON string
                        text = raw_desc.replace('\\n', ' ').replace('\\"', '"').replace('\\\\', '\\')
                        # Strip Asura promo prefix
                        text = re.sub(r'^\s*\[.*?(?:brought you|studio).*?\]\s*', '', text, flags=re.I | re.S)
                        text = re.sub(r'\s+', ' ', text).strip()
                        if len(text) > 20:
                            series.description = text[:2000]
                            break

            # --- Status ---
            if not series.status or series.status in ['', 'Unknown']:
                for h3 in soup.select('h3'):
                    if h3.get_text(strip=True) == 'Status':
                        next_h3 = h3.find_next_sibling('h3')
                        if next_h3:
                            text = next_h3.get_text(strip=True).lower()
                            if 'completed' in text or 'finished' in text:
                                series.status = 'Completed'
                            elif 'ongoing' in text:
                                series.status = 'Ongoing'
                            elif 'hiatus' in text:
                                series.status = 'Hiatus'
                            elif 'dropped' in text:
                                series.status = 'Dropped'
                        break

            # --- Rating ---
            if series.rating == 0.0:
                # Rating is in an italic div like: <div class="inline-block ml-[5px] ... italic ...">9.7</div>
                for div in soup.select('div[class*="italic"]'):
                    text = div.get_text(strip=True)
                    try:
                        val = float(text)
                        if 0 < val <= 10:
                            series.rating = round(val / 2, 2) if val > 5 else round(val, 2)
                            break
                    except ValueError:
                        continue

            # --- Author ---
            if not series.author:
                for h3 in soup.select('h3'):
                    if h3.get_text(strip=True) == 'Author':
                        next_h3 = h3.find_next_sibling('h3')
                        if next_h3:
                            text = next_h3.get_text(strip=True)
                            if text and text != '_':
                                series.author = text
                        break

            # --- Artist ---
            if not series.artist:
                for h3 in soup.select('h3'):
                    if h3.get_text(strip=True) == 'Artist':
                        next_h3 = h3.find_next_sibling('h3')
                        if next_h3:
                            text = next_h3.get_text(strip=True)
                            if text and text != '_':
                                series.artist = text
                        break

            # --- Cover ---
            if not series.cover_url:
                series.cover_url = self._extract_cover_from_soup(soup)

            # --- Chapter count ---
            if series.chapters_count == 0:
                try:
                    chapters = self.get_chapters(series)
                    series.chapters_count = len(chapters)
                except Exception:
                    pass

            return series
        except Exception as e:
            logger.debug(f"Error getting details for {series.title}: {e}")
            return series
    
    def get_all_series(self) -> List[Series]:
        """Get all series from Asura Scans"""
        logger.info("Fetching all series from Asura Scans...")
        
        all_series = []
        seen_urls = set()  # Track across ALL pages
        page = 1
        
        while True:
            url = f"{self.BASE_URL}/series?page={page}"
            logger.info(f"Fetching page {page}...")
            
            try:
                # Use Selenium with extra wait time for dynamic content
                self._init_driver()
                self.driver.get(url)
                
                # Wait for grid to load - the series are in a grid container
                time.sleep(4)  # Initial wait for JS to execute
                
                # Scroll down to trigger any lazy loading
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
                time.sleep(1)
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
                
                # Get page source after JS has loaded
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                
                # Debug: log page title to confirm we're on the right page
                page_title = soup.select_one('title')
                logger.debug(f"Page title: {page_title.get_text() if page_title else 'No title'}")
                
                # Find the grid container first - specifically the main content grid, not sidebar
                # The main grid has specific classes that distinguish it from the Popular sidebar
                grid = soup.select_one('div.grid.grid-cols-2.sm\\:grid-cols-2.md\\:grid-cols-5')
                if not grid:
                    grid = soup.select_one('div[class*="grid-cols-5"]')
                if not grid:
                    grid = soup.select_one('div.grid[class*="grid-cols"]')
                
                items = []
                if grid:
                    # Find all series links within the grid only
                    items = grid.select('a[href*="series/"]')
                    logger.debug(f"Found {len(items)} items in grid")
                
                # Fallback: find all series links but be more selective
                if not items:
                    # Only get links that have the series slug pattern
                    all_links = soup.select('a[href*="series/"]')
                    items = [a for a in all_links if re.search(r'series/[\w-]+-[a-f0-9]+$', a.get('href', ''))]
                    logger.debug(f"Fallback: found {len(items)} series links")
                
                if not items:
                    logger.info(f"No more series found on page {page}")
                    break
                
                found_count = 0
                
                for item in items:
                    href = item.get('href', '')
                    
                    # Skip if not a valid series link
                    if not href or 'series/' not in href:
                        continue
                    
                    # Normalize URL for deduplication
                    # Remove trailing slashes and query params
                    normalized_href = href.rstrip('/').split('?')[0]
                    
                    # Skip duplicates (check normalized version)
                    if normalized_href in seen_urls:
                        continue
                    seen_urls.add(normalized_href)
                    
                    # Build full URL
                    if href.startswith('http'):
                        full_url = href
                    elif href.startswith('/'):
                        full_url = self.BASE_URL + href
                    else:
                        full_url = self.BASE_URL + '/' + href
                    
                    # Get title - need to find the actual title, not badges like "MANHWA"
                    title = None
                    cover_url = ""

                    # Method 1: img alt attribute (most reliable) + grab cover URL
                    img = item.select_one('img')
                    if img:
                        alt = img.get('alt', '').strip()
                        # Skip if alt is just a type badge
                        if alt and len(alt) > 3 and alt.upper() not in ['MANHWA', 'MANHUA', 'MANGA', 'WEBTOON']:
                            title = alt
                        # Grab cover image URL from the listing card
                        raw_src = img.get('src') or img.get('data-src') or ''
                        raw_src = raw_src.strip()
                        if raw_src and not raw_src.startswith('data:'):
                            if raw_src.startswith('//'):
                                raw_src = 'https:' + raw_src
                            cover_url = raw_src
                    
                    # Method 2: Look for span with font-bold that has actual title text
                    if not title:
                        for span in item.select('span[class*="font-bold"], span.font-bold'):
                            text = span.get_text(strip=True)
                            # Skip badges and short text
                            if (text and len(text) > 3 and 
                                text.upper() not in ['MANHWA', 'MANHUA', 'MANGA', 'WEBTOON', 'ONGOING', 'COMPLETED', 'HIATUS', 'DROPPED', 'NEW', 'HOT'] and
                                not text.replace('.', '').replace(',', '').isdigit() and
                                'chapter' not in text.lower()):
                                title = text
                                break
                    
                    # Method 3: Look for any text in nested link
                    if not title:
                        nested_link = item.select_one('a[href*="series/"]')
                        if nested_link:
                            # Get text that's not in a badge span
                            for child in nested_link.children:
                                if hasattr(child, 'name') and child.name == 'span':
                                    text = child.get_text(strip=True)
                                    if (text and len(text) > 3 and 
                                        text.upper() not in ['MANHWA', 'MANHUA', 'MANGA', 'WEBTOON', 'ONGOING', 'COMPLETED', 'HIATUS']):
                                        title = text
                                        break
                    
                    if not title or len(title) < 2:
                        continue
                    
                    # Clean title
                    title = title.strip()
                    
                    # Get status if visible on card
                    status = ''
                    status_elem = item.select_one('span.status, span[class*="status"], span[class*="bg-blue"], span[class*="bg-green"], span[class*="bg-red"]')
                    if status_elem:
                        status_text = status_elem.get_text(strip=True).lower()
                        if 'ongoing' in status_text:
                            status = 'Ongoing'
                        elif 'completed' in status_text or 'complete' in status_text:
                            status = 'Completed'
                        elif 'hiatus' in status_text:
                            status = 'Hiatus'
                    
                    # Get rating if visible
                    rating = 0.0
                    rating_elem = item.select_one('span.text-xs, span[class*="ml-1"]')
                    if rating_elem:
                        try:
                            rating_text = rating_elem.get_text(strip=True)
                            rating_match = re.search(r'(\d+\.?\d*)', rating_text)
                            if rating_match:
                                rating = float(rating_match.group(1))
                                if rating > 5:
                                    rating = rating / 2  # Normalize 10-point to 5-point
                        except:
                            pass
                    
                    series = Series(
                        title=title,
                        url=full_url,
                        source=self.SITE_NAME,
                        status=status,
                        rating=round(rating, 2),
                        cover_url=cover_url
                    )
                    all_series.append(series)
                    found_count += 1
                    logger.debug(f"Found: {title}")
                    
                    # Check limit
                    if self.limit and len(all_series) >= self.limit:
                        logger.info(f"Reached limit of {self.limit} series")
                        break
                
                # Check limit after page
                if self.limit and len(all_series) >= self.limit:
                    break
                
                logger.info(f"Found {found_count} series on page {page}")
                
                if found_count == 0:
                    break
                
                page += 1
                
                # Safety limit
                if page > 200:
                    logger.warning("Reached page limit (200)")
                    break
                
                time.sleep(1)  # Be nice to the server
                    
            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                break
        
        logger.info(f"Total series found: {len(all_series)}")
        return all_series
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        """Get all chapters for a series"""
        soup = self._get_soup(series.url, use_selenium=True)

        chapters = []
        seen_urls = set()

        # Look for chapter links - on Asura they're typically in a list
        for link in soup.select('a[href*="chapter"]'):
            href = link.get('href', '').strip()

            if not href:
                continue

            # Build full URL - handle relative paths that don't start with /
            if href.startswith('http'):
                full_url = href
            elif href.startswith('/'):
                full_url = self.BASE_URL + href
            else:
                # Relative path like "series-name/chapter/1" needs /series/ prefix
                full_url = self.BASE_URL + '/series/' + href

            # Skip duplicates
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Extract chapter number from URL first (most reliable)
            match = re.search(r'chapter[/\- ]?(\d+(?:\.\d+)?)', href, re.I)

            # Extract chapter title from the first text node or span only,
            # avoiding date/time spans that get concatenated by get_text()
            title = None
            title_elem = link.select_one('.chapternum, .epl-num, .epxs, span:first-child')
            if title_elem:
                title = title_elem.get_text(strip=True)
            if not title:
                # Use direct text content of the link, excluding child elements
                title = link.find(string=True, recursive=False)
                if title:
                    title = title.strip()

            if not match and title:
                match = re.search(r'chapter[/\- ]?(\d+(?:\.\d+)?)', title, re.I)

            if match:
                num = match.group(1)
                # Clean title: use extracted title or fall back to "Chapter N"
                clean_title = title if title else f"Chapter {num}"
                # If title still has date junk concatenated, just use "Chapter N"
                if re.search(r'chapter\s*\d.*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', clean_title, re.I):
                    clean_title = f"Chapter {num}"
                chapters.append(Chapter(
                    number=num,
                    title=clean_title,
                    url=full_url
                ))

        # Sort by chapter number (ascending)
        chapters.sort(key=lambda x: float(x.number) if x.number.replace('.', '').isdigit() else 0)
        return chapters

    @staticmethod
    def _get_media_id(url: str) -> int:
        """Extract numeric media ID from an Asura CDN URL."""
        m = re.search(r'/media/(\d+)/', url)
        return int(m.group(1)) if m else 0

    def _filter_outlier_images(self, pages: List[str]) -> List[str]:
        """Remove sidebar/cover images that don't belong to the chapter.

        Chapter page images have sequential media IDs clustered together.
        Sidebar covers have isolated media IDs far from the main cluster.
        Also excludes any media IDs matching the known series cover.
        """
        if len(pages) <= 3:
            return pages  # Too few to reliably detect outliers

        # Get known cover media IDs to exclude
        cover_ids = getattr(self, '_cover_media_ids', set())

        # Extract media IDs and pair with URLs
        id_url_pairs = [(self._get_media_id(url), url) for url in pages]

        # First pass: exclude known cover media IDs
        if cover_ids:
            before = len(id_url_pairs)
            id_url_pairs = [(mid, url) for mid, url in id_url_pairs if mid not in cover_ids]
            removed = before - len(id_url_pairs)
            if removed:
                logger.info(f"Excluded {removed} image(s) matching series cover media ID")

        if len(id_url_pairs) <= 3:
            return [url for _, url in id_url_pairs]

        # Second pass: outlier detection via clustering
        # Chapter images have consecutive/close media IDs; sidebar images are far away
        ids = sorted(mid for mid, _ in id_url_pairs)
        gaps = [ids[i+1] - ids[i] for i in range(len(ids) - 1)]

        if not gaps:
            return [url for _, url in id_url_pairs]

        # Median gap between consecutive chapter images (usually 1-5)
        sorted_gaps = sorted(gaps)
        median_gap = sorted_gaps[len(sorted_gaps) // 2]

        # Threshold: if a gap is >50x the median AND >100, it's a cluster break
        threshold = max(median_gap * 50, 100)

        # Find the largest contiguous cluster
        clusters = [[ids[0]]]
        for i, gap in enumerate(gaps):
            if gap > threshold:
                clusters.append([ids[i+1]])
            else:
                clusters[-1].append(ids[i+1])

        # The main cluster is the one with the most IDs
        main_cluster = max(clusters, key=len)
        main_ids = set(main_cluster)

        # Filter to only keep images in the main cluster
        filtered = [(mid, url) for mid, url in id_url_pairs if mid in main_ids]
        outliers_removed = len(id_url_pairs) - len(filtered)
        if outliers_removed > 0:
            logger.info(f"Removed {outliers_removed} outlier image(s) outside chapter media ID cluster")

        return [url for _, url in filtered]

    def _extract_asura_images(self, html: str) -> List[str]:
        """Extract chapter image URLs from Asura HTML (Next.js data or img tags).

        Returns a sorted, deduplicated list of image URLs, or empty list if none found.
        """
        # --- Strategy 1: extract from Next.js serialised data ---
        # URLs look like: https://gg.asuracomic.net/storage/media/319264/conversions/01-optimized.webp
        # They appear inside escaped JSON in <script> tags.
        raw_urls = re.findall(
            r'https?://gg\.asuracomic\.net/storage/media/\d+/conversions/[^"\\]+\.(?:webp|jpg|png)',
            html
        )

        # Deduplicate while preserving order
        seen = set()
        pages = []
        for url in raw_urls:
            # Skip sidebar cover thumbnails (thumb-small, thumb-medium)
            if '-thumb-' in url:
                continue
            if url not in seen:
                seen.add(url)
                pages.append(url)

        if pages:
            # Sort by the media ID to get correct page order
            pages.sort(key=lambda u: self._get_media_id(u))
            # Filter out sidebar/cover images
            pages = self._filter_outlier_images(pages)
            if pages:
                logger.info(f"Found {len(pages)} chapter images from Next.js data")
                return pages

        # --- Strategy 2: fallback to <img> tags (legacy / Selenium) ---
        soup = BeautifulSoup(html, 'html.parser')
        pages = []
        for img in soup.select('img'):
            src = img.get('src', img.get('data-src', ''))
            if not src:
                continue
            if 'gg.asuracomic.net/storage/media/' not in src:
                continue
            if '/profile_images/' in src or '/profile/' in src:
                continue
            if '/conversions/' in src and '-thumb-' not in src and src not in pages:
                pages.append(src)

        if pages:
            pages = self._filter_outlier_images(pages)
            if pages:
                logger.info(f"Found {len(pages)} chapter images from img tags")
        return pages

    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter from Asura Scans.

        Asura is a Next.js app — chapter images are NOT in <img> tags in the
        initial HTML.  They're serialised inside self.__next_f.push() script
        blocks.  A plain HTTP fetch (or FlareSolverr) returns the full HTML
        including these scripts, so we can extract URLs with a regex instead
        of needing Selenium to render the page.

        If the initial fetch returns no images (e.g. stale cookies gave us a
        Cloudflare challenge page), we force a fresh FlareSolverr request and
        retry once before giving up.
        """
        max_attempts = 2 if self._use_flaresolverr else 1

        for attempt in range(1, max_attempts + 1):
            try:
                soup = self._get_soup(chapter.url, use_selenium=True)
                html = str(soup)

                pages = self._extract_asura_images(html)
                if pages:
                    return pages

                # No images found — on first attempt, force fresh FlareSolverr cookies
                if attempt < max_attempts and self._use_flaresolverr:
                    logger.warning(
                        f"No images found for {chapter.url} (attempt {attempt}), "
                        f"forcing fresh FlareSolverr request..."
                    )
                    # Clear stale cookies so _get_soup() goes through FlareSolverr again
                    self._fs_cookies_applied = False
                    self.session.cookies.clear()
                    time.sleep(2)  # Brief pause before retry
                    continue

                # Final attempt exhausted
                logger.warning(f"No chapter images found for {chapter.url} after {attempt} attempt(s)")
                return []

            except Exception as e:
                logger.error(f"Error getting pages (attempt {attempt}): {e}")
                if attempt < max_attempts:
                    self._fs_cookies_applied = False
                    self.session.cookies.clear()
                    time.sleep(2)
                    continue
                return []

        return []


class FlameFullScraper(BaseSiteScraper):
    """Full site scraper for flamecomics.xyz"""

    BASE_URL = "https://flamecomics.xyz"
    SITE_NAME = "flame"
    CLOUDFLARE_SITE = True
    
    def get_all_series(self) -> List[Series]:
        """Get all series from Flame Comics"""
        logger.info("Fetching all series from Flame Comics...")
        
        all_series = []
        
        # Flame uses a single browse page with infinite scroll or pagination
        url = f"{self.BASE_URL}/browse"
        logger.info(f"Fetching browse page...")
        
        try:
            self._init_driver()
            self.driver.get(url)
            time.sleep(3)
            
            # Scroll to load more content
            last_height = 0
            scroll_attempts = 0
            max_scrolls = 20
            
            while scroll_attempts < max_scrolls:
                # Scroll down
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    scroll_attempts += 1
                    if scroll_attempts >= 3:  # No new content after 3 attempts
                        break
                else:
                    scroll_attempts = 0
                last_height = new_height
                
                logger.info(f"Scrolling... found more content")
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Find series cards - they have links to /series/
            seen_urls = set()
            
            # Method 1: Links containing /series/
            for link in soup.select('a[href*="/series/"]'):
                href = link.get('href', '').strip()
                if not href or href in seen_urls:
                    continue
                
                # Skip chapter links
                if '/chapter' in href.lower():
                    continue
                    
                seen_urls.add(href)
                
                # Get title - try multiple methods
                title = None
                
                # Method 1: Look for title link with DescSeriesCard_title class (from screenshot)
                title_link = None
                parent_card = link.find_parent('div', recursive=True)
                if parent_card:
                    title_link = parent_card.select_one('a[class*="title"], a[class*="Title"]')
                    if title_link:
                        title = title_link.get_text(strip=True)
                
                # Method 2: Look for title in nearby heading or strong elements
                if not title and parent_card:
                    title_elem = parent_card.select_one('h3, h4, strong, [class*="title"]')
                    if title_elem:
                        text = title_elem.get_text(strip=True)
                        # Skip country codes and badges
                        if text and len(text) > 2 and text.upper() not in ['CN', 'KR', 'JP', 'EN', 'MANHWA', 'MANHUA', 'MANGA']:
                            title = text
                
                # Method 3: Try img alt
                if not title:
                    img = link.select_one('img')
                    if img:
                        alt = img.get('alt', '').strip()
                        if alt and len(alt) > 2 and alt.upper() not in ['CN', 'KR', 'JP', 'EN']:
                            title = alt
                
                # Method 4: Try link text but filter out badges
                if not title:
                    text = link.get_text(strip=True)
                    if text and len(text) > 2 and text.upper() not in ['CN', 'KR', 'JP', 'EN', 'MANHWA', 'MANHUA', 'MANGA', 'NEW', 'HOT']:
                        title = text
                
                if not title or len(title) < 3:
                    continue
                
                # Skip if title is just a country code or badge
                if title.upper() in ['CN', 'KR', 'JP', 'EN', 'MANHWA', 'MANHUA', 'MANGA', 'NEW', 'HOT', 'ONGOING', 'COMPLETED']:
                    continue
                
                # Clean title - remove chapter info
                if 'chapter' in title.lower():
                    continue
                
                full_url = href if href.startswith('http') else self.BASE_URL + href
                
                # Get genres if available
                genres = []
                genre_container = link.find_parent('div', recursive=True)
                if genre_container:
                    for span in genre_container.select('span'):
                        text = span.get_text(strip=True).upper()
                        if text in ['ACTION', 'FANTASY', 'COMEDY', 'ADVENTURE', 'ROMANCE', 'DRAMA', 'SHOUNEN', 'SHOUJO', 'CULTIVATION']:
                            genres.append(text.title())
                
                # Get status
                status = ''
                status_elem = link.find_parent('div')
                if status_elem:
                    status_badge = status_elem.select_one('[class*="badge"], [class*="status"]')
                    if status_badge:
                        status_text = status_badge.get_text(strip=True).lower()
                        if 'dropped' in status_text:
                            status = 'Dropped'
                        elif 'hiatus' in status_text:
                            status = 'Hiatus'
                        elif 'completed' in status_text or 'complete' in status_text:
                            status = 'Completed'
                        elif 'ongoing' in status_text:
                            status = 'Ongoing'
                
                series = Series(
                    title=title,
                    url=full_url,
                    source=self.SITE_NAME,
                    genres=genres,
                    status=status
                )
                all_series.append(series)
                logger.debug(f"Found: {title}")
                
                # Check limit
                if self.limit and len(all_series) >= self.limit:
                    logger.info(f"Reached limit of {self.limit} series")
                    break
                
        except Exception as e:
            logger.error(f"Error fetching Flame Comics: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        # Deduplicate by URL
        seen = set()
        unique_series = []
        for s in all_series:
            if s.url not in seen:
                seen.add(s.url)
                unique_series.append(s)
        
        logger.info(f"Total series found: {len(unique_series)}")
        return unique_series
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        soup = self._get_soup(series.url, use_selenium=True)

        chapters = []
        seen_urls = set()

        # Extract series ID from URL (e.g., /series/12 -> 12)
        series_id_match = re.search(r'/series/(\d+)', series.url)
        series_id = series_id_match.group(1) if series_id_match else None

        # Flame uses /series/ID/HASH format for chapter links
        # Look for links that match the series pattern
        for link in soup.select('a[href]'):
            href = link.get('href', '').strip()
            text = link.get_text(strip=True)

            if not href:
                continue

            # Match Flame chapter URL pattern: /series/ID/HASH
            is_chapter = False
            if series_id and re.match(rf'^/series/{series_id}/[a-f0-9]+$', href):
                is_chapter = True
            elif 'chapter' in href.lower() or 'chapter' in text.lower():
                is_chapter = True

            if not is_chapter:
                continue

            # Build full URL
            if href.startswith('http'):
                full_url = href
            elif href.startswith('/'):
                full_url = self.BASE_URL + href
            else:
                full_url = self.BASE_URL + '/' + href

            # Skip if already seen or is a series-level link (no hash)
            if full_url in seen_urls:
                continue
            # Skip "First Chapter" and "Latest Chapter" meta-links (handle them by content)
            if text.lower() in ('first chapter', 'latest chapter'):
                continue
            seen_urls.add(full_url)

            # Extract chapter number from text like "Chapter 192"
            # Text may have trailing timestamps like "4 years ago6" so be careful
            match = re.search(r'chapter\s*(\d+(?:\.\d+)?)', text, re.I)
            if not match:
                match = re.search(r'chapter[/\- ]?(\d+(?:\.\d+)?)', href, re.I)
            if not match:
                # Try just a leading number
                match = re.match(r'(\d+(?:\.\d+)?)', text.strip())

            if match:
                num = match.group(1)
                chapters.append(Chapter(number=num, title=f"Chapter {num}", url=full_url))

        # Sort by chapter number (ascending)
        chapters.sort(key=lambda x: float(x.number) if x.number.replace('.', '').isdigit() else 0)
        return chapters

    def get_pages(self, chapter: Chapter) -> List[str]:
        soup = self._get_soup(chapter.url, use_selenium=True)

        pages = []
        for img in soup.select('img'):
            src = img.get('data-src') or img.get('src', '')
            src = src.strip()
            if not src:
                continue

            # Only accept images from Flame's CDN with uploads/images/series path
            if 'cdn.flamecomics.xyz/uploads/images/series/' not in src:
                continue

            # Skip watermark/branding images
            if '/shared/' in src or '/assets/' in src:
                continue

            if src not in pages:
                pages.append(src)

        # Fallback: broader CDN match
        if not pages:
            for img in soup.select('img'):
                src = img.get('data-src') or img.get('src', '')
                src = src.strip()
                if src and 'cdn.flamecomics.xyz' in src and '/shared/' not in src and '/assets/' not in src:
                    if src not in pages:
                        pages.append(src)

        return pages


class WebtoonScraper(BaseSiteScraper):
    """Full site scraper for webtoons.com (official platform)"""
    
    BASE_URL = "https://www.webtoons.com"
    SITE_NAME = "webtoon"
    
    # Webtoon genres for ORIGINALS
    GENRES = [
        'drama', 'fantasy', 'comedy', 'action', 'slice-of-life', 'romance',
        'superhero', 'sci-fi', 'thriller', 'supernatural', 'mystery', 
        'sports', 'historical', 'heartwarming', 'horror', 'informative'
    ]
    
    def __init__(self, headless: bool = True, canvas: bool = False, limit: int = None):
        super().__init__(headless, limit=limit)
        self.canvas = canvas  # If True, scrape CANVAS instead of ORIGINALS
        # Webtoon requires specific headers
        self.session.headers.update({
            'Referer': 'https://www.webtoons.com/',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        })
    
    def get_all_series(self) -> List[Series]:
        """Get all series from Webtoons (ORIGINALS or CANVAS)"""
        if self.canvas:
            return self._get_canvas_series()
        return self._get_originals_series()
    
    def _get_originals_series(self) -> List[Series]:
        """Get all ORIGINALS series by genre"""
        logger.info("Fetching all ORIGINALS series from Webtoons...")
        
        all_series = []
        seen_urls = set()
        
        for genre in self.GENRES:
            logger.info(f"Fetching genre: {genre}")
            url = f"{self.BASE_URL}/en/genres/{genre}"
            
            try:
                self._init_driver()
                self.driver.get(url)
                time.sleep(3)
                
                # Scroll to load all content
                last_height = 0
                for _ in range(5):
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                    new_height = self.driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        break
                    last_height = new_height
                
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                
                # Method 1: Find series in webtoon_list
                for item in soup.select('ul.webtoon_list li'):
                    try:
                        # Get the main link
                        link = item.select_one('a.link_genre_title_a, a[href*="title_no"]')
                        if not link:
                            continue
                        
                        href = link.get('href', '').strip()
                        if not href or href in seen_urls:
                            continue
                        
                        # Extract title from strong.title or data attribute
                        title = None
                        title_elem = item.select_one('strong.title')
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                        
                        if not title:
                            # Try getting from link text
                            title = link.get_text(strip=True)
                        
                        if not title or len(title) < 2:
                            continue
                        
                        # Build full URL
                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        
                        # Extract title_no from URL
                        title_no_match = re.search(r'title_no=(\d+)', full_url)
                        if not title_no_match:
                            continue
                        
                        seen_urls.add(full_url)
                        
                        # Get author if available
                        author = ''
                        author_elem = item.select_one('div.author, .author')
                        if author_elem:
                            author = author_elem.get_text(strip=True)
                        
                        series = Series(
                            title=title,
                            url=full_url,
                            source=self.SITE_NAME,
                            genres=[genre.replace('-', ' ').title()],
                            author=author
                        )
                        all_series.append(series)
                        logger.debug(f"Found: {title}")
                        
                        # Check limit
                        if self.limit and len(all_series) >= self.limit:
                            logger.info(f"Reached limit of {self.limit} series")
                            break
                    except Exception as e:
                        logger.debug(f"Error parsing series: {e}")
                        continue
                
                # Check limit after genre
                if self.limit and len(all_series) >= self.limit:
                    break
                
                # Method 2: Fallback to card items (older structure)
                if not all_series:
                    for card in soup.select('a.card_item, a[href*="title_no"]'):
                        href = card.get('href', '')
                        if not href or href in seen_urls:
                            continue
                        
                        title_elem = card.select_one('.info .subj, strong.title, .subj')
                        if not title_elem:
                            continue
                        
                        title = title_elem.get_text(strip=True)
                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        
                        title_no_match = re.search(r'title_no=(\d+)', full_url)
                        if not title_no_match:
                            continue
                        
                        seen_urls.add(full_url)
                        
                        series = Series(
                            title=title,
                            url=full_url,
                            source=self.SITE_NAME,
                            genres=[genre.replace('-', ' ').title()]
                        )
                        all_series.append(series)
                        logger.debug(f"Found: {title}")
                        
                        # Check limit
                        if self.limit and len(all_series) >= self.limit:
                            break
                
                logger.info(f"Found {len([s for s in all_series if genre.replace('-', ' ').title() in s.genres])} series in {genre}")
                
                # Check limit after genre
                if self.limit and len(all_series) >= self.limit:
                    logger.info(f"Reached limit of {self.limit} series")
                    break
                    
            except Exception as e:
                logger.error(f"Error fetching genre {genre}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                continue
            
            # Check limit in outer loop
            if self.limit and len(all_series) >= self.limit:
                break
        
        logger.info(f"Total ORIGINALS series found: {len(all_series)}")
        return all_series
    
    def _get_canvas_series(self) -> List[Series]:
        """Get CANVAS series (user-created content)"""
        logger.info("Fetching CANVAS series from Webtoons...")
        
        all_series = []
        seen_urls = set()
        
        # CANVAS genres
        canvas_genres = ['romance', 'comedy', 'drama', 'slice-of-life', 'fantasy', 
                        'supernatural', 'heartwarming', 'sci-fi', 'horror', 
                        'thriller', 'action', 'others']
        
        for genre in canvas_genres:
            logger.info(f"Fetching CANVAS genre: {genre}")
            page = 1
            
            while page <= 5:  # Limit pages per genre
                url = f"{self.BASE_URL}/en/canvas/genre?genre={genre}&page={page}"
                
                try:
                    soup = self._get_soup(url, use_selenium=True)
                    
                    cards = soup.select('a.challenge_item, ul.challenge_lst li a')
                    if not cards:
                        break
                    
                    found_new = False
                    for card in cards:
                        href = card.get('href', '')
                        if not href or href in seen_urls:
                            continue
                        
                        title_elem = card.select_one('.subj, .info .subj')
                        if not title_elem:
                            continue
                        
                        title = title_elem.get_text(strip=True)
                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        
                        if full_url not in seen_urls:
                            seen_urls.add(full_url)
                            series = Series(
                                title=title,
                                url=full_url,
                                source='webtoon-canvas',
                                genres=[genre.replace('-', ' ').title()]
                            )
                            all_series.append(series)
                            found_new = True
                            
                            # Check limit
                            if self.limit and len(all_series) >= self.limit:
                                logger.info(f"Reached limit of {self.limit} series")
                                break
                    
                    # Check limit after page
                    if self.limit and len(all_series) >= self.limit:
                        break
                    
                    if not found_new:
                        break
                    page += 1
                    
                except Exception as e:
                    logger.error(f"Error on CANVAS page: {e}")
                    break
            
            # Check limit in outer loop
            if self.limit and len(all_series) >= self.limit:
                break
        
        logger.info(f"Total CANVAS series found: {len(all_series)}")
        return all_series
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        """Get all FREE chapters for a series"""
        chapters = []
        page = 1
        
        # Extract title_no from URL
        title_no_match = re.search(r'title_no=(\d+)', series.url)
        if not title_no_match:
            logger.error(f"Could not extract title_no from URL: {series.url}")
            return chapters
        
        title_no = title_no_match.group(1)
        
        # Build base URL properly - remove /list if present to avoid duplication
        base_url = re.sub(r'/list\?.*$', '', series.url)  # Remove /list?... 
        base_url = re.sub(r'\?.*$', '', base_url)  # Remove any remaining query params
        
        while True:
            # Webtoon chapter list URL
            list_url = f"{base_url}/list?title_no={title_no}&page={page}"
            
            try:
                soup = self._get_soup(list_url, use_selenium=False)
                
                # Find episode list
                episode_items = soup.select('#_listUl li a, ul#_listUl li a')
                
                if not episode_items:
                    break
                
                found_new = False
                for item in episode_items:
                    href = item.get('href', '')
                    
                    # Skip locked/paid episodes
                    if item.select_one('.ico_lock, .locked'):
                        continue
                    
                    # Get episode number and title
                    num_elem = item.select_one('.tx, .subj .num, .episode_num')
                    title_elem = item.select_one('.subj span, .sub_title')
                    
                    ep_num = ""
                    if num_elem:
                        ep_text = num_elem.get_text(strip=True)
                        match = re.search(r'#?(\d+)', ep_text)
                        ep_num = match.group(1) if match else ep_text
                    
                    ep_title = title_elem.get_text(strip=True) if title_elem else f"Episode {ep_num}"
                    
                    if href and ep_num:
                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        
                        # Check if we already have this chapter
                        if not any(c.url == full_url for c in chapters):
                            chapters.append(Chapter(
                                number=ep_num,
                                title=ep_title,
                                url=full_url
                            ))
                            found_new = True
                
                if not found_new:
                    break
                    
                page += 1
                
                # Safety limit
                if page > 200:
                    break
                    
            except Exception as e:
                logger.error(f"Error fetching chapter list page {page}: {e}")
                break
        
        # Sort by episode number
        chapters.sort(key=lambda x: int(x.number) if x.number.isdigit() else 0)
        
        logger.info(f"Found {len(chapters)} free chapters for {series.title}")
        return chapters
    
    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter"""
        try:
            soup = self._get_soup(chapter.url, use_selenium=True)
            
            pages = []
            
            # Webtoon stores images in the reader container
            for img in soup.select('#_imageList img, .viewer_img img, #content img._images'):
                src = img.get('data-url') or img.get('data-src') or img.get('src', '')
                
                if src and 'webtoon' in src.lower() and 'blank' not in src.lower():
                    # Clean up URL
                    src = src.split('?')[0] if '?' in src else src
                    if src not in pages:
                        pages.append(src)
            
            return pages
            
        except Exception as e:
            logger.error(f"Error getting pages for {chapter.url}: {e}")
            return []
    
    def _download_image(self, url: str, path: Path, referer: str) -> bool:
        """Download image with Webtoon-specific headers"""
        try:
            headers = {
                'Referer': referer,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            if len(response.content) < 1000:
                return False
            
            path.write_bytes(response.content)
            return True
        except Exception as e:
            logger.debug(f"Failed to download {url}: {e}")
            return False


class ManhuaToScraper(BaseSiteScraper):
    """Full site scraper for manhuato.com"""

    BASE_URL = "https://manhuato.com"
    SITE_NAME = "manhuato"
    CLOUDFLARE_SITE = True

    # Available genres
    GENRES = [
        'action', 'adventure', 'comedy', 'drama', 'fantasy', 'historical',
        'horror', 'martial-arts', 'mature', 'mystery', 'romance', 'sci-fi',
        'shoujo', 'shounen', 'slice-of-life', 'supernatural', 'tragedy'
    ]

    # Content types
    TYPES = ['manhwa', 'manhua', 'manga', 'comics']

    def _get_soup_fs(self, url: str) -> BeautifulSoup:
        """Fetch a page using FlareSolverr or cached session cookies"""
        if not self._fs_cookies_applied:
            # First request: use FlareSolverr to solve any challenges
            html, cookies, user_agent = self._flaresolverr_get(url)
            self._apply_flaresolverr_cookies(cookies, user_agent)
            self._fs_cookies_applied = True
            return BeautifulSoup(html, 'html.parser')
        else:
            # Subsequent requests: try session with cookies first, fall back to FlareSolverr
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                if len(resp.text) > 500:
                    return BeautifulSoup(resp.text, 'html.parser')
            except Exception:
                pass
            html, cookies, user_agent = self._flaresolverr_get(url)
            self._apply_flaresolverr_cookies(cookies, user_agent)
            return BeautifulSoup(html, 'html.parser')

    def get_all_series(self, content_type: str = None, genre_filter: List[str] = None) -> List[Series]:
        """Get all series from ManhuaTo.

        If genre_filter is provided (e.g. ['action', 'fantasy']), browse
        the /genre/{genre} pages instead of /type/ pages.  This is MUCH
        more comprehensive — /genre/action alone has 55+ pages.
        """
        all_series = []
        seen_urls = set()

        # Determine what to browse: genres or types
        if genre_filter:
            # Map filter terms to ManhuaTo genre slugs
            genre_slugs = []
            for term in genre_filter:
                slug = term.lower().replace(' ', '-')
                if slug in [g.lower() for g in self.GENRES]:
                    genre_slugs.append(slug)
            if genre_slugs:
                logger.info(f"Browsing ManhuaTo by genres: {genre_slugs}")
                return self._browse_pages(genre_slugs, 'genre', seen_urls)
            # If no valid genres matched, fall through to type browsing

        logger.info("Fetching all series from ManhuaTo by type...")
        types_to_scrape = [content_type] if content_type else self.TYPES
        return self._browse_pages(types_to_scrape, 'type', seen_urls)

    def _browse_pages(self, categories: List[str], browse_type: str,
                      seen_urls: set) -> List[Series]:
        """Browse ManhuaTo pages by type or genre.

        browse_type: 'type' for /type/{cat} or 'genre' for /genre/{cat}
        """
        all_series = []

        for category in categories:
            logger.info(f"Fetching {browse_type}: {category}")
            page = 1
            consecutive_failures = 0

            # Initialize driver for this category
            self._close_driver()

            while True:
                if page > 1:
                    url = f"{self.BASE_URL}/{browse_type}/{category}?page={page}"
                else:
                    url = f"{self.BASE_URL}/{browse_type}/{category}"
                logger.info(f"Fetching page {page} for {category}...")
                
                try:
                    if self._use_flaresolverr:
                        soup = self._get_soup_fs(url)
                    else:
                        # Initialize driver if needed
                        self._init_driver()

                        self.driver.get(url)
                        time.sleep(3)  # Wait for page to load

                        # Wait for content to appear
                        try:
                            WebDriverWait(self.driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, 'div.visual, div.manga-cover, div.list_wrap'))
                            )
                            time.sleep(1)
                        except:
                            pass

                        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                    
                    # Find series containers - they're in div.visual
                    visual_items = soup.select('div.visual')
                    logger.debug(f"Found {len(visual_items)} visual containers")
                    
                    if not visual_items:
                        logger.info(f"No more series found on page {page}")
                        consecutive_failures += 1
                        if consecutive_failures >= 2:
                            break
                        page += 1
                        continue
                    
                    consecutive_failures = 0
                    found_count = 0
                    
                    for item in visual_items:
                        try:
                            # Get the correct URL from manga-cover link
                            cover_link = item.select_one('div.manga-cover a, a[href*="/manhua/"], a[href*="/manhwa/"], a[href*="/manga/"]')
                            if not cover_link:
                                continue
                            
                            href = cover_link.get('href', '').strip()
                            if not href or href in seen_urls:
                                continue
                            
                            # Skip chapter links
                            if '-chapter-' in href:
                                continue
                            
                            # Get title from img alt or h3.title text
                            title = None
                            img = item.select_one('img')
                            if img:
                                title = img.get('alt', '')
                            
                            if not title:
                                title_elem = item.select_one('h3.title a, h3.title, h3 a')
                                if title_elem:
                                    title = title_elem.get_text(strip=True)
                            
                            if not title or len(title) < 2:
                                continue
                            
                            full_url = href if href.startswith('http') else self.BASE_URL + href
                            
                            if full_url not in seen_urls:
                                seen_urls.add(full_url)
                                series = Series(
                                    title=title,
                                    url=full_url,
                                    source=self.SITE_NAME,
                                    genres=[category.title()]
                                )
                                all_series.append(series)
                                found_count += 1
                                logger.debug(f"Found: {title}")
                                
                                # Check limit
                                if self.limit and len(all_series) >= self.limit:
                                    logger.info(f"Reached limit of {self.limit} series")
                                    break
                        except Exception as e:
                            logger.debug(f"Error parsing item: {e}")
                            continue
                    
                    # Check limit after processing page
                    if self.limit and len(all_series) >= self.limit:
                        break
                    
                    logger.info(f"Found {found_count} series on page {page}")
                    
                    if found_count == 0:
                        break
                    
                    page += 1
                    
                    # Safety limit per type
                    if page > 200:
                        logger.warning(f"Reached page limit for {category}")
                        break
                    
                    time.sleep(0.5)  # Be nice to server
                        
                except Exception as e:
                    logger.error(f"Error on page {page}: {e}")
                    # Reinitialize driver on error
                    self._close_driver()
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        logger.error(f"Too many failures for {category}, moving to next")
                        break
                    continue
            
            # Close driver between content types
            self._close_driver()
        
        logger.info(f"Total series found: {len(all_series)}")
        return all_series
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        """Get all chapters for a series"""
        try:
            soup = self._get_soup(series.url, use_selenium=False)
            
            chapters = []
            
            # Find chapter links
            for link in soup.select('a[href*="-chapter-"]'):
                href = link.get('href', '').strip()
                text = link.get_text(strip=True)
                
                if not href:
                    continue
                
                # Extract chapter number
                match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', text, re.I)
                if not match:
                    match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href, re.I)
                
                num = match.group(1) if match else text
                
                # Build full URL properly
                if href.startswith('http'):
                    full_url = href
                elif href.startswith('/'):
                    full_url = self.BASE_URL + href
                else:
                    full_url = self.BASE_URL + '/' + href
                
                # Avoid duplicates
                if not any(c.url == full_url for c in chapters):
                    chapters.append(Chapter(
                        number=num,
                        title=text,
                        url=full_url
                    ))
            
            # Sort by chapter number (oldest first)
            chapters.sort(key=lambda x: float(x.number) if x.number.replace('.', '').isdigit() else 0)
            
            return chapters
            
        except Exception as e:
            logger.error(f"Error getting chapters: {e}")
            return []
    
    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter with ad blocking and URL enumeration"""
        try:
            chapter_url = chapter.url.strip()
            logger.info(f"Loading chapter page: {chapter_url}")

            if self._use_flaresolverr:
                # FlareSolverr mode: fetch HTML without needing a browser
                soup = self._get_soup_fs(chapter_url)
            else:
                # Selenium mode: use browser with ad blocking
                self._init_driver()

                # Load saved cookies if available
                try:
                    import pickle
                    with open("manhuato_cookies.pkl", 'rb') as f:
                        cookies = pickle.load(f)
                    self.driver.get("https://manhuato.com")
                    time.sleep(1)
                    for c in cookies:
                        try:
                            self.driver.add_cookie(c)
                        except:
                            pass
                    logger.info(f"Loaded {len(cookies)} saved cookies")
                except:
                    pass

                # Try to load the page with MANY retries (ads cause redirects)
                max_retries = 15
                success = False
                for attempt in range(max_retries):
                    try:
                        self.driver.get(chapter_url)
                        time.sleep(2)

                        current = self.driver.current_url.lower()
                        if 'manhuato.com' in current:
                            logger.info(f"Successfully loaded chapter page (attempt {attempt + 1})")
                            success = True
                            break
                        else:
                            logger.warning(f"Redirected to {current[:50]}..., retrying...")
                            time.sleep(1)
                    except Exception as e:
                        logger.warning(f"Navigation attempt {attempt + 1} failed: {e}")
                        time.sleep(1)

                if not success:
                    logger.error("Could not load chapter page after all retries")
                    return []

                # Remove ad overlays
                try:
                    self.driver.execute_script("""
                        document.querySelectorAll('[onclick]').forEach(el => el.removeAttribute('onclick'));
                        document.querySelectorAll('div, section').forEach(el => {
                            var style = window.getComputedStyle(el);
                            if ((style.position === 'fixed' || style.position === 'absolute') &&
                                parseInt(style.zIndex) > 100 && !el.querySelector('img[src*="cdn"]')) {
                                el.remove();
                            }
                        });
                    """)
                except:
                    pass

                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            pages = []
            
            # Find images - ONLY from cdn.manhuato.com (strict filter!)
            for img in soup.select('img'):
                src = img.get('data-original') or img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
                
                if not src or src.startswith('data:') or len(src) < 10:
                    continue
                
                src = src.strip()
                
                # Ensure full URL
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = self.BASE_URL.rstrip('/') + src
                
                # ONLY accept images from cdn.manhuato.com - this prevents grabbing ad images
                if 'cdn.manhuato.com' not in src.lower():
                    continue
                
                if src not in pages:
                    pages.append(src)
            
            logger.info(f"Found {len(pages)} images from page HTML")
            
            # Enumerate more images based on URL pattern
            if pages:
                import re
                import requests as req
                
                base_url = None
                extension = None
                max_found = -1
                
                for img_url in pages:
                    match = re.search(r'(.+/)(\d+)(\.[a-z]+)$', img_url, re.I)
                    if match:
                        base_url = match.group(1)
                        num = int(match.group(2))
                        extension = match.group(3)
                        if num > max_found:
                            max_found = num
                
                if base_url and extension and 'cdn.manhuato' in base_url.lower():
                    logger.info(f"Enumerating images from pattern: {base_url}[N]{extension}")
                    
                    session = req.Session()
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': chapter_url,
                    })
                    
                    # Find all images by enumeration
                    consecutive_failures = 0
                    current_num = 0
                    
                    while consecutive_failures < 5 and current_num < 300:
                        test_url = f"{base_url}{current_num}{extension}"
                        
                        if test_url not in pages:
                            try:
                                resp = session.get(test_url, timeout=10, stream=True)
                                ct = resp.headers.get('Content-Type', '')
                                if resp.status_code == 200 and 'image' in ct:
                                    pages.append(test_url)
                                    consecutive_failures = 0
                                else:
                                    consecutive_failures += 1
                                resp.close()
                            except:
                                consecutive_failures += 1
                        else:
                            consecutive_failures = 0
                        
                        current_num += 1
                    
                    # Sort by number
                    def get_num(url):
                        m = re.search(r'/(\d+)\.[a-z]+$', url, re.I)
                        return int(m.group(1)) if m else 0
                    
                    pages.sort(key=get_num)
            
            logger.info(f"Found {len(pages)} page images total")
            return pages
            
        except Exception as e:
            logger.error(f"Error getting pages: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []

class DrakeFullScraper(BaseSiteScraper):
    """Full site scraper for drakecomic.org"""

    BASE_URL = "https://drakecomic.org"
    SITE_NAME = "drake"
    CLOUDFLARE_SITE = True

    def __init__(self, headless: bool = True, limit: int = None):
        super().__init__(headless=headless, limit=limit)
        if not self._is_arm() and not self._use_flaresolverr:
            # On x86, force non-headless for UC Cloudflare bypass
            if headless:
                logger.info("Drake Comics requires non-headless mode (Cloudflare protection). Overriding to visible browser.")
            self.headless = False

    def _init_driver(self):
        """Override to use minimal options for Cloudflare bypass"""
        # If using FlareSolverr, we don't need a browser driver at all for page fetching
        # But we may still need one for JS-heavy chapter page rendering
        if self._use_flaresolverr and not self.driver:
            # Only init regular selenium if explicitly needed (e.g. get_pages)
            return

        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium not available")
        if self.driver:
            return

        if UC_AVAILABLE:
            logger.info("Using undetected-chromedriver (Drake/Cloudflare mode)")
            options = uc.ChromeOptions()
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
                logger.warning(f"undetected-chromedriver failed: {e}")

        # Fallback
        super()._init_driver()

    def _wait_for_cloudflare(self, timeout: int = 30):
        """Wait for Cloudflare JS challenge to resolve"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                title = self.driver.title.lower()
                if 'just a moment' not in title and 'cloudflare' not in title and 'checking' not in title:
                    logger.debug(f"Cloudflare resolved after {time.time() - start:.1f}s")
                    return True
            except Exception:
                pass
            time.sleep(2)
        logger.warning("Cloudflare challenge did not resolve within timeout - site may require manual verification")
        return False

    def _get_soup(self, url: str, use_selenium: bool = False) -> BeautifulSoup:
        """Override to handle Cloudflare wait on non-FlareSolverr path"""
        if self._use_flaresolverr:
            return super()._get_soup(url, use_selenium=True)

        # Non-ARM path: use Selenium with UC + Cloudflare wait
        self._delay()
        self._init_driver()
        self.driver.get(url)
        self._wait_for_cloudflare()
        time.sleep(2)
        html = self.driver.page_source
        return BeautifulSoup(html, 'html.parser')

    def get_all_series(self) -> List[Series]:
        """Get all series from Drake Comics"""
        logger.info("Fetching all series from Drake Comics...")

        all_series = []
        page = 1

        while True:
            url = f"{self.BASE_URL}/manga/?page={page}" if page > 1 else f"{self.BASE_URL}/manga/"
            logger.info(f"Fetching page {page}...")

            try:
                soup = self._get_soup(url)
                
                # Find series containers - div.bs contains each series
                items = soup.select('div.bs')
                
                if not items:
                    # Fallback to links
                    items = soup.select('div.bsx a[href*="/manga/"]')
                
                if not items:
                    logger.info(f"No more series found on page {page}")
                    break
                
                found_count = 0
                for item in items:
                    try:
                        # Get the main link
                        link = item.select_one('a[href*="/manga/"]') if item.name != 'a' else item
                        if not link:
                            continue
                        
                        href = link.get('href', '').strip()
                        if not href or '/manga/' not in href:
                            continue
                        
                        # Get title from title attribute or div.tt
                        title = link.get('title', '')
                        if not title:
                            title_elem = item.select_one('div.tt, .title')
                            if title_elem:
                                title = title_elem.get_text(strip=True)
                        
                        if not title or len(title) < 2:
                            continue
                        
                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        
                        # Get type/genre
                        genres = []
                        type_elem = item.select_one('span.type')
                        if type_elem:
                            genres.append(type_elem.get_text(strip=True))
                        
                        # Get rating
                        rating = 0.0
                        rating_elem = item.select_one('div.rating')
                        if rating_elem:
                            rating_text = rating_elem.get_text(strip=True)
                            match = re.search(r'(\d+\.?\d*)', rating_text)
                            if match:
                                rating = float(match.group(1))
                                if rating > 5:
                                    rating = rating / 2
                        
                        # Avoid duplicates
                        if not any(s.url == full_url for s in all_series):
                            series = Series(
                                title=title,
                                url=full_url,
                                source=self.SITE_NAME,
                                genres=genres,
                                rating=round(rating, 2)
                            )
                            all_series.append(series)
                            found_count += 1
                            logger.debug(f"Found: {title}")
                            
                            # Check limit
                            if self.limit and len(all_series) >= self.limit:
                                logger.info(f"Reached limit of {self.limit} series")
                                break
                    except Exception as e:
                        logger.debug(f"Error parsing item: {e}")
                        continue
                
                # Check limit after page
                if self.limit and len(all_series) >= self.limit:
                    break
                
                logger.info(f"Found {found_count} series on page {page}")
                
                if found_count == 0:
                    break
                    
                page += 1
                if page > 200:
                    logger.warning("Reached page limit (200)")
                    break
                
                time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                break
        
        logger.info(f"Total series found: {len(all_series)}")
        return all_series
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        soup = self._get_soup(series.url, use_selenium=True)
        
        chapters = []
        for link in soup.select('#chapterlist li a, .eplister li a, a[href*="chapter"]'):
            href = link.get('href', '').strip()
            if not href:
                continue
            
            num_elem = link.select_one('.chapternum, .epl-num, .epxs')
            text = num_elem.get_text(strip=True) if num_elem else link.get_text(strip=True)
            
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href, re.I)
            if not match:
                match = re.search(r'(\d+(?:\.\d+)?)', text)
            num = match.group(1) if match else text
            
            full_url = href if href.startswith('http') else self.BASE_URL + href
            
            # Avoid duplicates
            if not any(c.url == full_url for c in chapters):
                chapters.append(Chapter(
                    number=num,
                    title=text or f"Chapter {num}",
                    url=full_url
                ))
        
        chapters.reverse()
        return chapters
    
    def _sync_cookies_from_driver(self):
        """Transfer Cloudflare cookies and UA from selenium to requests session"""
        # In FlareSolverr mode, cookies are already on the session
        if self._use_flaresolverr:
            return
        if self.driver:
            for cookie in self.driver.get_cookies():
                self.session.cookies.set(cookie['name'], cookie['value'],
                                        domain=cookie.get('domain', ''))
            # Match the browser's User-Agent exactly (Cloudflare validates this)
            try:
                ua = self.driver.execute_script('return navigator.userAgent')
                self.session.headers['User-Agent'] = ua
            except Exception:
                pass
            logger.debug("Synced cookies and UA from browser to requests session")

    def get_pages(self, chapter: Chapter) -> List[str]:
        # _get_soup handles FlareSolverr vs Selenium internally
        soup = self._get_soup(chapter.url, use_selenium=True)

        # Sync Cloudflare cookies so image downloads work
        self._sync_cookies_from_driver()

        pages = []
        for img in soup.select('#readerarea img, .chapter-content img, img.ts-main-image'):
            src = img.get('data-src') or img.get('src', '')
            src = src.strip()
            if src and 'logo' not in src.lower() and 'icon' not in src.lower():
                if src not in pages:
                    pages.append(src)

        return pages

    def _download_image(self, url: str, path: Path, referer: str) -> bool:
        """Download image using session with synced Cloudflare cookies and matching UA"""
        try:
            headers = {
                'Referer': referer,
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            }
            # Don't override User-Agent - use the one synced from the browser
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            if len(response.content) < 1000:
                return False

            path.write_bytes(response.content)
            return True
        except Exception as e:
            logger.debug(f"Failed to download {url}: {e}")
            return False


# Site registry
SCRAPERS = {
    'asura': AsuraFullScraper,
    'asuracomic': AsuraFullScraper,
    'asuracomic.net': AsuraFullScraper,
    'flame': FlameFullScraper,
    'flamecomics': FlameFullScraper,
    'flamecomics.xyz': FlameFullScraper,
    'drake': DrakeFullScraper,
    'drakecomic': DrakeFullScraper,
    'drakecomic.org': DrakeFullScraper,
    'manhuato': ManhuaToScraper,
    'manhuato.com': ManhuaToScraper,
    'webtoon': WebtoonScraper,
    'webtoons': WebtoonScraper,
    'webtoons.com': WebtoonScraper,
}

# Primary sites (canonical names only, no aliases) - used for --site all
# Note: Drake is excluded due to captcha protection
PRIMARY_SITES = {
    'asura': AsuraFullScraper,
    'flame': FlameFullScraper,
    'manhuato': ManhuaToScraper,
    'webtoon': WebtoonScraper,
}


def get_scraper(site: str, headless: bool = True, canvas: bool = False, limit: int = None) -> BaseSiteScraper:
    """Get scraper instance by site name"""
    site_lower = site.lower()
    
    for key, scraper_class in SCRAPERS.items():
        if key in site_lower:
            # Special handling for Webtoon canvas option
            if scraper_class == WebtoonScraper:
                return scraper_class(headless=headless, canvas=canvas, limit=limit)
            return scraper_class(headless=headless, limit=limit)
    
    raise ValueError(f"Unknown site: {site}. Available: {list(SCRAPERS.keys())}")


def get_all_scrapers(headless: bool = True, limit: int = None) -> Dict[str, BaseSiteScraper]:
    """Get all primary scrapers for --site all mode"""
    scrapers = {}
    for name, scraper_class in PRIMARY_SITES.items():
        scrapers[name] = scraper_class(headless=headless, limit=limit)
    return scrapers


def export_series_list(series_list: List[Series], output_file: Path):
    """Export series list to YAML file"""
    
    # Deduplicate by URL first
    seen_urls = set()
    unique_series = []
    for s in series_list:
        # Normalize URL for comparison
        normalized_url = s.url.rstrip('/').split('?')[0]
        if normalized_url not in seen_urls:
            seen_urls.add(normalized_url)
            unique_series.append(s)
    
    if len(unique_series) < len(series_list):
        logger.info(f"Removed {len(series_list) - len(unique_series)} duplicate entries")
    
    series_list = unique_series
    
    # Calculate stats
    total_chapters = sum(s.chapters_count for s in series_list)
    series_with_counts = [s for s in series_list if s.chapters_count > 0]
    series_with_ratings = [s for s in series_list if s.rating > 0]
    avg_rating = sum(s.rating for s in series_with_ratings) / len(series_with_ratings) if series_with_ratings else 0
    
    # Status breakdown
    status_counts = {}
    for s in series_list:
        status = s.status or 'Unknown'
        status_counts[status] = status_counts.get(status, 0) + 1
    
    data = {
        'generated': datetime.now().isoformat(),
        'total_series': len(series_list),
        'total_chapters': total_chapters,
        'series_with_chapter_info': len(series_with_counts),
        'series_with_ratings': len(series_with_ratings),
        'average_rating': round(avg_rating, 2),
        'status_breakdown': status_counts,
        'series': []
    }
    
    # Sort by rating first, then chapter count
    sorted_series = sorted(series_list, key=lambda s: (s.rating, s.chapters_count), reverse=True)
    
    for s in sorted_series:
        entry = {
            'title': s.title,
            'url': s.url,
            'source': s.source,
            'status': s.status or 'Unknown',
            'rating': s.rating,
            'chapters': s.chapters_count,
            'genres': s.genres,
            'author': s.author,
            'artist': s.artist,
            'description': s.description[:500] if s.description else '',  # Truncate for readability
            'enabled': True  # User can set to False to skip
        }
        data['series'].append(entry)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    logger.info(f"Exported {len(series_list)} series ({total_chapters} total chapters, {len(series_with_ratings)} with ratings) to {output_file}")


def load_series_list(config_file: Path) -> List[Series]:
    """Load series list from YAML file"""
    with open(config_file, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    series_list = []
    for item in data.get('series', []):
        if item.get('enabled', True):
            series_list.append(Series(
                title=item['title'],
                url=item['url'],
                source=item.get('source', 'unknown'),
                genres=item.get('genres', []),
                status=item.get('status', ''),
                chapters_count=item.get('chapters', 0),
                rating=item.get('rating', 0.0),
                description=item.get('description', ''),
                author=item.get('author', ''),
                artist=item.get('artist', '')
            ))
    
    return series_list


def filter_series(series_list: List[Series], filter_terms: List[str]) -> List[Series]:
    """Filter series by genre, title, or status keywords (OR logic - matches ANY term)"""
    if not filter_terms:
        return series_list
    
    filtered = []
    for s in series_list:
        # Check title, genres, and status
        searchable = s.title.lower() + ' ' + ' '.join(s.genres).lower() + ' ' + (s.status or '').lower()
        if any(term.lower() in searchable for term in filter_terms):
            filtered.append(s)
    
    return filtered


def filter_series_all(series_list: List[Series], filter_terms: List[str]) -> List[Series]:
    """Filter series by genre, title, or status keywords (AND logic - must match ALL terms)"""
    if not filter_terms:
        return series_list
    
    filtered = []
    for s in series_list:
        # Check title, genres, and status
        searchable = s.title.lower() + ' ' + ' '.join(s.genres).lower() + ' ' + (s.status or '').lower()
        if all(term.lower() in searchable for term in filter_terms):
            filtered.append(s)
    
    return filtered


def apply_keyword_filters(series_list: List[Series], filter_or: str, filter_and: str, status_filter: str = None) -> List[Series]:
    """Apply OR, AND, and status filters"""
    result = series_list
    
    # Apply OR filter (--filter)
    if filter_or:
        filter_terms = [t.strip() for t in filter_or.split(',')]
        result = filter_series(result, filter_terms)
    
    # Apply AND filter (--filter-all)
    if filter_and:
        filter_terms = [t.strip() for t in filter_and.split(',')]
        result = filter_series_all(result, filter_terms)
    
    # Apply status filter (--status)
    if status_filter:
        statuses = [s.strip() for s in status_filter.split(',')]
        result = filter_by_status(result, statuses)
    
    return result


def filter_by_chapter_count(series_list: List[Series], min_chapters: int = 0, max_chapters: int = None) -> List[Series]:
    """Filter series by chapter count"""
    filtered = []
    for s in series_list:
        if s.chapters_count >= min_chapters:
            if max_chapters is None or s.chapters_count <= max_chapters:
                filtered.append(s)
    return filtered


def filter_by_status(series_list: List[Series], statuses: List[str]) -> List[Series]:
    """Filter series by status (Ongoing, Completed, Hiatus, etc.)"""
    if not statuses:
        return series_list
    
    # Normalize status names for comparison
    normalized_statuses = [s.lower().strip() for s in statuses]
    
    filtered = []
    for s in series_list:
        series_status = (s.status or '').lower().strip()
        if series_status in normalized_statuses:
            filtered.append(s)
        # Also check partial matches (e.g., "complete" matches "completed")
        elif any(ns in series_status or series_status in ns for ns in normalized_statuses if series_status):
            filtered.append(s)
    
    return filtered


def filter_by_rating(series_list: List[Series], min_rating: float) -> List[Series]:
    """Filter series by minimum rating"""
    if min_rating <= 0:
        return series_list
    
    filtered = []
    for s in series_list:
        if s.rating >= min_rating:
            filtered.append(s)
    
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description='Scrape entire manhwa sites or specific series',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all series from Asura Scans
  python manhwa_scraper.py --site asura --list-all -o asura_series.yaml
  
  # List all series WITH chapter counts (slower but more info)
  python manhwa_scraper.py --site asura --list-all --with-chapters -o asura_series.yaml
  
  # List only series with 50+ chapters
  python manhwa_scraper.py --site asura --list-all --min-chapters 50 -o popular_series.yaml
  
  # List series with 20-100 chapters (avoid very short or very long)
  python manhwa_scraper.py --site asura --list-all --min-chapters 20 --max-chapters 100 -o mid_series.yaml
  
  # Download ALL series (warning: lots of data!)
  python manhwa_scraper.py --site asura --download-all -o ./library/Manhwa
  
  # Download only series with 100+ chapters (established series)
  python manhwa_scraper.py --site asura --download-all --min-chapters 100 -o ./library/Manhwa
  
  # Download only cultivation/martial arts manhwa (OR - matches either)
  python manhwa_scraper.py --site asura --download-all --filter "cultivation,martial" -o ./library
  
  # Series that are BOTH action AND fantasy (AND logic)
  python manhwa_scraper.py --site asura --list-all --filter-all "action,fantasy" -o action_fantasy.yaml
  
  # Combine OR and AND: must be fantasy, can be action or adventure
  python manhwa_scraper.py --site asura --list-all --filter "action,adventure" --filter-all "fantasy" -o filtered.yaml
  
  # Combine filters: action manhwa with 50+ chapters
  python manhwa_scraper.py --site asura --download-all --filter "action" --min-chapters 50 -o ./library
  
  # ============================================
  # STATUS FILTERING
  # ============================================
  
  # List only completed series
  python manhwa_scraper.py --site asura --list-all --status completed -o completed.yaml
  
  # List only ongoing series
  python manhwa_scraper.py --site asura --list-all --status ongoing -o ongoing.yaml
  
  # Completed fantasy series with 50+ chapters
  python manhwa_scraper.py --site asura --list-all --filter-all "fantasy" --status completed --min-chapters 50 -o done_fantasy.yaml
  
  # Download completed action series
  python manhwa_scraper.py --site asura --download-all --filter "action" --status completed -o ./library
  
  # Multiple statuses: completed or hiatus
  python manhwa_scraper.py --site asura --list-all --status "completed,hiatus" -o finished.yaml
  
  # ============================================
  # RATING FILTERING
  # ============================================
  
  # List only highly-rated series (4.0+ out of 5)
  python manhwa_scraper.py --site asura --list-all --min-rating 4.0 -o highly_rated.yaml
  
  # Completed series with 4.5+ rating and 100+ chapters (quality binge!)
  python manhwa_scraper.py --site asura --list-all --status completed --min-rating 4.5 --min-chapters 100 -o best_completed.yaml
  
  # Download only top-rated fantasy series
  python manhwa_scraper.py --site asura --download-all --filter "fantasy" --min-rating 4.0 -o ./library
  
  # ============================================
  # SCRAPE ALL SITES AT ONCE
  # ============================================
  
  # List series from ALL sites (asura, flame, drake, manhuato, webtoon)
  python manhwa_scraper.py --site all --list-all -o all_series.yaml
  
  # List series with 50+ chapters from ALL sites
  python manhwa_scraper.py --site all --list-all --min-chapters 50 -o popular_all.yaml
  
  # Download from ALL sites (auto-adds [Source] prefix to folders)
  python manhwa_scraper.py --site all --download-all -o ./library
  
  # Download action series with 100+ chapters from ALL sites
  python manhwa_scraper.py --site all --download-all --filter "action" --min-chapters 100 -o ./library
  
  # ============================================
  
  # List all Webtoon ORIGINALS
  python manhwa_scraper.py --site webtoon --list-all -o webtoon_originals.yaml
  
  # List Webtoon CANVAS (user-created) series
  python manhwa_scraper.py --site webtoon --canvas --list-all -o webtoon_canvas.yaml
  
  # Download Webtoon fantasy series
  python manhwa_scraper.py --site webtoon --download-all --filter "fantasy,action" -o ./library
  
  # Download from ManhuaTo
  python manhwa_scraper.py --site manhuato --list-all -o manhuato_series.yaml
  python manhwa_scraper.py --site manhuato --download-all --filter "romance" -o ./library
  
  # Compare same series from multiple sources (uses [Source] prefix)
  python manhwa_scraper.py --site asura --download-all --filter "solo leveling" --source-prefix -o ./library
  python manhwa_scraper.py --site webtoon --download-all --filter "solo leveling" --source-prefix -o ./library
  
  # Download from a curated YAML list
  python manhwa_scraper.py --config my_series.yaml -o ./library/Manhwa
        """
    )
    
    parser.add_argument('--site', '-s', help='Site to scrape (asura, flame, drake, manhuato, webtoon, or "all" for all sites)')
    parser.add_argument('--list-all', action='store_true', help='List all series and export to YAML')
    parser.add_argument('--download-all', action='store_true', help='Download all series from site')
    parser.add_argument('--download-url', help='Download a specific series by URL')
    parser.add_argument('--chapters', help='Chapter range to download (e.g., "1", "1-10", "latest", default: all)')
    parser.add_argument('--config', '-c', help='YAML config file with series list')
    parser.add_argument('--output', '-o', required=True, help='Output directory or YAML file')
    parser.add_argument('--filter', '-f', help='Comma-separated filter terms - OR logic (matches ANY term)')
    parser.add_argument('--filter-all', help='Comma-separated filter terms - AND logic (must match ALL terms)')
    parser.add_argument('--min-chapters', type=int, default=0, help='Minimum chapter count to include (default: 0)')
    parser.add_argument('--max-chapters', type=int, help='Maximum chapter count to include')
    parser.add_argument('--min-rating', type=float, default=0.0, help='Minimum rating to include (0.0-5.0)')
    parser.add_argument('--status', help='Filter by status: ongoing, completed, hiatus (comma-separated)')
    parser.add_argument('--with-chapters', action='store_true', help='Fetch chapter counts, status, and rating (slower but enables filtering)')
    parser.add_argument('--visible', action='store_true', help='Show browser window')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--limit', type=int, help='Limit number of series to process')
    parser.add_argument('--canvas', action='store_true', help='For Webtoon: scrape CANVAS instead of ORIGINALS')
    parser.add_argument('--source-prefix', action='store_true', help='Prefix series folders with [Source] for multi-source comparison')
    
    args = parser.parse_args()
    
    # Set logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    headless = not args.visible
    output_path = Path(args.output)
    
    # Mode 0: Download a specific series by URL
    if args.download_url:
        if not args.site:
            # Try to auto-detect site from URL
            url_lower = args.download_url.lower()
            if 'asura' in url_lower:
                args.site = 'asura'
            elif 'flame' in url_lower:
                args.site = 'flame'
            elif 'manhuato' in url_lower:
                args.site = 'manhuato'
            elif 'webtoon' in url_lower:
                args.site = 'webtoon'
            elif 'drake' in url_lower:
                args.site = 'drake'
            else:
                logger.error("Could not auto-detect site from URL. Please specify with --site")
                return
        
        scraper = get_scraper(args.site, headless)
        
        # Create series object from URL
        series = Series(
            title="Unknown",  # Will be updated from page
            url=args.download_url,
            source=args.site
        )
        
        # Get series details
        logger.info(f"Fetching details for: {args.download_url}")
        try:
            series = scraper.get_series_details(series)
            logger.info(f"Series: {series.title}")
        except Exception as e:
            logger.warning(f"Could not fetch details: {e}")
            # Extract title from URL as fallback
            import urllib.parse
            path = urllib.parse.urlparse(args.download_url).path
            series.title = path.split('/')[-1].replace('-', ' ').title()
        
        # Get chapters
        logger.info("Fetching chapter list...")
        chapters = scraper.get_chapters(series)
        logger.info(f"Found {len(chapters)} chapters")
        
        if not chapters:
            logger.error("No chapters found!")
            return
        
        # Parse chapter range
        chapters_to_download = chapters
        if args.chapters:
            chapter_spec = args.chapters.lower().strip()
            if chapter_spec == 'latest':
                chapters_to_download = [chapters[-1]]
            elif chapter_spec == 'first' or chapter_spec == '1':
                chapters_to_download = [chapters[0]]
            elif '-' in chapter_spec:
                start, end = chapter_spec.split('-')
                start_idx = int(start) - 1
                end_idx = int(end)
                chapters_to_download = chapters[start_idx:end_idx]
            else:
                try:
                    idx = int(chapter_spec) - 1
                    if 0 <= idx < len(chapters):
                        chapters_to_download = [chapters[idx]]
                except ValueError:
                    pass
        
        logger.info(f"Downloading {len(chapters_to_download)} chapter(s)...")
        
        # Create output directory
        output_path.mkdir(parents=True, exist_ok=True)
        cache_file = output_path / '.download_progress.pkl'
        tracker = ProgressTracker(cache_file)
        
        # Download chapters
        for i, chapter in enumerate(chapters_to_download, 1):
            logger.info(f"[{i}/{len(chapters_to_download)}] Downloading Chapter {chapter.number}")
            try:
                scraper.download_chapter(chapter, series.title, output_path, tracker, series)
            except Exception as e:
                logger.error(f"Error downloading chapter {chapter.number}: {e}")
        
        scraper._close_driver()
        logger.info(f"Done! Downloaded to: {output_path}")
        return
    
    # Mode 1: List all series from a site (or all sites)
    if args.list_all and args.site:
        all_series = []
        
        # Check if running on all sites
        if args.site.lower() == 'all':
            logger.info("Listing series from ALL sites...")
            scrapers = get_all_scrapers(headless, limit=args.limit)
            
            for site_name, scraper in scrapers.items():
                logger.info(f"\n{'='*50}")
                logger.info(f"Scraping: {site_name.upper()}")
                logger.info(f"{'='*50}")
                
                try:
                    # For ManhuaTo, pass filter terms as genre_filter for server-side genre browsing
                    filter_terms = [t.strip() for t in args.filter.split(',')] if args.filter else None
                    if isinstance(scraper, ManhuaToScraper) and filter_terms:
                        series_list = scraper.get_all_series(genre_filter=filter_terms)
                    else:
                        series_list = scraper.get_all_series()

                    # Always add source prefix in "all" mode for clarity
                    for s in series_list:
                        s.source = site_name

                    # Apply keyword filters (title/genre based - can be done before enrichment)
                    # For ManhuaTo with genre_filter, skip re-filtering since genres were used for browsing
                    if args.filter or args.filter_all:
                        if not (isinstance(scraper, ManhuaToScraper) and filter_terms):
                            series_list = apply_keyword_filters(series_list, args.filter, args.filter_all, None)

                    # Fetch chapter counts and status if needed
                    needs_enrichment = args.with_chapters or args.min_chapters > 0 or args.max_chapters or args.status or args.min_rating > 0
                    if needs_enrichment:
                        logger.info(f"Fetching details for {len(series_list)} series...")
                        series_list = scraper.enrich_with_chapter_counts(series_list)
                        
                        if args.min_chapters > 0 or args.max_chapters:
                            series_list = filter_by_chapter_count(series_list, args.min_chapters, args.max_chapters)
                        
                        # Apply status filter after enrichment
                        if args.status:
                            statuses = [s.strip() for s in args.status.split(',')]
                            before_count = len(series_list)
                            series_list = filter_by_status(series_list, statuses)
                            logger.info(f"Filtered from {before_count} to {len(series_list)} by status")
                        
                        # Apply rating filter after enrichment
                        if args.min_rating > 0:
                            before_count = len(series_list)
                            series_list = filter_by_rating(series_list, args.min_rating)
                            logger.info(f"Filtered from {before_count} to {len(series_list)} by rating (min: {args.min_rating})")
                    
                    logger.info(f"Found {len(series_list)} series from {site_name}")
                    all_series.extend(series_list)
                    
                except Exception as e:
                    logger.error(f"Error scraping {site_name}: {e}")
                finally:
                    scraper._close_driver()
            
            logger.info(f"\nTotal: {len(all_series)} series from all sites")
            export_series_list(all_series, output_path)
            return
        
        # Single site mode
        scraper = get_scraper(args.site, headless, canvas=args.canvas, limit=args.limit)
        filter_terms = [t.strip() for t in args.filter.split(',')] if args.filter else None
        if isinstance(scraper, ManhuaToScraper) and filter_terms:
            series_list = scraper.get_all_series(genre_filter=filter_terms)
        else:
            series_list = scraper.get_all_series()

        # Apply keyword filters (title/genre based - can be done before enrichment)
        # For ManhuaTo with genre_filter, skip re-filtering since genres were used for browsing
        if args.filter or args.filter_all:
            if not (isinstance(scraper, ManhuaToScraper) and filter_terms):
                before_count = len(series_list)
                series_list = apply_keyword_filters(series_list, args.filter, args.filter_all, None)
                logger.info(f"Filtered from {before_count} to {len(series_list)} series by keywords")

        # Fetch chapter counts and status if needed
        needs_enrichment = args.with_chapters or args.min_chapters > 0 or args.max_chapters or args.status or args.min_rating > 0
        if needs_enrichment:
            logger.info(f"Fetching details for {len(series_list)} series (this may take a while)...")
            series_list = scraper.enrich_with_chapter_counts(series_list)
            
            # Apply chapter count filter
            if args.min_chapters > 0 or args.max_chapters:
                before_count = len(series_list)
                series_list = filter_by_chapter_count(series_list, args.min_chapters, args.max_chapters)
                logger.info(f"Filtered from {before_count} to {len(series_list)} series by chapter count")
            
            # Apply status filter
            if args.status:
                statuses = [s.strip() for s in args.status.split(',')]
                before_count = len(series_list)
                series_list = filter_by_status(series_list, statuses)
                logger.info(f"Filtered from {before_count} to {len(series_list)} series by status")
            
            # Apply rating filter
            if args.min_rating > 0:
                before_count = len(series_list)
                series_list = filter_by_rating(series_list, args.min_rating)
                logger.info(f"Filtered from {before_count} to {len(series_list)} series by rating (min: {args.min_rating})")
        
        export_series_list(series_list, output_path)
        scraper._close_driver()
        return
    
    # Mode 2: Download all series from a site (or all sites)
    if args.download_all and args.site:
        output_path.mkdir(parents=True, exist_ok=True)
        cache_file = output_path / '.download_progress.pkl'
        tracker = ProgressTracker(cache_file)
        
        # Check if running on all sites
        if args.site.lower() == 'all':
            logger.info("Downloading from ALL sites (with source prefix)...")
            scrapers = get_all_scrapers(headless, limit=args.limit)
            
            total_series = 0
            for site_name, scraper in scrapers.items():
                logger.info(f"\n{'='*50}")
                logger.info(f"Processing: {site_name.upper()}")
                logger.info(f"{'='*50}")
                
                try:
                    # For ManhuaTo, pass filter terms as genre_filter for server-side genre browsing
                    filter_terms = [t.strip() for t in args.filter.split(',')] if args.filter else None
                    if isinstance(scraper, ManhuaToScraper) and filter_terms:
                        series_list = scraper.get_all_series(genre_filter=filter_terms)
                    else:
                        series_list = scraper.get_all_series()

                    # Set source for all series
                    for s in series_list:
                        s.source = site_name

                    # Apply keyword filters (title/genre based)
                    # For ManhuaTo with genre_filter, skip re-filtering since genres were used for browsing
                    if args.filter or args.filter_all:
                        if not (isinstance(scraper, ManhuaToScraper) and filter_terms):
                            series_list = apply_keyword_filters(series_list, args.filter, args.filter_all, None)
                            logger.info(f"Filtered to {len(series_list)} series by keywords")
                    
                    # Fetch details if needed for filtering
                    needs_enrichment = args.min_chapters > 0 or args.max_chapters or args.status or args.min_rating > 0
                    if needs_enrichment:
                        logger.info(f"Fetching details for {len(series_list)} series...")
                        series_list = scraper.enrich_with_chapter_counts(series_list)
                        
                        if args.min_chapters > 0 or args.max_chapters:
                            before_count = len(series_list)
                            series_list = filter_by_chapter_count(series_list, args.min_chapters, args.max_chapters)
                            logger.info(f"Filtered from {before_count} to {len(series_list)} by chapter count")
                        
                        if args.status:
                            statuses = [s.strip() for s in args.status.split(',')]
                            before_count = len(series_list)
                            series_list = filter_by_status(series_list, statuses)
                            logger.info(f"Filtered from {before_count} to {len(series_list)} by status")
                        
                        if args.min_rating > 0:
                            before_count = len(series_list)
                            series_list = filter_by_rating(series_list, args.min_rating)
                            logger.info(f"Filtered from {before_count} to {len(series_list)} by rating (min: {args.min_rating})")
                    
                    if args.limit:
                        series_list = series_list[:args.limit]
                    
                    logger.info(f"Will download {len(series_list)} series from {site_name}")
                    total_series += len(series_list)
                    
                    for i, series in enumerate(series_list, 1):
                        logger.info(f"[{i}/{len(series_list)}] Processing: {series.title}")
                        
                        try:
                            # Fetch full details for metadata if not already done
                            if series.rating == 0.0 and not series.description:
                                series = scraper.get_series_details(series)
                            
                            chapters = scraper.get_chapters(series)
                            logger.info(f"  Found {len(chapters)} chapters")
                            
                            # Always use source prefix in "all" mode
                            display_title = f"[{site_name.title()}] {series.title}"
                            
                            # Create a copy of series with prefixed title for metadata
                            series_for_meta = copy.copy(series)
                            series_for_meta.title = display_title
                            
                            for chapter in chapters:
                                scraper.download_chapter(chapter, display_title, output_path, tracker, series_for_meta)
                                
                        except Exception as e:
                            logger.error(f"  Error processing {series.title}: {e}")
                            continue
                    
                except Exception as e:
                    logger.error(f"Error with {site_name}: {e}")
                finally:
                    scraper._close_driver()
            
            logger.info(f"\nDownload complete! Processed {total_series} series from all sites.")
            return
        
        # Single site mode
        scraper = get_scraper(args.site, headless, canvas=args.canvas, limit=args.limit)
        filter_terms = [t.strip() for t in args.filter.split(',')] if args.filter else None
        if isinstance(scraper, ManhuaToScraper) and filter_terms:
            series_list = scraper.get_all_series(genre_filter=filter_terms)
        else:
            series_list = scraper.get_all_series()

        # Apply keyword filters (title/genre based)
        # For ManhuaTo with genre_filter, skip re-filtering since genres were used for browsing
        if args.filter or args.filter_all:
            if not (isinstance(scraper, ManhuaToScraper) and filter_terms):
                series_list = apply_keyword_filters(series_list, args.filter, args.filter_all, None)
                logger.info(f"Filtered to {len(series_list)} series by keywords")

        # Fetch details if needed for filtering
        needs_enrichment = args.min_chapters > 0 or args.max_chapters or args.status or args.min_rating > 0
        if needs_enrichment:
            logger.info(f"Fetching details for {len(series_list)} series to apply filters...")
            series_list = scraper.enrich_with_chapter_counts(series_list)
            
            if args.min_chapters > 0 or args.max_chapters:
                before_count = len(series_list)
                series_list = filter_by_chapter_count(series_list, args.min_chapters, args.max_chapters)
                logger.info(f"Filtered from {before_count} to {len(series_list)} by chapter count (min: {args.min_chapters}, max: {args.max_chapters or 'unlimited'})")
            
            if args.status:
                statuses = [s.strip() for s in args.status.split(',')]
                before_count = len(series_list)
                series_list = filter_by_status(series_list, statuses)
                logger.info(f"Filtered from {before_count} to {len(series_list)} by status")
            
            if args.min_rating > 0:
                before_count = len(series_list)
                series_list = filter_by_rating(series_list, args.min_rating)
                logger.info(f"Filtered from {before_count} to {len(series_list)} by rating (min: {args.min_rating})")
        
        if args.limit:
            series_list = series_list[:args.limit]
        
        logger.info(f"Will download {len(series_list)} series")
        
        # Download each series
        for i, series in enumerate(series_list, 1):
            logger.info(f"[{i}/{len(series_list)}] Processing: {series.title}")
            
            try:
                # Fetch full details for metadata if not already done
                if series.rating == 0.0 and not series.description:
                    series = scraper.get_series_details(series)
                
                chapters = scraper.get_chapters(series)
                logger.info(f"  Found {len(chapters)} chapters")
                
                # Apply source prefix if requested
                display_title = series.title
                series_for_meta = series
                if args.source_prefix:
                    source_name = series.source.title() if series.source else scraper.SITE_NAME.title()
                    display_title = f"[{source_name}] {series.title}"
                    # Create copy with prefixed title for metadata
                    series_for_meta = copy.copy(series)
                    series_for_meta.title = display_title
                
                for chapter in chapters:
                    scraper.download_chapter(chapter, display_title, output_path, tracker, series_for_meta)
                    
            except Exception as e:
                logger.error(f"  Error processing {series.title}: {e}")
                continue
        
        scraper._close_driver()
        logger.info("Download complete!")
        return
    
    # Mode 3: Download from config file
    if args.config:
        series_list = load_series_list(Path(args.config))
        
        if args.limit:
            series_list = series_list[:args.limit]
        
        logger.info(f"Loaded {len(series_list)} series from config")
        
        output_path.mkdir(parents=True, exist_ok=True)
        cache_file = output_path / '.download_progress.pkl'
        tracker = ProgressTracker(cache_file)
        
        # Group by source
        by_source = {}
        for s in series_list:
            by_source.setdefault(s.source, []).append(s)
        
        for source, series in by_source.items():
            scraper = get_scraper(source, headless)
            
            for i, s in enumerate(series, 1):
                logger.info(f"[{i}/{len(series)}] Processing: {s.title}")
                
                try:
                    # Fetch full details for metadata if not already in config
                    if s.rating == 0.0 and not s.description:
                        s = scraper.get_series_details(s)
                    
                    chapters = scraper.get_chapters(s)
                    for chapter in chapters:
                        scraper.download_chapter(chapter, s.title, output_path, tracker, s)
                except Exception as e:
                    logger.error(f"Error: {e}")
            
            scraper._close_driver()
        
        logger.info("Download complete!")
        return
    
    parser.print_help()


if __name__ == '__main__':
    main()
