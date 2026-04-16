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
- manhuafast.net
- reset-scans.org

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
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote, urlunparse

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
        # Use a JSON file alongside the legacy pkl name for safe storage
        self.cache_file = cache_file.with_suffix('.json')
        self._legacy_file = cache_file  # old .pkl path for one-time migration
        self.downloaded: Set[str] = set()
        self.load()

    def load(self):
        # Try JSON cache first
        if self.cache_file.exists():
            try:
                import json as _json
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.downloaded = set(_json.load(f))
                logger.info(f"Loaded progress: {len(self.downloaded)} chapters already downloaded")
                self._migrate_asura_urls()
                return
            except Exception as e:
                logger.warning(f"Could not load progress cache: {e}")
                self.downloaded = set()
        # One-time migration: read old pickle file if it exists, then convert
        if self._legacy_file.exists():
            try:
                import pickle as _pickle
                with open(self._legacy_file, 'rb') as f:
                    self.downloaded = _pickle.load(f)
                logger.info(f"Migrated {len(self.downloaded)} entries from legacy pickle cache")
                self._migrate_asura_urls()
                self.save()  # persist as JSON immediately
                self._legacy_file.unlink(missing_ok=True)  # remove old pkl
            except Exception as e:
                logger.warning(f"Could not migrate legacy progress cache: {e}")
                self.downloaded = set()

    def _migrate_asura_urls(self):
        """Rewrite old asuracomic.net/series/ tracker entries to new asurascans.com/comics/ format."""
        old_urls = [u for u in self.downloaded if 'asuracomic.net/series/' in u]
        if not old_urls:
            return
        for url in old_urls:
            self.downloaded.discard(url)
            self.downloaded.add(url.replace('asuracomic.net/series/', 'asurascans.com/comics/'))
        logger.info(f"Migrated {len(old_urls)} Asura tracker URLs to new domain/path")
        self.save()

    def save(self):
        try:
            import json as _json
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                _json.dump(list(self.downloaded), f)
        except Exception as e:
            logger.warning(f"Could not save progress cache: {e}")
    
    def is_downloaded(self, chapter_url: str) -> bool:
        return chapter_url in self.downloaded
    
    def mark_downloaded(self, chapter_url: str):
        """Add chapter URL to the in-memory downloaded set.

        Does NOT write to disk — callers must invoke save() explicitly
        (e.g. once per series) to avoid hundreds of individual JSON writes.
        """
        self.downloaded.add(chapter_url)


