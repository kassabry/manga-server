"""
Focused tests for the two code changes made to manhwa_scraper.py:
  1. DrakeFullScraper.get_pages() now calls _flaresolverr_get() directly (no cached-session attempt)
  2. BaseSiteScraper._get_soup() now returns empty BS rather than crashing when
     FlareSolverr fails and self.driver is None
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
import types, requests

# Stub heavy optional deps so the import doesn't require them installed
for mod in (
    'selenium', 'selenium.webdriver', 'selenium.webdriver.chrome',
    'selenium.webdriver.chrome.options', 'selenium.webdriver.chrome.service',
    'selenium.webdriver.common', 'selenium.webdriver.common.by',
    'selenium.webdriver.support', 'selenium.webdriver.support.ui',
    'selenium.webdriver.support.expected_conditions',
    'webdriver_manager', 'webdriver_manager.chrome',
    'undetected_chromedriver',
):
    sys.modules.setdefault(mod, types.ModuleType(mod))

# Minimal class stubs
import selenium.webdriver.chrome.options as copt
copt.Options = type('Options', (), {'add_argument': lambda self, a: None})()

import webdriver_manager.chrome as wdm
wdm.ChromeDriverManager = type('C', (), {'install': lambda self: '/usr/bin/chromedriver'})

import undetected_chromedriver as uc_mod
uc_mod.ChromeOptions = copt.Options
uc_mod.Chrome = MagicMock()

import manhwa_scraper as ms  # noqa: E402 — must come after stubs

# ── helpers ──────────────────────────────────────────────────────────────────
PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results = []

def check(label, cond):
    status = PASS if cond else FAIL
    print(f"  [{status}] {label}")
    results.append(cond)

# ── Test 1: _extract_drake_pages with .reading-content .page-break img ───────
print("\nTest 1: _extract_drake_pages — .reading-content .page-break img")
scraper = ms.DrakeFullScraper.__new__(ms.DrakeFullScraper)

html = """
<div class="reading-content">
  <div class="page-break">
    <img data-src="https://cdn.drakecomic.org/images/ch1/001.jpg" class="wp-manga-chapter-img">
  </div>
  <div class="page-break">
    <img data-src="https://cdn.drakecomic.org/images/ch1/002.jpg" class="wp-manga-chapter-img">
  </div>
</div>
"""
soup = BeautifulSoup(html, 'html.parser')
pages = scraper._extract_drake_pages(soup)
check("finds 2 pages via .reading-content .page-break img", len(pages) == 2)
check("first page URL correct", pages[0] == "https://cdn.drakecomic.org/images/ch1/001.jpg")

# ── Test 2: _extract_drake_pages with data-lazy-src ──────────────────────────
print("\nTest 2: _extract_drake_pages — data-lazy-src attribute")
html2 = """
<div class="reading-content">
  <div class="page-break">
    <img data-lazy-src="https://cdn.drakecomic.org/lazy/001.jpg">
  </div>
</div>
"""
soup2 = BeautifulSoup(html2, 'html.parser')
pages2 = scraper._extract_drake_pages(soup2)
check("picks up data-lazy-src", len(pages2) == 1)
check("URL is correct", pages2[0] == "https://cdn.drakecomic.org/lazy/001.jpg")

# ── Test 3: _extract_drake_pages — shell HTML (no images) → [] ───────────────
print("\nTest 3: _extract_drake_pages — shell HTML returns []")
html3 = "<div class='reading-content'><div class='page-break'></div></div>"
soup3 = BeautifulSoup(html3, 'html.parser')
check("empty reading-content returns []", scraper._extract_drake_pages(soup3) == [])

# ── Test 4: _extract_drake_pages — logo/icon URLs are filtered out ───────────
print("\nTest 4: _extract_drake_pages — logo and icon URLs excluded")
html4 = """
<div class="reading-content">
  <div class="page-break">
    <img data-src="https://cdn.drakecomic.org/logo.png">
    <img data-src="https://cdn.drakecomic.org/favicon-icon.png">
    <img data-src="https://cdn.drakecomic.org/real-page-001.jpg">
  </div>
</div>
"""
soup4 = BeautifulSoup(html4, 'html.parser')
pages4 = scraper._extract_drake_pages(soup4)
check("only real page included (logo/icon excluded)", len(pages4) == 1)
check("kept the real page URL", pages4[0] == "https://cdn.drakecomic.org/real-page-001.jpg")

# ── Test 5: get_pages FlareSolverr path — success ────────────────────────────
print("\nTest 5: get_pages() in FlareSolverr mode — success")

good_html = """
<div class="reading-content">
  <div class="page-break"><img data-src="https://cdn.drakecomic.org/img/001.jpg"></div>
  <div class="page-break"><img data-src="https://cdn.drakecomic.org/img/002.jpg"></div>