class BaseSiteScraper:
    """Base class for site-wide scraping"""
    
    BASE_URL = ""
    SITE_NAME = ""
    
    # Rate limiting
    MIN_DELAY = 2  # Minimum seconds between requests
    MAX_DELAY = 5  # Maximum seconds between requests

    # Cloudflare-protected sites that benefit from FlareSolverr
    CLOUDFLARE_SITE = False

    # Concurrent image download threads.  Override to a lower value for CDNs
    # that rate-limit or 504 under parallel load (e.g. ManhuaFast/Drake sites).
    _DOWNLOAD_WORKERS = 8

    def __init__(self, headless: bool = True, limit: int = None, max_pages: int = None):
        self.headless = headless
        self.driver = None
        self.limit = limit  # Stop after finding this many series
        self.max_pages = max_pages  # Max pages to browse per category (None = unlimited)
        self._use_flaresolverr = False
        self._fs_cookies_applied = False
        # Track cover URLs that have already failed so we don't spam a 403
        # warning on every chapter of a series when the cover is unavailable.
        self._failed_cover_urls: set = set()
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
        except Exception:
            pass
        # Linux - try multiple browser names
        for browser in ['google-chrome', 'chromium-browser', 'chromium']:
            try:
                result = subprocess.run([browser, '--version'], capture_output=True, text=True, timeout=5)
                match = regex.search(r'(\d+)\.', result.stdout)
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

    def _flaresolverr_post(self, url: str, post_data: str,
                           cookies: list = None, max_timeout: int = 60000):
        """Use FlareSolverr to POST to a URL (e.g. admin-ajax.php).

        Sending the POST through FlareSolverr's headless browser keeps us in
        the same Cloudflare-cleared browser session, which is required for
        sites that bind cf_clearance to a TLS fingerprint.  The caller can pass
        the raw cookie list returned by a prior _flaresolverr_get call so that
        the same WordPress/Cloudflare session is reused.

        Returns (html, cookies_list, user_agent) or raises on failure.
        """
        payload = {
            "cmd": "request.post",
            "url": url,
            "postData": post_data,
            "maxTimeout": max_timeout,
        }
        if cookies:
            payload["cookies"] = cookies
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
        resp_cookies = solution.get("cookies", [])
        user_agent = solution.get("userAgent", "")
        return html, resp_cookies, user_agent

    def _apply_flaresolverr_cookies(self, cookies: list, user_agent: str = ""):
        """Apply cookies from FlareSolverr to the requests session.

        Also saves the raw cookie list to self._last_fs_raw_cookies so that
        follow-up FlareSolverr POST requests (e.g. admin-ajax.php) can reuse
        the same session without needing to re-solve the Cloudflare challenge.
        """
        applied = 0
        for c in cookies:
            domain = c.get("domain", "").strip()
            if not domain:
                logger.debug(f"Skipping cookie '{c.get('name', '?')}' with empty domain")
                continue
            self.session.cookies.set(
                c["name"], c["value"],
                domain=domain,
                path=c.get("path", "/"),
            )
            applied += 1
        if user_agent:
            self.session.headers["User-Agent"] = user_agent
        # Stash raw cookies for follow-up FlareSolverr POST requests
        self._last_fs_raw_cookies = list(cookies)
        logger.debug(f"Applied {applied}/{len(cookies)} FlareSolverr cookies to session")

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
        except Exception:
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
        except Exception:
            pass
        
        self.driver.implicitly_wait(10)


    def _close_driver(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    @staticmethod
    def _is_browser_error_page(soup) -> bool:
        """Detect browser/OS network error pages (Chrome ERR_*, Firefox, etc.)
        that contain no real content.  These must not overwrite series metadata.
        """
        # Chrome error pages have a distinctive div or body class
        if soup.select_one('#main-frame-error, #error-information-popup-container'):
            return True
        body = soup.find('body')
        if body and 'neterror' in body.get('class', []):
            return True

        # Fallback: check the page title for well-known browser error strings
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text(strip=True).lower()
            error_titles = (
                'your connection was interrupted',
                'your connection was reset',
                'your connection is not private',
                "this site can't be reached",
                "this page isn't working",
                'server not found',
                'unable to connect',
                'the connection was reset',
                'err_connection_interrupted',
                'err_connection_refused',
                'err_connection_reset',
                'err_connection_timed_out',
                'err_name_not_resolved',
                'err_internet_disconnected',
            )
            if any(e in title_text for e in error_titles):
                return True

        return False

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
                    # Force UTF-8 — modern manga sites always use UTF-8 regardless
                    # of what the Content-Type header claims (often omits charset or
                    # says iso-8859-1), which causes requests to misread curly quotes
                    # and other non-ASCII chars as mojibake (e.g. â for â€™).
                    resp.encoding = 'utf-8'
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
                # Fall through to Selenium if available — but only if a driver
                # can actually be created.  Sites that run in pure-FlareSolverr
                # mode (e.g. DrakeFullScraper on ARM) never init self.driver, so
                # attempting driver.get() here would raise AttributeError.
                if not self.driver:
                    return BeautifulSoup("", 'html.parser')

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
            except Exception:
                pass  # Continue even if wait fails

            html = self.driver.page_source
        else:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            # Force UTF-8 to prevent mojibake on sites that omit charset in headers
            response.encoding = 'utf-8'
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
                except Exception:
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

            # If we got a browser error page (ERR_CONNECTION_INTERRUPTED, etc.)
            # instead of real content, bail out immediately — do NOT overwrite
            # any existing series metadata (especially series.title) with text
            # from the error page (e.g. "Your connection was interrupted").
            if self._is_browser_error_page(soup):
                logger.warning(
                    f"Browser error page detected for {series.url!r} — "
                    f"skipping detail fetch, keeping title: {series.title!r}"
                )
                return series

            # Always prefer the detail page title — it is more authoritative
            # than the listing page title, which may be shortened, use an
            # alternate translation, or come from a generic link attribute.
            detail_title = self._extract_title_from_soup(soup)
            if detail_title:
                series.title = detail_title
            
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

            # Get chapter count if not set.  Store the chapters list as a
            # dynamic attribute so the download_all loop can reuse it without
            # making a second identical network request.
            if series.chapters_count == 0:
                try:
                    chapters = self.get_chapters(series)
                    series.chapters_count = len(chapters)
                    series._chapters_cache = chapters  # consumed once by download_all
                except Exception:
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
            except Exception:
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
            except Exception:
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
            except Exception:
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
            except Exception:
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
                    # Clean up common prefixes (including plurals like "Authors:")
                    text = re.sub(r'^(Authors?|Writers?|By)[:\s]*', '', text, flags=re.I)
                    if text and len(text) > 1 and len(text) < 100:
                        return text
            except Exception:
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
                    text = re.sub(r'^(Artists?|Illustrators?)[:\s]*', '', text, flags=re.I)
                    if text and len(text) > 1 and len(text) < 100:
                        return text
            except Exception:
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
            except Exception:
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
            # Do NOT set User-Agent here — Cloudflare-protected sites (Drake,
            # ManhuaTo) validate that the UA matches the one used during the
            # CF challenge.  FlareSolverr already stored the correct UA in
            # self.session.headers; overriding it with a generic string causes
            # a 403 even when the cf_clearance cookie is valid.
            headers = {}
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
                'manhuafast': 'ManhuaFast',
                'resetscans': 'Reset Scans',
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

    @staticmethod
    def _filter_outlier_images_by_dimension(temp_dir: Path):
        """Remove downloaded images with outlier dimensions (likely promotional covers).

        Chapter pages share similar widths. Promo covers from other series are
        typically a different size. If 5+ images exist, remove any whose width
        differs significantly from the majority.
        """
        try:
            from PIL import Image
        except ImportError:
            return  # Pillow not available, skip

        img_files = sorted([
            f for f in temp_dir.iterdir()
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif')
        ])

        if len(img_files) < 5:
            return  # Too few to reliably detect outliers

        # Get widths of all images
        widths = []
        for f in img_files:
            try:
                with Image.open(f) as img:
                    widths.append((f, img.width))
            except Exception:
                widths.append((f, 0))

        # Find the most common width — chapter pages should cluster around it
        width_values = [w for _, w in widths if w > 0]
        if not width_values:
            return

        # Use the median width as reference
        sorted_widths = sorted(width_values)
        median_width = sorted_widths[len(sorted_widths) // 2]

        # Remove images whose width differs by more than 30% from the median
        removed = 0
        for f, w in widths:
            if w == 0:
                continue
            if abs(w - median_width) / median_width > 0.30:
                logger.info(f"Removing outlier image {f.name} (width {w} vs median {median_width})")
                f.unlink()
                removed += 1

        if removed:
            logger.info(f"Removed {removed} outlier image(s) by dimension")

    def _scan_series_dir(self, series_title: str, output_dir: Path) -> set:
        """Return the set of CBZ filenames already present in the series directory.

        Called once per series before the chapter loop so that per-chapter
        existence checks can be done as O(1) set lookups rather than individual
        stat() syscalls — critical on NFS/network mounts where each stat can
        take hundreds of milliseconds.
        """
        safe_title = self._sanitize_filename(series_title)
        series_dir = output_dir / safe_title
        try:
            return {f.name for f in series_dir.iterdir() if f.suffix == '.cbz'}
        except (FileNotFoundError, PermissionError):
            return set()

    def download_chapter(self, chapter: Chapter, series_title: str,
                        output_dir: Path, tracker: ProgressTracker,
                        series: Series = None,
                        existing_cbzs: set = None) -> bool:
        """Download a chapter and create CBZ with metadata.

        existing_cbzs: optional set of CBZ filenames already on disk for this
        series, pre-scanned by _scan_series_dir().  When provided, all
        existence checks use O(1) set membership instead of stat() syscalls.
        """

        safe_title = self._sanitize_filename(series_title)
        safe_chapter = self._sanitize_filename(chapter.number)

        series_dir = output_dir / safe_title
        # Guard against path traversal: series_dir must stay inside output_dir
        try:
            series_dir.resolve().relative_to(output_dir.resolve())
        except ValueError:
            logger.error(f"Path traversal detected for title '{series_title}' — skipping")
            return 'fail'
        cbz_name = f"{safe_title} - Chapter {safe_chapter}.cbz"
        cbz_path = series_dir / cbz_name

        # Helper: O(1) set lookup when pre-scan is available, stat() fallback otherwise.
        def _exists():
            if existing_cbzs is not None:
                return cbz_name in existing_cbzs
            return cbz_path.exists()

        # Check if already downloaded — but only trust the cache if the CBZ file
        # actually exists on disk.  If the file was deleted, re-download it.
        if tracker.is_downloaded(chapter.url):
            if _exists():
                logger.debug(f"Skipping (already downloaded): {series_title} Ch.{chapter.number}")
                return 'skip'
            else:
                # File was deleted — clear from cache so we re-download.
                # The in-memory discard is enough here; tracker.save() will
                # be called at the end of the series loop.
                tracker.downloaded.discard(chapter.url)
                logger.info(f"Re-downloading (file missing): {cbz_name}")

        series_dir.mkdir(parents=True, exist_ok=True)

        # Download series cover image once (if not already present).
        # Skip if we already tried and failed for this URL — avoids a 403
        # warning on every chapter when the cover host blocks direct fetches.
        if series and series.cover_url and series.cover_url not in self._failed_cover_urls:
            existing_covers = list(series_dir.glob('cover.*'))
            if not existing_covers:
                result = self._download_cover(series.cover_url, series_dir, referer=series.url)
                if result is None:
                    self._failed_cover_urls.add(series.cover_url)

        if _exists():
            tracker.mark_downloaded(chapter.url)
            logger.info(f"Already exists: {cbz_name}")
            return 'exists'

        logger.info(f"Downloading: {series_title} - Chapter {chapter.number}")

        # Cover media ID exclusion was specific to old asuracomic.net CDN structure;
        # new asurascans.com CDN uses sequential page filenames so this is not needed.
        self._cover_media_ids = set()

        try:
            pages = self.get_pages(chapter)
            if not pages:
                # Drake paywalled chapters return 0 pages silently (logged at DEBUG
                # in get_pages); other sites treat this as a real error.
                if self.SITE_NAME != 'drake':
                    logger.error(f"No pages found for chapter {chapter.number}")
                return 'fail'
            
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

            with ThreadPoolExecutor(max_workers=self._DOWNLOAD_WORKERS) as pool:
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

            # Post-download: remove outlier images by dimension
            # Promotional covers have different aspect ratios than chapter pages
            self._filter_outlier_images_by_dimension(temp_dir)

            # Create CBZ with metadata
            self._create_cbz(temp_dir, cbz_path, series, chapter)
            
            # Cleanup
            for f in temp_dir.iterdir():
                f.unlink()
            temp_dir.rmdir()
            
            # Mark as downloaded and update the in-memory set so the rest of
            # this run's chapter loop doesn't re-check a file we just wrote.
            tracker.mark_downloaded(chapter.url)
            if existing_cbzs is not None:
                existing_cbzs.add(cbz_name)

            logger.info(f"Created: {cbz_name} ({success_count} pages)")
            return 'new'

        except Exception as e:
            logger.error(f"Error downloading chapter: {e}")
            return 'fail'
    
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


class AsuraFullScraper(BaseSiteScraper):
    """Full site scraper for asurascans.com (formerly asuracomic.net).

    Site migrated to Astro framework; series at /comics/slug-id,
    chapters at /comics/slug-id/chapter/N,
    images at cdn.asurascans.com/asura-images/chapters/hash/chapter/001.webp
    """

    BASE_URL = "https://asurascans.com"
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
                # New site: /browse?genres=action
                genre_links = soup.select('a[href*="/browse?genres="], a[href*="&genres="]')
                if genre_links:
                    genres = []
                    for link in genre_links:
                        text = link.get_text(strip=True).strip(',').strip()
                        if text and text.lower() not in ('genres', ''):
                            genres.append(text)
                    if genres:
                        seen = set()
                        unique = []
                        for g in genres:
                            if g.lower() not in seen:
                                seen.add(g.lower())
                                unique.append(g)
                        series.genres = unique

            # --- Synopsis ---
            if not series.description:
                # Strategy 1: Astro site uses id="description-text"
                desc_elem = soup.select_one('#description-text')
                if desc_elem:
                    text = desc_elem.get_text(separator=' ', strip=True)
                    text = re.sub(r'^\s*\[.*?(?:brought you|studio).*?\]\s*', '', text, flags=re.I | re.S)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if len(text) > 20:
                        series.description = text[:2000]

                # Strategy 2: h3 "Synopsis" sibling (legacy fallback)
                if not series.description:
                    for h3 in soup.select('h3'):
                        if 'Synopsis' in h3.get_text():
                            sibling = h3.find_next_sibling('span')
                            if sibling:
                                p = sibling.find('p')
                                text = (p or sibling).get_text(strip=True)
                                text = re.sub(r'^\s*\[.*?(?:brought you|studio).*?\]\s*', '', text, flags=re.I | re.S)
                                text = text.strip()
                                if len(text) > 20:
                                    series.description = re.sub(r'\s+', ' ', text)[:2000]
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
            # New site uses /browse?page=N for the series listing
            url = f"{self.BASE_URL}/browse?page={page}"
            logger.info(f"Fetching page {page}...")

            try:
                soup = self._get_soup(url, use_selenium=True)

                # Debug: log page title to confirm we're on the right page
                page_title = soup.select_one('title')
                logger.debug(f"Page title: {page_title.get_text() if page_title else 'No title'}")

                # New Astro site: series cards are <a href="/comics/slug-id"> links
                all_links = soup.select('a[href*="/comics/"]')
                items = [a for a in all_links if re.search(r'/comics/[\w-]+-[a-f0-9]+', a.get('href', ''))]
                logger.debug(f"Found {len(items)} series links")
                
                if not items:
                    logger.info(f"No more series found on page {page}")
                    break
                
                found_count = 0
                
                for item in items:
                    href = item.get('href', '')

                    # Skip if not a valid series link (must be /comics/slug-id pattern)
                    if not href or '/comics/' not in href:
                        continue

                    # Skip chapter links (e.g. /comics/slug/chapter/1)
                    if '/chapter/' in href:
                        continue

                    # Normalize URL for deduplication
                    normalized_href = href.rstrip('/').split('?')[0]

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
                        # Skip generic alt values that are not real titles
                        _SKIP_ALTS = {'MANHWA', 'MANHUA', 'MANGA', 'WEBTOON', 'POSTER', 'COVER', 'THUMBNAIL', 'IMAGE'}
                        if alt and len(alt) > 3 and alt.upper() not in _SKIP_ALTS:
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
                        nested_link = item.select_one('a[href*="/comics/"]')
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
                        except Exception:
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
                
                # Page limit (user-specified or safety cap)
                if page > (self.max_pages or 200):
                    logger.warning(f"Reached page limit ({self.max_pages or 200})")
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

        # Derive the series slug path so we only collect chapters that belong to
        # THIS series (e.g. "/comics/swords-master-youngest-son-abc123/").
        # Asura pages show a "Latest Chapters" sidebar with links from OTHER
        # series — using a broad `a[href*="chapter"]` would pick those up too.
        from urllib.parse import urlparse
        parsed_series = urlparse(series.url)
        # series path: e.g. "/comics/swords-master-youngest-son-abc123"
        series_path = parsed_series.path.rstrip('/')

        # First try: scope to the scrollable chapter list container
        chapter_container = (
            soup.select_one('div[class*="scrollbar"]') or
            soup.select_one('div[class*="chapter-list"]') or
            soup.select_one('div[class*="chapters"]')
        )
        search_root = chapter_container if chapter_container else soup

        for link in search_root.select('a[href*="chapter"]'):
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

            # Skip chapters that belong to a different series.
            # If we found a scrollbar container, skip this check (already scoped).
            if not chapter_container:
                if series_path not in urlparse(full_url).path:
                    continue

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
        """No-op on the new CDN — all chapter images share the same CDN path prefix
        so there are no sidebar/cover outliers to remove.  Kept for API compatibility.
        """

        return [url for _, url in filtered]

    @staticmethod
    def _is_chapter_page_url(url: str) -> bool:
        """Check if a URL is a chapter page image from the Asura CDN.

        Chapter pages: cdn.asurascans.com/asura-images/chapters/hash/chapter/001.webp
        Covers:        cdn.asurascans.com/asura-images/covers/...
        """
        return 'cdn.asurascans.com/asura-images/chapters/' in url

    @staticmethod
    def _unwrap_astro(obj):
        """Recursively unwrap Astro's [typeIndex, value] serialisation format.

        Astro serialises component props as nested [primitive, value] pairs.
        A 2-element list whose first item is a non-collection primitive is
        treated as [typeIndex, payload] — we discard the index and recurse
        into the payload.  All other lists and dicts are traversed normally.
        """
        if isinstance(obj, list):
            if len(obj) == 2 and not isinstance(obj[0], (list, dict)):
                return AsuraFullScraper._unwrap_astro(obj[1])
            return [AsuraFullScraper._unwrap_astro(x) for x in obj]
        if isinstance(obj, dict):
            return {k: AsuraFullScraper._unwrap_astro(v) for k, v in obj.items()}
        return obj

    def _extract_asura_images(self, html: str) -> List[str]:
        """Extract chapter image URLs from Asura HTML.

        The site was rebuilt from scratch in Feb 2026.  Chapter images are
        now embedded as Astro component props — a 'props' attribute on an
        island element containing a JSON-encoded page list — rather than
        plain <img> tags or CDN URLs baked into the HTML.

        Strategy 1 (new site): find the Astro island element whose 'props'
          attribute contains "pages", parse and unwrap the JSON, and collect
          the 'url' field from each page object.

        Strategy 2 (legacy fallback): regex + img-tag scan for the old
          cdn.asurascans.com CDN URL pattern, for any page that may still
          render the old way.
        """
        soup = BeautifulSoup(html, 'html.parser')

        # --- Strategy 1: Astro props (new site, Feb 2026 rebuild) ---
        # Mirrors Tachiyomi's extractAstroProp<PageListDto>("pages")
        props_elem = soup.find(
            lambda tag: tag.has_attr('props') and 'pages' in tag.get('props', '')
        )
        if props_elem:
            try:
                raw_props = json.loads(props_elem.get('props', ''))
                unwrapped = self._unwrap_astro(raw_props)
                pages_data = unwrapped.get('pages', []) if isinstance(unwrapped, dict) else []
                urls = [p['url'] for p in pages_data if isinstance(p, dict) and p.get('url')]
                if urls:
                    logger.info(f"Found {len(urls)} chapter images from Astro props")
                    return urls
            except Exception as e:
                logger.debug(f"Astro props extraction failed: {e}")

        # --- Strategy 2: legacy CDN regex + img-tag scan ---
        seen: set = set()
        pages: List[str] = []

        def _add(url: str):
            url = url.strip()
            if url and url not in seen and self._is_chapter_page_url(url):
                seen.add(url)
                pages.append(url)

        normalised = html.replace('\\/', '/')
        for url in re.findall(
            r'https?://cdn\.asurascans\.com/asura-images/chapters/[^\s"\'<>]+\.(?:webp|jpg|jpeg|png)',
            normalised,
        ):
            _add(url)

        for img in soup.select('img'):
            for attr in ('src', 'data-src', 'data-lazy-src', 'data-original'):
                _add(img.get(attr, ''))
            for entry in img.get('srcset', '').split(','):
                _add(entry.strip().split()[0] if entry.strip() else '')

        if pages:
            def _page_num(u: str) -> int:
                m = re.search(r'/(\d+)\.(?:webp|jpg|jpeg|png)$', u)
                return int(m.group(1)) if m else 0
            pages.sort(key=_page_num)
            logger.info(f"Found {len(pages)} chapter images from legacy CDN scan")

        return pages

    def _get_pages_selenium_scroll(self, url: str) -> List[str]:
        """Fetch chapter images using Selenium with incremental scroll.

        FlareSolverr only renders the initial viewport, so chapter images that
        use IntersectionObserver-based lazy loading (below the fold) never get
        their src resolved in FlareSolverr's HTML snapshot.  Headless Chromium
        via Selenium actually scrolls through the page, triggering lazy loads.
        """
        self._init_driver()
        self.driver.get(url)
        time.sleep(4)  # Wait for initial JS hydration

        # Scroll incrementally from top to bottom so IntersectionObserver fires
        # for every image strip as it enters the viewport.
        scroll_step = 400
        position = 0
        while True:
            page_height = self.driver.execute_script("return document.body.scrollHeight")
            if position >= page_height:
                break
            self.driver.execute_script(f"window.scrollTo(0, {position})")
            position += scroll_step
            time.sleep(0.15)
        # Final pause to let the last batch of images finish loading
        time.sleep(2)

        return self._extract_asura_images(self.driver.page_source)

    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter from Asura Scans.

        Strategy:
        1. FlareSolverr (ARM) or Selenium (x86) renders the page.
        2. If < MIN_PAGES found, the cached-session fast path likely returned
           shell HTML (og:image preloads only) — retry with a fresh FlareSolverr
           render.
        3. If FlareSolverr still can't get enough images after retries (the Astro
           chapter viewer lazy-loads images via IntersectionObserver and
           FlareSolverr only renders the initial viewport), fall back to headless
           Selenium with full-page auto-scroll to trigger all lazy loads.
        """
        MIN_PAGES = 3
        max_attempts = 2 if self._use_flaresolverr else 1
        best_pages: List[str] = []

        for attempt in range(1, max_attempts + 1):
            try:
                soup = self._get_soup(chapter.url, use_selenium=True)
                pages = self._extract_asura_images(str(soup))

                if len(pages) > len(best_pages):
                    best_pages = pages

                if len(pages) >= MIN_PAGES:
                    return pages

                # Too few — retry with fresh FlareSolverr if attempts remain
                if attempt < max_attempts and self._use_flaresolverr:
                    logger.warning(
                        f"Only {len(pages)} image(s) for {chapter.url} (attempt {attempt}), "
                        f"forcing fresh FlareSolverr render..."
                    )
                    self._fs_cookies_applied = False
                    self.session.cookies.clear()
                    time.sleep(2)
                    continue

            except Exception as e:
                logger.error(f"Error getting pages (attempt {attempt}): {e}")
                if attempt < max_attempts:
                    self._fs_cookies_applied = False
                    self.session.cookies.clear()
                    time.sleep(2)
                    continue

        # FlareSolverr exhausted with insufficient images.
        # On ARM the scraper runs inside Docker with no host Chromium, so the
        # Selenium+scroll fallback won't work there — skip it and return best.
        # On x86 we can try headless Selenium with auto-scroll.
        if not self._is_arm():
            logger.info(
                f"FlareSolverr returned only {len(best_pages)} image(s) for {chapter.url}; "
                f"falling back to Selenium+scroll to trigger lazy loading..."
            )
            try:
                pages = self._get_pages_selenium_scroll(chapter.url)
                if pages:
                    logger.info(f"Selenium+scroll found {len(pages)} images for {chapter.url}")
                    return pages
            except Exception as e:
                logger.warning(f"Selenium+scroll fallback failed for {chapter.url}: {e}")
        else:
            logger.warning(
                f"ARM: FlareSolverr returned only {len(best_pages)} image(s) for {chapter.url}; "
                f"Selenium+scroll not available on ARM — chapter images may be incomplete."
            )

        if best_pages:
            logger.warning(
                f"Returning partial page list ({len(best_pages)} images) for {chapter.url}"
            )
            return best_pages

        logger.warning(f"No chapter images found for {chapter.url}")
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
            max_scrolls = self.max_pages or 20

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

            if not href:
                continue

            # Use separator=' ' so adjacent inline elements don't merge digits.
            # e.g. <a>Chapter 1<span>3 years ago</span></a> becomes
            # "Chapter 1 3 years ago" instead of "Chapter 13 years ago".
            text = link.get_text(separator=' ', strip=True)

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
            # Skip "First Chapter" and "Latest Chapter" meta-links
            if text.lower() in ('first chapter', 'latest chapter'):
                continue
            seen_urls.add(full_url)

            # Try specific chapter-number element first to avoid timestamp bleed
            num_elem = link.select_one(
                '[class*="chapter-num"], [class*="chapternum"], [class*="chapter_num"], '
                '.chap-num, .ch-name, .epxs'
            )
            if num_elem:
                text = num_elem.get_text(separator=' ', strip=True)

            # Extract chapter number
            match = re.search(r'chapter\s*(\d+(?:\.\d+)?)', text, re.I)
            if not match:
                match = re.search(r'chapter[/\- ]?(\d+(?:\.\d+)?)', href, re.I)
            if not match:
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

    # Webtoon is not Cloudflare-protected — use a lighter delay than the
    # default 2–5 s so chapter-list pagination doesn't dominate runtime.
    MIN_DELAY = 0.5
    MAX_DELAY = 1.5

    # Webtoon genres for ORIGINALS
    GENRES = [
        'drama', 'fantasy', 'comedy', 'action', 'slice-of-life', 'romance',
        'superhero', 'sci-fi', 'thriller', 'supernatural', 'mystery', 
        'sports', 'historical', 'heartwarming', 'horror', 'informative'
    ]
    
    def __init__(self, headless: bool = True, canvas: bool = False, limit: int = None, max_pages: int = None):
        super().__init__(headless, limit=limit, max_pages=max_pages)
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

                # Fixed safety cap only — self.max_pages controls how many
                # catalog/browse pages to scan for series discovery, NOT how
                # many chapter-list pages to fetch per series.
                if page > 200:
                    logger.warning(f"Reached chapter page safety cap (200) for {series.title}")
                    break

            except Exception as e:
                logger.error(f"Error fetching chapter list page {page}: {e}")
                break

        # Sort by episode number
        chapters.sort(key=lambda x: int(x.number) if x.number.isdigit() else 0)

        logger.info(f"Found {len(chapters)} free chapters for {series.title}")
        return chapters
    
    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter.

        Webtoon embeds image URLs in the static HTML via data-url attributes on
        <img> tags inside #_imageList.  No JavaScript execution is needed, so a
        plain HTTP request is ~10× faster than spinning up a Selenium driver.
        We try requests first and only fall back to Selenium when the fast path
        returns nothing (e.g. a redirect or age-gate check page).
        """
        def _extract(soup) -> list:
            pages = []
            for img in soup.select('#_imageList img, .viewer_img img, #content img._images'):
                src = img.get('data-url') or img.get('data-src') or img.get('src', '')
                if src and 'webtoon' in src.lower() and 'blank' not in src.lower():
                    src = src.split('?')[0] if '?' in src else src
                    if src not in pages:
                        pages.append(src)
            return pages

        # Fast path: plain HTTP request (no Selenium/5 s wait overhead)
        try:
            soup = self._get_soup(chapter.url, use_selenium=False)
            pages = _extract(soup)
            if pages:
                return pages
            logger.debug(f"Requests path returned no images for {chapter.url}, retrying with Selenium")
        except Exception as e:
            logger.debug(f"Requests fetch failed for {chapter.url}: {e}")

        # Slow path: Selenium (handles JS redirects / age-gate)
        try:
            soup = self._get_soup(chapter.url, use_selenium=True)
            return _extract(soup)
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

    @staticmethod
    def _encode_url(url: str) -> str:
        """Percent-encode spaces and unsafe characters in a CDN URL path.

        ManhuaTo HTML sometimes has raw spaces in img src attributes like:
            https://cdn.manhuato.com/ My Series/chapter-1/1.jpg
        Python requests does NOT auto-encode spaces, so the CDN returns errors.
        This encodes only the path component, leaving scheme/host/query intact.
        """
        try:
            p = urlparse(url)
            encoded_path = quote(p.path, safe='/:@!$&()*+,;=~')
            return urlunparse(p._replace(path=encoded_path))
        except Exception:
            return url

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

    # Words that stay lowercase in title case (unless first word).
    _MINOR_WORDS = frozenset({
        'a', 'an', 'the',
        'and', 'but', 'or', 'nor', 'for', 'so', 'yet',
        'as', 'at', 'by', 'in', 'of', 'on', 'to', 'up', 'via',
        'with', 'from', 'into', 'onto', 'upon',
    })

    @classmethod
    def _title_case(cls, text: str) -> str:
        """Title-case that skips minor words and never capitalises after apostrophes.

        Python's str.title() has two bugs for our use case:
          "world's" → "World'S"   (wrong — capitalises the s after apostrophe)
          "and" / "a" → "And"/"A" (wrong — minor words should stay lowercase)
        """
        words = text.split()
        result = []
        for i, word in enumerate(words):
            lower = word.lower()
            if i == 0 or lower not in cls._MINOR_WORDS:
                result.append(word[0].upper() + word[1:] if word else word)
            else:
                result.append(lower)
        return ' '.join(result)

    @classmethod
    def _strip_type_suffix(cls, title: str) -> str:
        """Remove trailing type labels and normalize to consistent title case.

        ManhuaTo returns titles in inconsistent casing (e.g. "Return of the Mad
        Demon Manhwa" from the detail page vs "Return Of The Mad Demon Manhwa"
        from the listing page).  Stripping the suffix AND normalising case
        ensures both runs always produce the same directory/filename, preventing
        spurious re-downloads due to case-variant paths.
        """
        stripped = re.sub(
            r'\s+\b(Manhwa|Manhua|Manga|Comics)\b\s*$', '', title, flags=re.I
        ).strip()
        return cls._title_case(stripped)

    def _extract_title_from_soup(self, soup) -> str:
        """ManhuaTo-specific title extraction — strips type suffix."""
        title = super()._extract_title_from_soup(soup)
        if title:
            title = self._strip_type_suffix(title)
        return title

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
                        except Exception:
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

                            title = self._strip_type_suffix(title)
                            
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
                    
                    # Page limit (user-specified or safety cap)
                    if page > (self.max_pages or 200):
                        logger.warning(f"Reached page limit ({self.max_pages or 200}) for {category}")
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
                cookie_file = Path("manhuato_cookies.json")
                if cookie_file.exists():
                    try:
                        with open(cookie_file, 'r', encoding='utf-8') as f:
                            cookies = json.load(f)
                        self.driver.get("https://manhuato.com")
                        time.sleep(1)
                        for c in cookies:
                            try:
                                self.driver.add_cookie(c)
                            except Exception:
                                pass
                        logger.info(f"Loaded {len(cookies)} saved cookies")
                    except Exception as e:
                        logger.debug(f"Could not load saved cookies: {e}")

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
                except Exception:
                    pass

                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            pages = []
            
            # Find images - ONLY from cdn.manhuato.com (strict filter!)
            for img in soup.select('img'):
                # Try attributes in priority order; validate each candidate before
                # accepting it — ManhuaTo CDN URLs for series whose titles contain a
                # comma are truncated at the comma so the path starts with a space
                # (e.g. "/ Please Act Like a Final Boss/ch-1/1.jpeg"). After
                # percent-encoding that becomes "/%20Please..." which is a broken path
                # that returns 404. When we detect this, skip that attribute and try
                # the next one.
                src = None
                for attr in ('data-original', 'data-src', 'data-lazy-src', 'src'):
                    candidate = img.get(attr, '')
                    if not candidate or candidate.startswith('data:') or len(candidate) < 10:
                        continue

                    candidate = candidate.strip()

                    # Ensure full URL
                    if candidate.startswith('//'):
                        candidate = 'https:' + candidate
                    elif candidate.startswith('/'):
                        candidate = self.BASE_URL.rstrip('/') + candidate

                    # Only consider CDN images
                    if 'cdn.manhuato.com' not in candidate.lower():
                        continue

                    # Percent-encode spaces/special chars in the CDN path
                    candidate = self._encode_url(candidate)

                    # Detect truncated-at-comma CDN paths: after encoding, the first
                    # path segment after the host starts with %20 (a space). This
                    # means the real series directory is missing — skip this attribute
                    # and try the next one which may have the full URL.
                    if urlparse(candidate).path.startswith('/%20'):
                        logger.debug(
                            f"Skipping truncated CDN URL from {attr!r} "
                            f"(path starts with space): {candidate}"
                        )
                        continue

                    src = candidate
                    break

                if not src:
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

                    # Use the scraper's own session so FlareSolverr cookies and
                    # the matching User-Agent are sent to the CDN during probing.
                    session = self.session
                    session.headers.update({'Referer': chapter_url})
                    
                    # Find all images by enumeration (rate-limited to avoid CDN bans)
                    consecutive_failures = 0
                    current_num = 0
                    ENUM_DELAY = 0.3  # seconds between probes

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
                            except Exception:
                                consecutive_failures += 1
                            time.sleep(ENUM_DELAY)
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

    def _download_image(self, url: str, path: Path, referer: str) -> bool:
        """Download image using the FlareSolverr session cookies and matching UA.

        The base class hardcodes a generic User-Agent which cdn.manhuato.com
        rejects when it doesn't match the UA used during the Cloudflare challenge.
        We send only the Referer here and let the session supply the correct UA.
        """
        try:
            headers = {
                'Referer': referer,
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


class DrakeFullScraper(BaseSiteScraper):
    """Full site scraper for drakecomic.org"""

    BASE_URL = "https://drakecomic.org"
    SITE_NAME = "drake"
    CLOUDFLARE_SITE = True

    # ManhuaFast/Drake CDNs 504 under heavy parallel load — use fewer workers
    # than the base-class default (8) to avoid hammering the CDN.
    _DOWNLOAD_WORKERS = 4

    def __init__(self, headless: bool = True, limit: int = None, max_pages: int = None):
        super().__init__(headless=headless, limit=limit, max_pages=max_pages)
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

    def _extract_title_from_soup(self, soup) -> str:
        """Drake-specific title extraction.

        Drake uses the Madara / WP-manga WordPress theme.  The series title is
        in 'div.post-title h1' or 'h1.entry-title'.  og:title often contains a
        different (or alternate) translation and always has the site suffix, so
        we prefer the on-page H1 first, then fall back to the base class.
        """
        for selector in ('div.post-title h1', 'h1.entry-title',
                         '.manga-title h1', '.seriestuheader h1'):
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(separator=' ', strip=True)
                if text and len(text) > 2:
                    return text
        # Fall back to base class (tries og:title, then other h1 selectors)
        return super()._extract_title_from_soup(soup)

    def _extract_cover_from_soup(self, soup) -> str:
        """Drake-specific cover extraction.

        Drake's og:image is a promotional banner that includes their site
        branding header, not a clean cover thumbnail.  Use the Madara theme
        cover selectors directly instead; only fall back to og:image if no
        thumbnail is found.
        """
        for selector in ('.summary_image img', '.seriestuimg img',
                         '.thumb img', '[class*="thumb"] img',
                         '.manga-thumb img', '.comic-thumb img'):
            elem = soup.select_one(selector)
            if elem:
                raw = (elem.get('data-src') or elem.get('data-lazy-src')
                       or elem.get('src', ''))
                url = raw.strip()
                if url and url.startswith('http') and not url.endswith('.gif'):
                    return url
        # Fall back to base class (includes og:image as last resort)
        return super()._extract_cover_from_soup(soup)

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
                
                # Find series containers — try multiple WP manga theme selectors
                items = (
                    soup.select('div.bs') or           # Madara theme
                    soup.select('div.bsx') or           # Madara variant
                    soup.select('.listupd .bs') or
                    soup.select('.listupd article') or
                    soup.select('article.item') or
                    soup.select('div.utao') or
                    soup.select('li.el') or
                    # Last resort: any link to a /manga/ series page
                    soup.select('a[href*="/manga/"]:not([href*="chapter"])')
                )

                if not items:
                    logger.info(f"No series found on page {page} — dumping selectors for debug")
                    logger.debug(f"Page title: {soup.title.string if soup.title else 'none'}")
                    logger.debug(f"Body classes: {soup.body.get('class', []) if soup.body else []}")
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
                        # Require a non-empty slug after /manga/ — rejects the bare
                        # listing URL /manga/ and pagination links /manga/page/2/
                        if not re.search(r'/manga/[^/?#\s]+', href):
                            continue
                        if re.search(r'/manga/page/\d+', href):
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
                # Page limit (user-specified or safety cap)
                if page > (self.max_pages or 200):
                    logger.warning(f"Reached page limit ({self.max_pages or 200})")
                    break

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                break
        
        logger.info(f"Total series found: {len(all_series)}")
        return all_series
    
    def get_chapters(self, series: Series) -> List[Chapter]:
        soup = self._get_soup(series.url, use_selenium=True)

        # Bail out cleanly if the network returned a browser error page
        # instead of the real series page — returning [] skips downloading
        # rather than creating fake chapters from error page link text.
        if self._is_browser_error_page(soup):
            logger.warning(
                f"Browser error page for {series.url!r} — "
                f"returning 0 chapters for {series.title!r}"
            )
            return []

        chapters = []
        # Prefer specific Madara list containers; fall back to the broad
        # a[href*="chapter"] selector only as a last resort.  The '{' guard
        # below filters the JS template placeholder links (e.g.
        # /chapter/{{number}}/) that Drake injects for pagination scaffolding.
        for link in soup.select('#chapterlist li a, .eplister li a, a[href*="chapter"]'):
            href = link.get('href', '').strip()
            if not href:
                continue

            # Skip JS template placeholder URLs (e.g. /chapter/{{number}}/)
            if '{' in href:
                continue

            full_url = href if href.startswith('http') else self.BASE_URL + href

            # Only accept URLs that belong to this site — filters out Twitter share
            # buttons and other off-site links that contain "chapter" in their query params
            if not full_url.startswith(self.BASE_URL):
                continue

            num_elem = link.select_one('.chapternum, .epl-num, .epxs')
            text = num_elem.get_text(separator=' ', strip=True) if num_elem else link.get_text(separator=' ', strip=True)

            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href, re.I)
            if not match:
                match = re.search(r'(\d+(?:\.\d+)?)', text)
            if not match:
                # Can't determine chapter number — skip (avoids "Chapter " blank entries)
                continue
            num = match.group(1)

            # Avoid duplicates
            if not any(c.url == full_url for c in chapters):
                chapters.append(Chapter(
                    number=num,
                    title=text or f"Chapter {num}",
                    url=full_url
                ))

        chapters.sort(key=lambda c: float(c.number) if c.number.replace('.', '', 1).isdigit() else 0)
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

    @staticmethod
    def _normalize_page_url(url: str) -> str:
        """Normalise CDN proxy / template URLs to their direct source form.

        Handles three cases that cause download failures:

        1. Statically CDN proxy:
           ``cdn.statically.io/img/{host}/{path}`` → ``https://{host}/{path}``
           These return HTTP 400 when the origin is rate-limiting or the proxy
           quota is exhausted; the direct URL almost always works.

        2. Generic ``?url=`` proxy:
           ``some-domain.com/proxy?url=https://real.host/img.jpg``
           → ``https://real.host/img.jpg``
           Used by dead proxy domains (e.g. porn18comic.com) that no longer
           resolve.

        3. Unrendered JS template strings:
           URLs containing ``$object``, ``${``, or ``{{`` are JavaScript
           template literals that were never evaluated — discard them.

        Returns the normalised URL, or ``""`` to signal the caller to skip it.
        """
        from urllib.parse import urlparse, parse_qs, unquote
        # Filter unrendered JS template strings
        if '$object' in url or '${' in url or '{{' in url:
            return ''
        parsed = urlparse(url)
        # Statically CDN: cdn.statically.io/img/{host}/{path} → https://{host}/{path}
        if parsed.netloc == 'cdn.statically.io' and parsed.path.startswith('/img/'):
            remainder = parsed.path[5:]  # strip leading '/img/'
            parts = remainder.split('/', 1)
            if len(parts) == 2 and parts[0]:
                return f'https://{parts[0]}/{parts[1]}'
        # Generic proxy: ?url=https://... → extract original URL
        if parsed.query and 'url=' in parsed.query:
            qs = parse_qs(parsed.query, keep_blank_values=False)
            if 'url' in qs and qs['url']:
                return unquote(qs['url'][0])
        return url

    def _extract_drake_pages(self, soup: BeautifulSoup) -> List[str]:
        """Extract chapter image URLs from a parsed Drake chapter page.

        Filters out data: URIs (lazy-load placeholders), logo/icon URLs, and
        promotional banner images injected at the end by some Madara sites.
        A promotional image is detected when the last URL's hostname differs
        from the hostname used by all other chapter images.
        """
        pages = []
        # Madara/WP-manga theme: images live in .reading-content .page-break img.
        # Try selectors in specificity order; stop at the first one that yields.
        selectors = (
            '.reading-content .page-break img',
            '.reading-content img',
            '#readerarea img',
            '.chapter-content img',
            'img.ts-main-image',
            'img.wp-manga-chapter-img',
        )
        for selector in selectors:
            for img in soup.select(selector):
                src = img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
                src = src.strip()
                if not src or src.startswith('data:'):
                    continue
                if 'logo' in src.lower() or 'icon' in src.lower():
                    continue
                src = self._normalize_page_url(src)
                if not src:
                    continue
                if src not in pages:
                    pages.append(src)
            if pages:
                break

        # Drop promotional/banner images appended at the end by the site.
        # These are identified by having a different hostname from the rest of
        # the chapter images (e.g. an ad CDN vs the site's image CDN).
        if len(pages) >= 2:
            from urllib.parse import urlparse
            def _host(url):
                try:
                    return urlparse(url).netloc.lower()
                except Exception:
                    return ''
            # Find the dominant host (used by the majority of pages)
            hosts = [_host(p) for p in pages]
            majority_host = max(set(hosts), key=hosts.count)
            # If the last image is from a different host, it's a promo banner
            if hosts[-1] and hosts[-1] != majority_host:
                logger.debug(f"Dropping suspected promo image (host {hosts[-1]!r} != {majority_host!r}): {pages[-1]}")
                pages = pages[:-1]

        return pages

    def get_pages(self, chapter: Chapter) -> List[str]:
        # Drake chapter pages render images via JavaScript (wp-manga-reader.js
        # populates <img src> after page load).  A plain HTTP request — even
        # with valid Cloudflare clearance cookies — returns the shell HTML
        # without any image tags, so the cached-session fast path always fails.
        # Skip it entirely and go straight to FlareSolverr (full headless
        # Chromium that executes the JS) on the first attempt.
        #
        # We retry the full page fetch up to 3 times total.  On each attempt we
        # re-request via FlareSolverr/Selenium — if we get HTML but 0 images it
        # means the JS reader hasn't finished rendering yet, so waiting a bit
        # and fetching again usually resolves it.
        max_page_attempts = 3
        for page_attempt in range(max_page_attempts):
            if self._use_flaresolverr:
                last_err = None
                for attempt in range(3):
                    try:
                        html, cookies, user_agent = self._flaresolverr_get(chapter.url)
                        self._apply_flaresolverr_cookies(cookies, user_agent)
                        self._fs_cookies_applied = True
                        soup = BeautifulSoup(html, 'html.parser')
                        last_err = None
                        break
                    except Exception as e:
                        last_err = e
                        if attempt < 2:
                            wait = (attempt + 1) * 10
                            logger.warning(f"FlareSolverr failed for {chapter.url} (attempt {attempt+1}/3): {e} — retrying in {wait}s")
                            time.sleep(wait)
                if last_err:
                    logger.warning(f"FlareSolverr failed for {chapter.url} after 3 attempts: {last_err}")
                    return []
            else:
                # Non-ARM path: use Selenium with undetected-chromedriver
                soup = self._get_soup(chapter.url, use_selenium=True)
                self._sync_cookies_from_driver()

            pages = self._extract_drake_pages(soup)

            if pages:
                return pages

            # Got HTML but no images — JS reader may not have finished rendering.
            # Wait before re-fetching; skip retry on the last attempt.
            if page_attempt < max_page_attempts - 1:
                wait = 15 * (page_attempt + 1)
                logger.warning(
                    f"No images in rendered HTML for {chapter.url} "
                    f"(attempt {page_attempt + 1}/{max_page_attempts}) — "
                    f"retrying in {wait}s"
                )
                time.sleep(wait)

        logger.debug(f"No pages found for {chapter.url} after {max_page_attempts} attempts (likely paywalled)")
        return []

    def _extract_description_from_soup(self, soup) -> str:
        """Extract description for Madara/WP-manga theme sites.

        The base-class [class*="summary"] selector is too broad — it matches
        the page-level wrapper (.profile-manga.summary-layout-1) first, which
        contains the entire page and returns garbled text.  Try Madara-specific
        selectors first before falling back.
        """
        # Reset Scans uses a two-tab layout; the Summary tab panel is #nav-profile.
        # Standard Madara puts the synopsis text in .summary_content.
        for selector in ('#nav-profile', '.summary_content', '.post-content',
                         'div[itemprop="description"]'):
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(separator=' ', strip=True)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 50:
                    return text[:2000]
        return super()._extract_description_from_soup(soup)

    def _download_image(self, url: str, path: Path, referer: str) -> bool:
        """Download image using session with synced Cloudflare cookies and matching UA.

        Retries up to 3 times with short backoff for transient failures.
        Skips data: URIs (lazy-load placeholders that slipped through extraction).
        """
        if url.startswith('data:'):
            logger.debug(f"Skipping data: URI placeholder in page list")
            return False

        headers = {
            'Referer': referer,
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        }
        last_err = None
        for attempt in range(4):
            try:
                response = self.session.get(url, headers=headers, timeout=45)
                response.raise_for_status()
                if len(response.content) < 1000:
                    logger.warning(f"Image too small (<1 KB), likely promo/placeholder: {url}")
                    return False
                path.write_bytes(response.content)
                return True
            except Exception as e:
                last_err = e
                if attempt < 3:
                    # 5xx errors (504 Gateway Timeout, 503 Service Unavailable)
                    # mean the CDN is temporarily overloaded — back off longer so
                    # it has time to recover before the next attempt.
                    import requests as _req
                    is_5xx = (isinstance(e, _req.HTTPError) and
                              e.response is not None and
                              e.response.status_code >= 500)
                    wait = (15 * (attempt + 1)) if is_5xx else (3 * (attempt + 1))
                    time.sleep(wait)
        logger.warning(f"Failed to download image after 4 attempts: {url} — {last_err}")
        return False


class ManhuaFastScraper(DrakeFullScraper):
    """Full site scraper for manhuafast.net (Madara/WP-manga theme).

    ManhuaFast uses the standard Madara WordPress theme with WordPress-style
    pagination: /manga/page/N/ (NOT ?page=N which Drake uses).  The catalog
    is large (~64 pages), so proper multi-page scraping is required.

    Chapter list uses li.wp-manga-chapter (confirmed via Tachiyomi/Madara
    default) before falling back to the broader Drake selectors.

    og:image on ManhuaFast is a clean series cover (unlike Drake where it is
    a branded site banner), so we use the base class cover extractor which
    tries og:image first.
    """

    # .com and .net are the same site; .com is the canonical domain used by
    # Tachiyomi and has the full catalog (~152 pages vs ~64 on .net).
    BASE_URL = "https://manhuafast.com"
    SITE_NAME = "manhuafast"
    CLOUDFLARE_SITE = True

    def __init__(self, headless: bool = True, limit: int = None, max_pages: int = None):
        BaseSiteScraper.__init__(self, headless=headless, limit=limit, max_pages=max_pages)
        if not self._is_arm() and not self._use_flaresolverr:
            if headless:
                logger.info("ManhuaFast: switching to non-headless mode for Cloudflare bypass.")
            self.headless = False

    def _extract_cover_from_soup(self, soup) -> str:
        """ManhuaFast og:image is a clean cover — use base class logic (og:image first)."""
        return BaseSiteScraper._extract_cover_from_soup(self, soup)

    # Valid Madara sort keys and their human-readable names
    SORT_KEYS = {
        'latest':    'latest',
        'views':     'views',
        'trending':  'trending',
        'rating':    'rating',
        'az':        'alphabet',
        'alphabet':  'alphabet',
        'new':       'new-manga',
        'new-manga': 'new-manga',
    }

    def get_all_series(self, order_by: str = None) -> List[Series]:
        """Get all series using WordPress /manga/page/N/ pagination.

        ManhuaFast (and manhuafast.com) use the WordPress standard pagination
        format /manga/page/N/ rather than the ?page=N query-string format that
        Drake uses.  Using the wrong format returns page 1 on every request,
        so only the first ~18 series would ever be scraped.

        order_by: Madara sort key — one of latest, views, trending, rating,
                  alphabet/az, new.  Defaults to site default (latest).
        """
        sort_param = self.SORT_KEYS.get((order_by or '').lower().strip(), '')
        if order_by and not sort_param:
            logger.warning(f"Unknown sort key '{order_by}' — using site default. Valid: {', '.join(self.SORT_KEYS)}")
        if sort_param:
            logger.info(f"Fetching all series from ManhuaFast (sort={sort_param})...")
        else:
            logger.info("Fetching all series from ManhuaFast...")
        all_series = []
        page = 1

        while True:
            if page > 1:
                url = f"{self.BASE_URL}/manga/page/{page}/"
            else:
                url = f"{self.BASE_URL}/manga/"
            if sort_param:
                url += f"?m_orderby={sort_param}"
            logger.info(f"Fetching page {page}: {url}")

            try:
                soup = self._get_soup(url)

                items = (
                    soup.select('div.bs') or
                    soup.select('div.bsx') or
                    soup.select('.listupd .bs') or
                    soup.select('.listupd article') or
                    soup.select('article.item') or
                    soup.select('a[href*="/manga/"]:not([href*="chapter"])')
                )

                if not items:
                    logger.debug(f"Page title: {soup.title.string if soup.title else 'none'}")
                    logger.debug(f"Body classes: {soup.body.get('class', []) if soup.body else []}")
                    break

                found_count = 0
                for item in items:
                    try:
                        link = item.select_one('a[href*="/manga/"]') if item.name != 'a' else item
                        if not link:
                            continue
                        href = link.get('href', '').strip()
                        if not href or '/manga/' not in href:
                            continue
                        # Require a non-empty slug after /manga/ — rejects the bare
                        # listing URL /manga/ (the "Page 1" pagination link) as well
                        # as pagination sub-pages /manga/page/2/ and query-string
                        # category pages /manga/?m_orderby=views.
                        if not re.search(r'/manga/[^/?#\s]+', href):
                            continue
                        if re.search(r'/manga/page/\d+', href) or \
                                re.search(r'/manga/\?(genre|tag|type|status|m_orderby)', href):
                            continue

                        title = link.get('title', '')
                        if not title:
                            title_elem = item.select_one('div.tt, .title')
                            if title_elem:
                                title = title_elem.get_text(strip=True)
                        if not title or len(title) < 2:
                            continue

                        full_url = href if href.startswith('http') else self.BASE_URL + href
                        # Reject pagination/filter URLs after full_url is built
                        if re.search(r'/manga/page/\d+', full_url):
                            continue

                        genres = []
                        type_elem = item.select_one('span.type')
                        if type_elem:
                            genres.append(type_elem.get_text(strip=True))

                        rating = 0.0
                        rating_elem = item.select_one('div.rating')
                        if rating_elem:
                            m = re.search(r'(\d+\.?\d*)', rating_elem.get_text(strip=True))
                            if m:
                                rating = float(m.group(1))
                                if rating > 5:
                                    rating /= 2

                        if not any(s.url == full_url for s in all_series):
                            all_series.append(Series(
                                title=title,
                                url=full_url,
                                source=self.SITE_NAME,
                                genres=genres,
                                rating=round(rating, 2),
                            ))
                            found_count += 1
                            if self.limit and len(all_series) >= self.limit:
                                break
                    except Exception as e:
                        logger.debug(f"Error parsing item: {e}")

                if self.limit and len(all_series) >= self.limit:
                    break

                logger.info(f"Found {found_count} series on page {page}")
                if found_count == 0:
                    break

                page += 1
                if page > (self.max_pages or 200):
                    logger.warning(f"Reached page limit ({self.max_pages or 200})")
                    break

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                break

        logger.info(f"Total series found: {len(all_series)}")
        return all_series

    def _extract_ajax_nonce(self, soup: BeautifulSoup) -> str:
        """Extract the Madara AJAX nonce from the series page.

        Madara 3.x+ requires a nonce in the admin-ajax.php POST body.  It is
        embedded in the page via one of several patterns depending on the theme
        version:
          - data-nonce attribute on #manga-chapters-holder
          - JavaScript variable  wp_manga_ajax_nonce / manga_ajax_nonce
          - Inline JSON  {"manga_nonce":"<token>"} in a localized script block
        """
        holder = soup.select_one('#manga-chapters-holder[data-nonce]')
        if holder:
            return holder.get('data-nonce', '').strip()

        for script in soup.find_all('script'):
            text = script.get_text()
            for pat in (
                r'"manga_nonce"\s*:\s*"([^"]+)"',
                r'wp_manga_ajax_nonce\s*[=:]\s*["\']([^"\']+)["\']',
                r'manga_ajax_nonce\s*[=:]\s*["\']([^"\']+)["\']',
                r'"nonce"\s*:\s*"([a-f0-9]{8,})"',
            ):
                m = re.search(pat, text)
                if m:
                    return m.group(1).strip()
        return ''

    def _extract_manga_id(self, soup: BeautifulSoup) -> str:
        """Extract the WordPress post ID for the Madara AJAX chapter endpoint.

        Different Madara versions store this differently:
          - data-id on #manga-chapters-holder  (most common)
          - data-postid on the wrapper div
          - inline JavaScript variable
        """
        # Primary: data-id on the chapters holder div
        holder = soup.select_one('#manga-chapters-holder')
        if holder:
            manga_id = holder.get('data-id', '').strip()
            if manga_id and manga_id.isdigit():
                return manga_id

        # Fallback: data-postid on any element
        for el in soup.select('[data-postid]'):
            val = el.get('data-postid', '').strip()
            if val and val.isdigit():
                return val

        # Fallback: inline JavaScript variable
        for script in soup.find_all('script'):
            text = script.get_text()
            for pat in (
                r'["\']?manga["\']?\s*:\s*["\']?(\d+)["\']?',
                r'manga[_-]id["\']?\s*[=:]\s*["\']?(\d+)',
                r'var\s+post_id\s*=\s*(\d+)',
                r'"postid"\s*:\s*(\d+)',
            ):
                m = re.search(pat, text, re.I)
                if m:
                    return m.group(1)
        return ''

    def _fetch_chapters_ajax(self, series_url: str, soup: BeautifulSoup) -> str:
        """Fetch the full chapter list via Madara's AJAX endpoint.

        ManhuaFast (and most Madara sites) lazy-load the chapter list: the
        initial page HTML only contains the first ~16 chapters; the rest are
        loaded by JavaScript via:
          POST /wp-admin/admin-ajax.php
          action=manga_get_chapters&manga=<post_id>

        The post ID is stored in  <div id="manga-chapters-holder" data-id="…">.
        A nonce may also be required (Madara 3.x+).
        Returns the raw HTML of the chapter list on success, or "" on failure.
        """
        manga_id = self._extract_manga_id(soup)
        if not manga_id:
            logger.info(f"Could not extract manga ID for AJAX from {series_url} — skipping AJAX fetch")
            return ""

        nonce = self._extract_ajax_nonce(soup)
        logger.info(f"AJAX chapter fetch: manga_id={manga_id}, nonce={'found' if nonce else 'none'}, via={'FlareSolverr' if self._use_flaresolverr else 'requests'}")

        ajax_url = f"{self.BASE_URL}/wp-admin/admin-ajax.php"

        # ── FlareSolverr POST path (ARM / Cloudflare-protected sites) ─────────
        # Try FlareSolverr's request.post first.  Some FlareSolverr versions
        # don't support POST (they make a GET instead and WordPress returns "0").
        # If that happens, fall through to plain session.post — cf_clearance
        # is already applied to self.session from the series page GET, so the
        # same IP/UA combination should satisfy Cloudflare.
        if self._use_flaresolverr:
            post_data = f"action=manga_get_chapters&manga={manga_id}"
            if nonce:
                post_data += f"&nonce={nonce}"
            raw_cookies = getattr(self, '_last_fs_raw_cookies', [])
            try:
                html, _, _ = self._flaresolverr_post(
                    ajax_url, post_data, cookies=raw_cookies
                )
                html = html.strip()
                if html and html not in ('0', '-1') and 'wp-manga-chapter' in html:
                    logger.info(f"AJAX chapter fetch succeeded via FlareSolverr POST ({len(html)} chars)")
                    return html
                logger.info(f"FlareSolverr POST returned '{html[:40]}' — falling back to session.post")
            except Exception as e:
                logger.info(f"FlareSolverr POST failed ({e}) — falling back to session.post")
            # Fall through to plain session.post with cf_clearance cookies

        # Full browser-like headers — Cloudflare WAF checks Origin and Sec-Fetch-*
        ua = self.session.headers.get("User-Agent", "Mozilla/5.0")
        ajax_headers = {
            "Referer": series_url,
            "Origin": self.BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": ua,
        }

        # ── Try 1: POST to Madara's frontend chapter endpoint ─────────────────
        # /manga/{slug}/ajax/chapters/ is a frontend URL and typically NOT
        # subject to Cloudflare WAF rules that block /wp-admin/ access.
        frontend_url = series_url.rstrip('/') + '/ajax/chapters/'
        try:
            resp = self.session.post(
                frontend_url,
                data={"action": "manga_get_chapters"},
                headers=ajax_headers,
                timeout=30,
            )
            if resp.status_code == 200:
                resp.encoding = 'utf-8'
                text = resp.text.strip()
                if text and text not in ('0', '-1') and 'wp-manga-chapter' in text:
                    logger.info(f"AJAX chapter fetch succeeded via frontend endpoint ({len(text)} chars)")
                    return text
                logger.info(f"Frontend endpoint returned status=200 but invalid body ({text[:60]!r})")
            else:
                logger.info(f"Frontend endpoint returned HTTP {resp.status_code}")
        except Exception as e:
            logger.info(f"Frontend endpoint failed: {e}")

        # ── Try 2: POST to /wp-admin/admin-ajax.php with full browser headers ──
        # On ARM: cf_clearance from FlareSolverr is applied to self.session.
        # On x86: direct requests to the site (no Cloudflare challenge).
        payloads = []
        if nonce:
            payloads.append({"action": "manga_get_chapters", "manga": manga_id, "nonce": nonce})
        payloads.append({"action": "manga_get_chapters", "manga": manga_id})

        for payload in payloads:
            try:
                resp = self.session.post(ajax_url, data=payload, headers=ajax_headers, timeout=30)
                resp.raise_for_status()
                resp.encoding = 'utf-8'
                text = resp.text.strip()
                if text and text not in ('0', '-1') and 'wp-manga-chapter' in text:
                    logger.info(f"AJAX chapter fetch succeeded via session.post ({len(text)} chars)")
                    return text
                logger.info(f"session.post AJAX returned invalid body ({text[:60]!r})")
            except Exception as e:
                logger.warning(f"AJAX chapter fetch failed for {series_url}: {e}")
                break
        return ""

    def get_chapters(self, series: Series) -> List[Chapter]:
        """Get the full chapter list for a ManhuaFast series.

        Madara lazy-loads chapters: the initial HTML only contains the first
        batch (~16).  The complete list requires a POST to admin-ajax.php.

        Strategy:
        1. Fetch the series page (needed for the #manga-chapters-holder data-id).
        2. POST to admin-ajax.php to get the full chapter list HTML.
        3. Scope all selectors to the chapter list container to avoid
           contamination from sidebar "related series" chapter links.
        4. Fall back to the initial HTML if AJAX fails.
        5. Fall back to DrakeFullScraper if still nothing.
        """
        soup = self._get_soup(series.url, use_selenium=True)

        if self._is_browser_error_page(soup):
            logger.warning(
                f"Browser error page for {series.url!r} — "
                f"returning 0 chapters for {series.title!r}"
            )
            return []

        # URL-path filter: only accept chapters whose URL starts with the series
        # path, e.g. https://manhuafast.com/manga/solo-reincarnation/…
        # This is the definitive fix for sidebar contamination — sidebar links
        # point to entirely different series and will never start with series.url.
        series_path = series.url.rstrip('/').split('?')[0]

        def _parse_chapter_link(href: str, link) -> 'Chapter | None':
            if not href or '{' in href:
                return None
            full_url = href if href.startswith('http') else self.BASE_URL + href
            if not full_url.startswith(self.BASE_URL):
                return None
            # Reject chapters that belong to other series (sidebar widgets)
            if not full_url.startswith(series_path):
                return None
            text = link.get_text(separator=' ', strip=True)
            m = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href, re.I)
            if not m:
                m = re.search(r'(\d+(?:\.\d+)?)', text)
            if not m:
                return None
            num = m.group(1)
            return Chapter(number=num, title=text or f"Chapter {num}", url=full_url)

        def _parse_chapter_links(source_soup) -> List[Chapter]:
            found = []
            seen_urls: set = set()
            # Scope strictly to the chapter list container — never touch sidebar
            for container_sel in (
                '.listing-chapters_wrap',
                '#manga-chapters-holder',
                '.tab-summary',
            ):
                container = source_soup.select_one(container_sel)
                if container:
                    links = container.select('li.wp-manga-chapter a')
                    if links:
                        for link in links:
                            ch = _parse_chapter_link(link.get('href', '').strip(), link)
                            if ch and ch.url not in seen_urls:
                                seen_urls.add(ch.url)
                                found.append(ch)
                        if found:
                            break  # found a container with chapters — stop searching
            return found

        chapters: List[Chapter] = []

        # Primary path: AJAX full chapter list
        ajax_html = self._fetch_chapters_ajax(series.url, soup)
        if ajax_html:
            ajax_soup = BeautifulSoup(ajax_html, 'html.parser')
            chapters = _parse_chapter_links(ajax_soup)
            if not chapters:
                # AJAX HTML may itself be a flat list without the container wrapper
                seen_urls: set = set()
                for link in ajax_soup.select('li.wp-manga-chapter a'):
                    ch = _parse_chapter_link(link.get('href', '').strip(), link)
                    if ch and ch.url not in seen_urls:
                        seen_urls.add(ch.url)
                        chapters.append(ch)

        # Fallback: scoped selectors from the initial page HTML
        if not chapters:
            logger.debug("AJAX returned no chapters; falling back to initial HTML")
            chapters = _parse_chapter_links(soup)

        # Broad fallback: scan ALL links on the page but enforce the series_path
        # filter.  This catches chapter lists that use non-standard containers
        # (e.g. plain <ul> without .listing-chapters_wrap).  We still reject
        # chapters that belong to sidebar / "related series" widgets because
        # _parse_chapter_link filters by series_path.
        if not chapters:
            logger.debug("Scoped selectors returned no chapters; trying broad link scan with series-path filter")
            seen_urls: set = set()
            for link in soup.select('a[href*="chapter"]'):
                ch = _parse_chapter_link(link.get('href', '').strip(), link)
                if ch and ch.url not in seen_urls:
                    seen_urls.add(ch.url)
                    chapters.append(ch)

        if chapters:
            chapters.sort(key=lambda c: float(c.number) if c.number.replace('.', '', 1).isdigit() else 0)
            logger.info(f"  Found {len(chapters)} chapters")
            return chapters

        # Last resort: parent DrakeFullScraper (broad a[href*="chapter"] selector,
        # no series-path filter — may include sidebar chapters from other series).
        logger.debug("All ManhuaFast-specific strategies failed; delegating to DrakeFullScraper.get_chapters()")
        return super().get_chapters(series)


class ResetScansScraper(DrakeFullScraper):
    """Full site scraper for reset-scans.org (Madara/WP-manga theme).

    Reset Scans is a small scanlation group with a compact catalog (typically
    < 30 series).  All series are listed on a single /manga/ page — there is
    no URL-based pagination (?page=2, /page/2/ etc.).  The inherited
    get_all_series() handles this naturally: it scrapes /manga/ on the first
    pass, then on the second pass finds no new series (found_count == 0) and
    stops.

    Chapter list note: Tachiyomi's Madara class targets li.wp-manga-chapter
    elements.  This scraper adds that as the primary selector before the broader
    a[href*="chapter"] fallback used by DrakeFullScraper.
    """

    BASE_URL = "https://reset-scans.org"
    SITE_NAME = "resetscans"
    CLOUDFLARE_SITE = True

    def __init__(self, headless: bool = True, limit: int = None, max_pages: int = None):
        BaseSiteScraper.__init__(self, headless=headless, limit=limit, max_pages=max_pages)
        if not self._is_arm() and not self._use_flaresolverr:
            if headless:
                logger.info("Reset Scans: switching to non-headless mode for Cloudflare bypass.")
            self.headless = False

    # Inherit sort keys from ManhuaFastScraper (same Madara theme, same params)
    SORT_KEYS = ManhuaFastScraper.SORT_KEYS

    def _extract_cover_from_soup(self, soup) -> str:
        """Reset Scans og:image is a clean cover — use base class logic (og:image first)."""
        return BaseSiteScraper._extract_cover_from_soup(self, soup)

    def get_all_series(self, order_by: str = None, genre: str = None) -> List[Series]:
        """Get all series from Reset Scans, optionally filtered by genre(s) and/or sorted.

        Reset Scans uses /manga-genre/{slug}/ for genre browsing — a separate
        URL namespace from /manga/ (unlike most Madara sites that use query params).

          No genre:        https://reset-scans.org/manga/?m_orderby=views
          Single genre:    https://reset-scans.org/manga-genre/action/?m_orderby=views
          Multiple genres: fetches each genre URL and merges results (deduped by URL)

        order_by: views, trending, rating, latest, alphabet/az, new.
        genre: single slug or comma-separated slugs, e.g. "action" or "action,romance".
        """
        sort_param = self.SORT_KEYS.get((order_by or '').lower().strip(), '')
        if order_by and not sort_param:
            logger.warning(f"Unknown sort key '{order_by}' — using site default. Valid: {', '.join(self.SORT_KEYS)}")

        # Support comma-separated genres
        genre_slugs = [
            g.lower().strip().replace(' ', '-')
            for g in (genre or '').split(',')
            if g.strip()
        ]

        # Build list of URLs to fetch: one per genre, or /manga/ if no genre
        if genre_slugs:
            fetch_urls = [
                (f"{self.BASE_URL}/manga-genre/{slug}/" +
                 (f"?m_orderby={sort_param}" if sort_param else ""))
                for slug in genre_slugs
            ]
            log_suffix = f"genre={','.join(genre_slugs)}"
        else:
            base = f"{self.BASE_URL}/manga/"
            fetch_urls = [base + (f"?m_orderby={sort_param}" if sort_param else "")]
            log_suffix = ""

        if sort_param:
            log_suffix = f"{log_suffix + ', ' if log_suffix else ''}sort={sort_param}"

        if log_suffix:
            logger.info(f"Fetching all series from Reset Scans ({log_suffix})...")
        else:
            logger.info("Fetching all series from Reset Scans...")

        all_series = []
        seen_urls: set = set()

        for fetch_url in fetch_urls:
            soup = self._get_soup(fetch_url)
            items = (
                soup.select('div.bs') or
                soup.select('.listupd .bs') or
                soup.select('.listupd article') or
                soup.select('a[href*="/manga/"]:not([href*="chapter"])')
            )

            for item in items:
                try:
                    link = item.select_one('a[href*="/manga/"]') if item.name != 'a' else item
                    if not link:
                        continue
                    href = link.get('href', '').strip()
                    if not href or '/manga/' not in href:
                        continue
                    title = link.get('title', '')
                    if not title:
                        title_elem = item.select_one('div.tt, .title')
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                    if not title or len(title) < 2:
                        continue
                    full_url = href if href.startswith('http') else self.BASE_URL + href
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)
                    genres = []
                    type_elem = item.select_one('span.type')
                    if type_elem:
                        genres.append(type_elem.get_text(strip=True))
                    all_series.append(Series(
                        title=title,
                        url=full_url,
                        source=self.SITE_NAME,
                        genres=genres,
                    ))
                    if self.limit and len(all_series) >= self.limit:
                        break
                except Exception:
                    continue

            if self.limit and len(all_series) >= self.limit:
                break

        logger.info(f"Total series found: {len(all_series)}")
        return all_series

    def get_chapters(self, series: Series) -> List[Chapter]:
        """Get chapters using Madara's li.wp-manga-chapter selector first.

        Reset Scans uses the standard Madara chapter list markup:
          <ul class="main version-chap">
            <li class="wp-manga-chapter">
              <a href=".../chapter-01/">Chapter 1</a>
            </li>
          </ul>
        The inherited DrakeFullScraper.get_chapters() tries #chapterlist first
        which may not be present.  We try li.wp-manga-chapter directly, then
        fall back to the parent implementation if nothing is found.
        """
        soup = self._get_soup(series.url, use_selenium=True)

        if self._is_browser_error_page(soup):
            logger.warning(
                f"Browser error page for {series.url!r} — "
                f"returning 0 chapters for {series.title!r}"
            )
            return []

        # URL-path filter: reject sidebar links that belong to other series
        series_path = series.url.rstrip('/').split('?')[0]
        chapters = []
        seen_urls: set = set()

        # Primary: standard Madara chapter list
        for link in soup.select('li.wp-manga-chapter a, #chapterlist li a, .eplister li a'):
            href = link.get('href', '').strip()
            if not href or '{' in href:
                continue
            full_url = href if href.startswith('http') else self.BASE_URL + href
            if not full_url.startswith(self.BASE_URL):
                continue
            if not full_url.startswith(series_path):
                continue  # Sidebar link for a different series

            text = link.get_text(separator=' ', strip=True)
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href, re.I)
            if not match:
                match = re.search(r'(\d+(?:\.\d+)?)', text)
            if not match:
                continue
            num = match.group(1)

            if full_url not in seen_urls:
                seen_urls.add(full_url)
                chapters.append(Chapter(
                    number=num,
                    title=text or f"Chapter {num}",
                    url=full_url
                ))

        if chapters:
            chapters.reverse()
            return chapters

        # Fallback: let parent implementation try its broader selectors
        return super().get_chapters(series)


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
    'manhuafast': ManhuaFastScraper,
    'manhuafast.com': ManhuaFastScraper,
    'manhuafast.net': ManhuaFastScraper,
    'resetscans': ResetScansScraper,
    'reset-scans': ResetScansScraper,
    'reset-scans.org': ResetScansScraper,
}