</div>
"""

scraper2 = ms.DrakeFullScraper.__new__(ms.DrakeFullScraper)
scraper2._use_flaresolverr = True
scraper2._fs_cookies_applied = True  # simulate already having cached cookies

chapter = ms.Chapter(number="1", title="Chapter 1",
                     url="https://drakecomic.org/test-chapter-1/")

with patch.object(scraper2, '_flaresolverr_get', return_value=(good_html, [], "TestUA")) as mock_fs, \
     patch.object(scraper2, '_apply_flaresolverr_cookies') as mock_apply:
    pages5 = scraper2.get_pages(chapter)

check("_flaresolverr_get called ONCE — no wasted cached-session attempt", mock_fs.call_count == 1)
check("called with correct chapter URL", mock_fs.call_args[0][0] == chapter.url)
check("returns 2 pages", len(pages5) == 2)
check("_fs_cookies_applied still True after success", scraper2._fs_cookies_applied is True)

# ── Test 6: get_pages FlareSolverr path — FlareSolverr failure → [] ──────────
print("\nTest 6: get_pages() in FlareSolverr mode — FlareSolverr failure returns []")

scraper3 = ms.DrakeFullScraper.__new__(ms.DrakeFullScraper)
scraper3._use_flaresolverr = True
scraper3._fs_cookies_applied = False

with patch.object(scraper3, '_flaresolverr_get', side_effect=RuntimeError("FlareSolverr down")):
    pages6 = scraper3.get_pages(chapter)

check("returns [] when FlareSolverr throws", pages6 == [])

# ── Test 7: _get_soup — FlareSolverr failure + None driver → empty BS, no crash
print("\nTest 7: _get_soup() -- FlareSolverr failure with driver=None -> empty BS (no crash)")

base = ms.BaseSiteScraper.__new__(ms.BaseSiteScraper)
base.session = requests.Session()
base._use_flaresolverr = True
base._fs_cookies_applied = False
base.driver = None
base._delay = lambda: None

with patch.object(base, '_flaresolverr_get', side_effect=RuntimeError("Timeout")), \
     patch.object(base, '_is_cloudflare_challenge', return_value=False):
    result = base._get_soup("https://drakecomic.org/test/", use_selenium=True)

check("returns BeautifulSoup instance (not None)", isinstance(result, BeautifulSoup))
check("no AttributeError crash when driver is None", True)  # survived to here

# ── Test 8: get_chapters — {{number}} template links are filtered ─────────────
print("\nTest 8: get_chapters() — JS template placeholder {{number}} links excluded")

scraper8 = ms.DrakeFullScraper.__new__(ms.DrakeFullScraper)
scraper8._use_flaresolverr = True
scraper8._fs_cookies_applied = True
scraper8.BASE_URL = "https://drakecomic.org"

chapter_list_html = """
<ul id="chapterlist">
  <li><a href="/beast-evolution-chapter-1/"><span class="chapternum">Chapter 1</span></a></li>
  <li><a href="/beast-evolution-chapter-2/"><span class="chapternum">Chapter 2</span></a></li>
  <li><a href="/beast-evolution-chapter-{{number}}/"><span class="chapternum">Chapter {{number}}</span></a></li>
</ul>
"""
ch_soup = BeautifulSoup(chapter_list_html, 'html.parser')

series = ms.Series(title="Beast Evolution", url="https://drakecomic.org/manga/beast-evolution/",
                   source="drake")

with patch.object(scraper8, '_get_soup', return_value=ch_soup):
    chapters8 = scraper8.get_chapters(series)

check("only real chapters returned ({{number}} filtered)", len(chapters8) == 2)
check("chapter 1 present", any(c.number == "1" for c in chapters8))
check("chapter 2 present", any(c.number == "2" for c in chapters8))
check("no chapter with '{{number}}' in number", not any('{{' in str(c.number) for c in chapters8))

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
total = len(results)
passed = sum(results)
print(f"Results: {passed}/{total} passed")
if passed == total:
    print("\033[32mAll tests passed.\033[0m")
    sys.exit(0)
else:
    print(f"\033[31m{total - passed} test(s) FAILED.\033[0m")
    sys.exit(1)