# Primary sites (canonical names only, no aliases) - used for --site all
# Note: Drake is excluded due to captcha protection
PRIMARY_SITES = {
    'asura': AsuraFullScraper,
    'flame': FlameFullScraper,
    'manhuato': ManhuaToScraper,
    'webtoon': WebtoonScraper,
    'manhuafast': ManhuaFastScraper,
    'resetscans': ResetScansScraper,
}


def get_scraper(site: str, headless: bool = True, canvas: bool = False, limit: int = None, max_pages: int = None) -> BaseSiteScraper:
    """Get scraper instance by site name"""
    site_lower = site.lower()

    for key, scraper_class in SCRAPERS.items():
        if key in site_lower:
            # Special handling for Webtoon canvas option
            if scraper_class == WebtoonScraper:
                return scraper_class(headless=headless, canvas=canvas, limit=limit, max_pages=max_pages)
            return scraper_class(headless=headless, limit=limit, max_pages=max_pages)
    
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

  # ============================================
  # SORT ORDER (Madara sites: manhuafast, resetscans)
  # ============================================

  # Download the top-viewed ManhuaFast series (first 10 pages)
  python manhwa_scraper.py --site manhuafast --download-all --sort views --pages 10 -o ./library/Manhua

  # List Reset Scans series sorted by most views
  python manhwa_scraper.py --site resetscans --list-all --sort views -o resetscans.yaml

  # Download trending ManhuaFast series
  python manhwa_scraper.py --site manhuafast --download-all --sort trending --pages 5 -o ./library/Manhua

  # Valid sort values: latest (default), views, trending, rating, az, new
        """
    )
    
    parser.add_argument('--site', '-s', help='Site to scrape (asura, flame, drake, manhuato, webtoon, manhuafast, resetscans, or "all" for all sites)')
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
    parser.add_argument('--pages', type=int, help='Max browse pages per category (all paginated sites; Flame: max scroll rounds)')
    parser.add_argument('--canvas', action='store_true', help='For Webtoon: scrape CANVAS instead of ORIGINALS')
    parser.add_argument('--source-prefix', action='store_true', help='Prefix series folders with [Source] for multi-source comparison')
    parser.add_argument('--sort', help='Sort order for Madara sites (manhuafast, resetscans): views, trending, rating, latest, az, new')
    parser.add_argument('--genre', help='Genre filter for Reset Scans (e.g. action, romance, fantasy) — uses /manga-genre/{slug}/ URL format')
    
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
        
        scraper = get_scraper(args.site, headless, max_pages=getattr(args, 'pages', None))

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
        scraper = get_scraper(args.site, headless, canvas=args.canvas, limit=args.limit, max_pages=getattr(args, 'pages', None))
        filter_terms = [t.strip() for t in args.filter.split(',')] if args.filter else None
        sort_order = getattr(args, 'sort', None)
        genre_filter = getattr(args, 'genre', None)
        if isinstance(scraper, ManhuaToScraper) and filter_terms:
            series_list = scraper.get_all_series(genre_filter=filter_terms)
        elif isinstance(scraper, ResetScansScraper) and (sort_order or genre_filter):
            series_list = scraper.get_all_series(order_by=sort_order, genre=genre_filter)
        elif isinstance(scraper, ManhuaFastScraper) and sort_order:
            series_list = scraper.get_all_series(order_by=sort_order)
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
        scraper = get_scraper(args.site, headless, canvas=args.canvas, limit=args.limit, max_pages=getattr(args, 'pages', None))
        filter_terms = [t.strip() for t in args.filter.split(',')] if args.filter else None
        sort_order = getattr(args, 'sort', None)
        genre_filter = getattr(args, 'genre', None)
        if isinstance(scraper, ManhuaToScraper) and filter_terms:
            series_list = scraper.get_all_series(genre_filter=filter_terms)
        elif isinstance(scraper, ResetScansScraper) and (sort_order or genre_filter):
            series_list = scraper.get_all_series(order_by=sort_order, genre=genre_filter)
        elif isinstance(scraper, ManhuaFastScraper) and sort_order:
            series_list = scraper.get_all_series(order_by=sort_order)
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
                # Fetch full details if cover is missing or if we have no
                # description/rating yet.  cover_url is never populated by
                # get_all_series() on Drake (and some other scrapers), so we
                # must always hit the detail page at least once to get it.
                if not series.cover_url or (series.rating == 0.0 and not series.description):
                    series = scraper.get_series_details(series)
                
                # Reuse chapters pre-fetched inside get_series_details to
                # avoid making a duplicate network round-trip per series.
                cached = getattr(series, '_chapters_cache', None)
                if cached is not None:
                    chapters = cached
                    series._chapters_cache = None  # release memory
                else:
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
                
                # Scan the series directory once so per-chapter checks are O(1)
                # set lookups instead of individual stat() calls on the NFS mount.
                existing_cbzs = scraper._scan_series_dir(display_title, output_path)

                # Backfill missing cover — do this before the chapter loop so
                # it runs even when every chapter is already in the tracker
                # (download_chapter() returns early in that case and never
                # reaches the cover-download code).
                if series_for_meta.cover_url and series_for_meta.cover_url not in scraper._failed_cover_urls:
                    safe_title = scraper._sanitize_filename(display_title)
                    series_dir = output_path / safe_title
                    if series_dir.exists() and not list(series_dir.glob('cover.*')):
                        result = scraper._download_cover(
                            series_for_meta.cover_url, series_dir,
                            referer=series_for_meta.url)
                        if result is None:
                            scraper._failed_cover_urls.add(series_for_meta.cover_url)

                counts = {'new': 0, 'exists': 0, 'skip': 0, 'fail': 0}
                for chapter in chapters:
                    status = scraper.download_chapter(chapter, display_title, output_path, tracker, series_for_meta, existing_cbzs=existing_cbzs)
                    counts[status if status in counts else 'fail'] += 1

                # Flush tracker to disk once per series instead of once per chapter.
                # This turns O(N) disk writes per series into O(1).
                tracker.save()

                # Always log a per-series summary so silent skips are visible
                parts = []
                if counts['new']:
                    parts.append(f"{counts['new']} downloaded")
                if counts['exists']:
                    parts.append(f"{counts['exists']} found on disk")
                if counts['skip']:
                    parts.append(f"{counts['skip']} already up-to-date")
                if counts['fail']:
                    parts.append(f"{counts['fail']} failed/paywalled")
                logger.info(f"  Summary: {', '.join(parts) if parts else 'nothing to do'}")

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
            scraper = get_scraper(source, headless, max_pages=getattr(args, 'pages', None))
            
            for i, s in enumerate(series, 1):
                logger.info(f"[{i}/{len(series)}] Processing: {s.title}")
                
                try:
                    # Fetch full details for metadata if not already in config
                    if s.rating == 0.0 and not s.description:
                        s = scraper.get_series_details(s)
                    
                    chapters = scraper.get_chapters(s)
                    existing_cbzs = scraper._scan_series_dir(s.title, output_path)
                    for chapter in chapters:
                        scraper.download_chapter(chapter, s.title, output_path, tracker, s, existing_cbzs=existing_cbzs)
                    # Flush once per series (not once per chapter)
                    tracker.save()
                except Exception as e:
                    logger.error(f"Error: {e}")
            
            scraper._close_driver()
        
        logger.info("Download complete!")
        return
    
    parser.print_help()


if __name__ == '__main__':
    main()
