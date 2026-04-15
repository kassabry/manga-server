"""
Unit tests for ManhuaFastScraper and ResetScansScraper.

Covers:
  1. get_all_series() — parses Madara listing page HTML
  2. get_chapters()   — parses Madara series-detail page HTML
  3. get_pages()      — extracts image URLs from Madara chapter page (FlareSolverr path)
  4. download_chapter() — full pipeline: pages → images → CBZ (mocked network, temp dir)

No real HTTP calls are made.
"""
import os
import sys
import types
import zipfile
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

# ── Stub heavy optional deps so the import never fails without them ────────────
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

import selenium.webdriver.chrome.options as copt
copt.Options = type('Options', (), {'add_argument': lambda self, a: None,
                                     'add_experimental_option': lambda self, k, v: None})()

import webdriver_manager.chrome as wdm
wdm.ChromeDriverManager = type('C', (), {'install': lambda self: '/usr/bin/chromedriver'})

import undetected_chromedriver as uc_mod
uc_mod.ChromeOptions = copt.Options
uc_mod.Chrome = MagicMock()

import requests
import manhwa_scraper as ms
from bs4 import BeautifulSoup

# ── Helpers ───────────────────────────────────────────────────────────────────
PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results = []


def check(label, cond):
    status = PASS if cond else FAIL
    print(f"  [{status}] {label}")
    results.append(cond)


# ── Shared HTML fixtures ──────────────────────────────────────────────────────

# Madara listing page — two series cards (div.bs > a + div.tt)
LISTING_HTML = """
<div class="listupd">
  <div class="bs">
    <a href="/manga/hero-returns/" title="Hero Returns">
      <div class="bsx">
        <div class="tt">Hero Returns</div>
        <span class="type">Manhwa</span>
        <div class="rating">4.8</div>
      </div>
    </a>
  </div>
  <div class="bs">
    <a href="/manga/villain-academy/" title="Villain Academy">
      <div class="bsx">
        <div class="tt">Villain Academy</div>
        <span class="type">Manhua</span>
        <div class="rating">4.5</div>
      </div>
    </a>
  </div>
</div>
"""

# Madara series detail page — chapter list (standard #chapterlist, used by Drake/ManhuaFast)
SERIES_HTML = """
<div id="chapterlist">
  <li><a href="/manga/hero-returns/chapter-1/"><span class="chapternum">Chapter 1</span></a></li>
  <li><a href="/manga/hero-returns/chapter-2/"><span class="chapternum">Chapter 2</span></a></li>
  <li><a href="/manga/hero-returns/chapter-3/"><span class="chapternum">Chapter 3</span></a></li>
</ul>
"""

# Madara series detail page — li.wp-manga-chapter (Reset Scans / standard Madara)
SERIES_HTML_MADARA = """
<ul class="main version-chap no-volumn">
  <li class="wp-manga-chapter">
    <a href="https://reset-scans.org/manga/hero-returns/chapter-03/">Chapter 3</a>
  </li>
  <li class="wp-manga-chapter">
    <a href="https://reset-scans.org/manga/hero-returns/chapter-02/">Chapter 2</a>
  </li>
  <li class="wp-manga-chapter">
    <a href="https://reset-scans.org/manga/hero-returns/chapter-01/">Chapter 1</a>
  </li>
</ul>
"""

# Madara chapter page — reading-content with page-break images
CHAPTER_HTML = """
<div class="reading-content">
  <div class="page-break">
    <img data-src="https://cdn.manhuafast.net/uploads/hero-returns/ch1/001.jpg"
         class="wp-manga-chapter-img">
  </div>
  <div class="page-break">
    <img data-src="https://cdn.manhuafast.net/uploads/hero-returns/ch1/002.jpg"
         class="wp-manga-chapter-img">
  </div>
  <div class="page-break">
    <img data-src="https://cdn.manhuafast.net/uploads/hero-returns/ch1/003.jpg"
         class="wp-manga-chapter-img">
  </div>
</div>
"""

CHAPTER_HTML_RESET = CHAPTER_HTML.replace("manhuafast.net", "reset-scans.org")

# ManhuaFast series page: only the FIRST batch of chapters is in the HTML
# (sidebar has unrelated chapter links that must NOT be picked up).
# The full list comes from the AJAX endpoint.
SERIES_PAGE_MF_HTML = """
<div id="manga-chapters-holder" data-id="99999">
  <!-- only the latest 3 loaded in HTML; rest fetched via AJAX -->
  <ul class="main version-chap">
    <li class="wp-manga-chapter">
      <a href="https://manhuafast.com/manga/hero-returns/chapter-3/">Chapter 3</a>
    </li>
    <li class="wp-manga-chapter">
      <a href="https://manhuafast.com/manga/hero-returns/chapter-2/">Chapter 2</a>
    </li>
  </ul>
</div>
<!-- sidebar: MUST NOT be scraped -->
<div class="sidebar-widget">
  <li class="wp-manga-chapter">
    <a href="https://manhuafast.com/manga/other-series/chapter-592/">Chapter 592</a>
  </li>
  <li class="wp-manga-chapter">
    <a href="https://manhuafast.com/manga/other-series/chapter-264/">Chapter 264</a>
  </li>
</div>
"""

# AJAX response HTML: full flat list (no outer container wrapper)
AJAX_CHAPTERS_HTML = """
<ul class="main version-chap no-volumn">
  <li class="wp-manga-chapter">
    <a href="https://manhuafast.com/manga/hero-returns/chapter-90/">Chapter 90</a>
  </li>
  <li class="wp-manga-chapter">
    <a href="https://manhuafast.com/manga/hero-returns/chapter-2/">Chapter 2</a>
  </li>
  <li class="wp-manga-chapter">
    <a href="https://manhuafast.com/manga/hero-returns/chapter-1/">Chapter 1</a>
  </li>
</ul>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — ManhuaFastScraper
# ═══════════════════════════════════════════════════════════════════════════════

print("\n-- ManhuaFastScraper ----------------------------------------------------")

scraper_mf = ms.ManhuaFastScraper.__new__(ms.ManhuaFastScraper)
scraper_mf.session = requests.Session()
scraper_mf._use_flaresolverr = True
scraper_mf._fs_cookies_applied = False
scraper_mf._failed_cover_urls = set()
scraper_mf.headless = True
scraper_mf.driver = None
scraper_mf.limit = None
scraper_mf.max_pages = None
scraper_mf.BASE_URL = ms.ManhuaFastScraper.BASE_URL  # https://manhuafast.com
scraper_mf.SITE_NAME = ms.ManhuaFastScraper.SITE_NAME

# ── ManhuaFast fixtures ───────────────────────────────────────────────────────

# ManhuaFast uses li.wp-manga-chapter (standard Madara, confirmed by Tachiyomi extension)
SERIES_HTML_MF = """
<ul class="main version-chap no-volumn">
  <li class="wp-manga-chapter">
    <a href="https://manhuafast.com/manga/hero-returns/chapter-3/">Chapter 3</a>
  </li>
  <li class="wp-manga-chapter">
    <a href="https://manhuafast.com/manga/hero-returns/chapter-2/">Chapter 2</a>
  </li>
  <li class="wp-manga-chapter">
    <a href="https://manhuafast.com/manga/hero-returns/chapter-1/">Chapter 1</a>
  </li>
</ul>
"""

# ── Test 1: get_all_series — /manga/page/N/ pagination ───────────────────────
print("\nTest 1: ManhuaFastScraper.get_all_series() — /manga/page/N/ pagination")

listing_soup = BeautifulSoup(LISTING_HTML, 'html.parser')
empty_soup = BeautifulSoup("<html></html>", 'html.parser')

mf_urls_fetched = []

def mf_get_soup_side(url, use_selenium=False):
    mf_urls_fetched.append(url)
    # page 1 = real content, page 2 = empty
    if "/page/" in url:
        return empty_soup
    return listing_soup

with patch.object(scraper_mf, '_get_soup', side_effect=mf_get_soup_side), \
     patch.object(scraper_mf, '_delay'):
    series_list = scraper_mf.get_all_series()

check("returns 2 series", len(series_list) == 2)
check("first series title is 'Hero Returns'", series_list[0].title == "Hero Returns")
check("second series title is 'Villain Academy'", series_list[1].title == "Villain Academy")
check("series URLs point to manhuafast.com",
      all("manhuafast.com" in s.url for s in series_list))
check("source is 'manhuafast'", all(s.source == "manhuafast" for s in series_list))
check("page 1 URL is /manga/ (no /page/1/)",
      mf_urls_fetched[0] == "https://manhuafast.com/manga/")
check("page 2 URL uses /manga/page/2/ format (NOT ?page=2)",
      mf_urls_fetched[1] == "https://manhuafast.com/manga/page/2/")

series_mf = ms.Series(
    title="Hero Returns",
    url="https://manhuafast.com/manga/hero-returns/",
    source="manhuafast"
)

# ── Test 2: AJAX chapter fetch — full list, no sidebar contamination ──────────
print("\nTest 2: ManhuaFastScraper.get_chapters() — AJAX full list, sidebar ignored")

series_page_soup = BeautifulSoup(SERIES_PAGE_MF_HTML, 'html.parser')

with patch.object(scraper_mf, '_get_soup', return_value=series_page_soup), \
     patch.object(scraper_mf, '_fetch_chapters_ajax', return_value=AJAX_CHAPTERS_HTML), \
     patch.object(scraper_mf, '_delay'):
    chapters = scraper_mf.get_chapters(series_mf)

check("returns 3 chapters (full AJAX list, not the 2 from HTML)", len(chapters) == 3)
check("chapter 90 is present (full AJAX list)", any(c.number == "90" for c in chapters))
check("chapter 592 is NOT present (sidebar filtered out)",
      not any(c.number == "592" for c in chapters))
check("chapter 264 is NOT present (sidebar filtered out)",
      not any(c.number == "264" for c in chapters))
check("chapters are in ascending order",
      chapters[0].number == "1" and chapters[-1].number == "90")
check("chapter URLs all contain manhuafast.com",
      all("manhuafast.com" in c.url for c in chapters))

# ── Test 2b: AJAX fails — fall back to scoped initial HTML (no sidebar) ───────
print("\nTest 2b: ManhuaFastScraper.get_chapters() — AJAX fails, scoped HTML fallback")

with patch.object(scraper_mf, '_get_soup', return_value=series_page_soup), \
     patch.object(scraper_mf, '_fetch_chapters_ajax', return_value=""), \
     patch.object(scraper_mf, '_delay'):
    chapters_fb = scraper_mf.get_chapters(series_mf)

check("fallback finds 2 chapters from scoped HTML", len(chapters_fb) == 2)
check("chapter 592 still not present (sidebar scoping works even without AJAX)",
      not any(c.number == "592" for c in chapters_fb))
check("chapter 264 still not present",
      not any(c.number == "264" for c in chapters_fb))

# ── Test 2c: get_chapters — li.wp-manga-chapter in initial HTML (no AJAX) ─────
print("\nTest 2c: ManhuaFastScraper.get_chapters() — li.wp-manga-chapter in HTML")

mf_series_soup = BeautifulSoup(SERIES_HTML_MF, 'html.parser')

with patch.object(scraper_mf, '_get_soup', return_value=mf_series_soup), \
     patch.object(scraper_mf, '_fetch_chapters_ajax', return_value=""), \
     patch.object(scraper_mf, '_delay'):
    chapters_html = scraper_mf.get_chapters(series_mf)

check("returns 3 chapters from plain HTML", len(chapters_html) == 3)
check("chapters have numbers 1, 2, 3",
      {c.number for c in chapters_html} == {"1", "2", "3"})

# ── Test 3: get_pages (FlareSolverr path) ─────────────────────────────────────
print("\nTest 3: ManhuaFastScraper.get_pages() — Madara chapter images via FlareSolverr")

chapter_mf = ms.Chapter(
    number="1",
    title="Chapter 1",
    url="https://manhuafast.com/manga/hero-returns/chapter-1/"
)

with patch.object(scraper_mf, '_flaresolverr_get',
                  return_value=(CHAPTER_HTML, [], "TestUA")) as mock_fs, \
     patch.object(scraper_mf, '_apply_flaresolverr_cookies'), \
     patch.object(scraper_mf, '_delay'):
    pages = scraper_mf.get_pages(chapter_mf)

check("FlareSolverr called once", mock_fs.call_count == 1)
check("returns 3 page URLs", len(pages) == 3)
check("page URLs are CDN image URLs",
      all("cdn.manhuafast" in p for p in pages))
check("pages ordered 001, 002, 003",
      pages[0].endswith("001.jpg") and pages[2].endswith("003.jpg"))

# ── Test 4: download_chapter — full pipeline ──────────────────────────────────
print("\nTest 4: ManhuaFastScraper.download_chapter() — full CBZ pipeline (mocked)")

FAKE_IMAGE = b'\xff\xd8\xff\xe0' + b'\x00' * 2000  # minimal fake JPEG (>1000 bytes)


def fake_download_image(url, path, referer):
    path.write_bytes(FAKE_IMAGE)
    return True


with tempfile.TemporaryDirectory() as tmpdir:
    output_dir = Path(tmpdir)
    cache_file = output_dir / '.download_progress.pkl'
    tracker = ms.ProgressTracker(cache_file)

    series_for_dl = ms.Series(
        title="Hero Returns",
        url="https://manhuafast.com/manga/hero-returns/",
        source="manhuafast",
        chapters_count=3,
    )
    chapter_for_dl = ms.Chapter(
        number="1",
        title="Chapter 1",
        url="https://manhuafast.com/manga/hero-returns/chapter-1/"
    )

    fake_pages = [
        "https://cdn.manhuafast.com/uploads/hero-returns/ch1/001.jpg",
        "https://cdn.manhuafast.com/uploads/hero-returns/ch1/002.jpg",
        "https://cdn.manhuafast.com/uploads/hero-returns/ch1/003.jpg",
    ]

    with patch.object(scraper_mf, 'get_pages', return_value=fake_pages), \
         patch.object(scraper_mf, '_download_image', side_effect=fake_download_image), \
         patch.object(scraper_mf, '_download_cover', return_value=None):
        result = scraper_mf.download_chapter(
            chapter_for_dl, series_for_dl.title, output_dir, tracker, series_for_dl
        )

    cbz_path = output_dir / "Hero Returns" / "Hero Returns - Chapter 1.cbz"
    check("download_chapter returns 'new'", result == 'new')
    check("CBZ file created on disk", cbz_path.exists())

    if cbz_path.exists():
        with zipfile.ZipFile(cbz_path) as zf:
            names = zf.namelist()
        check("CBZ contains 3 image files",
              sum(1 for n in names if n.endswith('.jpg')) == 3)
        check("CBZ contains ComicInfo.xml", "ComicInfo.xml" in names)

        # Verify ComicInfo.xml has correct series name
        with zipfile.ZipFile(cbz_path) as zf:
            comic_info = zf.read("ComicInfo.xml").decode("utf-8")
        check("ComicInfo.xml has correct series title",
              "<Series>Hero Returns</Series>" in comic_info)
        check("ComicInfo.xml has chapter number 1",
              "<Number>1</Number>" in comic_info)
        check("ComicInfo.xml has ManhuaFast publisher",
              "ManhuaFast" in comic_info)

    # Second call should skip (already in tracker)
    with patch.object(scraper_mf, 'get_pages', return_value=fake_pages), \
         patch.object(scraper_mf, '_download_image', side_effect=fake_download_image), \
         patch.object(scraper_mf, '_download_cover', return_value=None):
        result2 = scraper_mf.download_chapter(
            chapter_for_dl, series_for_dl.title, output_dir, tracker, series_for_dl
        )
    check("second call is skipped (already downloaded)", result2 in ('skip', 'exists'))


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — ResetScansScraper
# ═══════════════════════════════════════════════════════════════════════════════

print("\n-- ResetScansScraper ----------------------------------------------------")

scraper_rs = ms.ResetScansScraper.__new__(ms.ResetScansScraper)
scraper_rs.session = requests.Session()
scraper_rs._use_flaresolverr = True
scraper_rs._fs_cookies_applied = False
scraper_rs._failed_cover_urls = set()
scraper_rs.headless = True
scraper_rs.driver = None
scraper_rs.limit = None
scraper_rs.max_pages = None
scraper_rs.BASE_URL = ms.ResetScansScraper.BASE_URL
scraper_rs.SITE_NAME = ms.ResetScansScraper.SITE_NAME

LISTING_HTML_RS = LISTING_HTML.replace(
    'href="/manga/hero-returns/"', 'href="/manga/hero-returns/"'
)  # same structure, base URL changes automatically via BASE_URL

# ── Test 5: get_all_series — single-page catalog (no pagination) ──────────────
print("\nTest 5: ResetScansScraper.get_all_series() — single-page catalog, stops cleanly")

# Reset Scans is a small scanlation group: all series on one page.
# Page 1 returns the real content; page 2 returns the same content (Madara
# default for out-of-range pages on small installs) — the scraper must stop
# because found_count == 0 (all URLs already seen).
rs_listing_soup = BeautifulSoup(LISTING_HTML, 'html.parser')

call_count = [0]
def rs_get_soup_side_effect(url, use_selenium=False):
    call_count[0] += 1
    return rs_listing_soup  # always returns the same page (simulates Madara repeating page 1)

with patch.object(scraper_rs, '_get_soup', side_effect=rs_get_soup_side_effect), \
     patch.object(scraper_rs, '_delay'):
    rs_series = scraper_rs.get_all_series()

check("returns 2 series (not doubled)", len(rs_series) == 2)
check("first series title is 'Hero Returns'", rs_series[0].title == "Hero Returns")
check("series URLs point to reset-scans.org",
      all("reset-scans.org" in s.url for s in rs_series))
check("source is 'resetscans'", all(s.source == "resetscans" for s in rs_series))
check("scraper stopped after duplicate page (no infinite loop)",
      call_count[0] == 2)  # page 1 (real) + page 2 (duplicate) → stop

# ── Test 6: get_chapters — li.wp-manga-chapter (standard Madara, no #chapterlist) ─
print("\nTest 6: ResetScansScraper.get_chapters() — li.wp-manga-chapter selector")

series_rs = ms.Series(
    title="Hero Returns",
    url="https://reset-scans.org/manga/hero-returns/",
    source="resetscans"
)
rs_madara_soup = BeautifulSoup(SERIES_HTML_MADARA, 'html.parser')

with patch.object(scraper_rs, '_get_soup', return_value=rs_madara_soup), \
     patch.object(scraper_rs, '_delay'):
    rs_chapters = scraper_rs.get_chapters(series_rs)

check("returns 3 chapters via li.wp-manga-chapter", len(rs_chapters) == 3)
check("chapters have numbers 01, 02, 03",
      {c.number for c in rs_chapters} == {"01", "02", "03"})
check("chapters are in ascending order (oldest first)",
      rs_chapters[0].number == "01" and rs_chapters[-1].number == "03")
check("chapter URLs point to reset-scans.org",
      all("reset-scans.org" in c.url for c in rs_chapters))

# ── Test 6b: get_chapters — fallback to parent when no li.wp-manga-chapter ────
print("\nTest 6b: ResetScansScraper.get_chapters() — fallback to #chapterlist")

rs_fallback_soup = BeautifulSoup(SERIES_HTML, 'html.parser')

with patch.object(scraper_rs, '_get_soup', return_value=rs_fallback_soup), \
     patch.object(scraper_rs, '_delay'):
    rs_chapters_fb = scraper_rs.get_chapters(series_rs)

check("fallback returns 3 chapters", len(rs_chapters_fb) == 3)
check("fallback chapters have numbers 1, 2, 3",
      {c.number for c in rs_chapters_fb} == {"1", "2", "3"})

# ── Test 7: get_pages (FlareSolverr path) ─────────────────────────────────────
print("\nTest 7: ResetScansScraper.get_pages() — Madara chapter images via FlareSolverr")

chapter_rs = ms.Chapter(
    number="1",
    title="Chapter 1",
    url="https://reset-scans.org/manga/hero-returns/chapter-1/"
)

with patch.object(scraper_rs, '_flaresolverr_get',
                  return_value=(CHAPTER_HTML_RESET, [], "TestUA")) as mock_rs_fs, \
     patch.object(scraper_rs, '_apply_flaresolverr_cookies'), \
     patch.object(scraper_rs, '_delay'):
    rs_pages = scraper_rs.get_pages(chapter_rs)

check("FlareSolverr called once", mock_rs_fs.call_count == 1)
check("returns 3 page URLs", len(rs_pages) == 3)
check("page URLs are CDN image URLs",
      all("reset-scans.org" in p for p in rs_pages))

# ── Test 8: download_chapter — full pipeline (Reset Scans) ───────────────────
print("\nTest 8: ResetScansScraper.download_chapter() — full CBZ pipeline (mocked)")

with tempfile.TemporaryDirectory() as tmpdir2:
    output_dir2 = Path(tmpdir2)
    cache_file2 = output_dir2 / '.download_progress.pkl'
    tracker2 = ms.ProgressTracker(cache_file2)

    series_rs_dl = ms.Series(
        title="Hero Returns",
        url="https://reset-scans.org/manga/hero-returns/",
        source="resetscans",
        chapters_count=3,
    )
    chapter_rs_dl = ms.Chapter(
        number="1",
        title="Chapter 1",
        url="https://reset-scans.org/manga/hero-returns/chapter-1/"
    )

    fake_pages_rs = [
        "https://cdn.reset-scans.org/uploads/hero-returns/ch1/001.jpg",
        "https://cdn.reset-scans.org/uploads/hero-returns/ch1/002.jpg",
        "https://cdn.reset-scans.org/uploads/hero-returns/ch1/003.jpg",
    ]

    with patch.object(scraper_rs, 'get_pages', return_value=fake_pages_rs), \
         patch.object(scraper_rs, '_download_image', side_effect=fake_download_image), \
         patch.object(scraper_rs, '_download_cover', return_value=None):
        rs_result = scraper_rs.download_chapter(
            chapter_rs_dl, series_rs_dl.title, output_dir2, tracker2, series_rs_dl
        )

    rs_cbz = output_dir2 / "Hero Returns" / "Hero Returns - Chapter 1.cbz"
    check("download_chapter returns 'new'", rs_result == 'new')
    check("CBZ file created on disk", rs_cbz.exists())

    if rs_cbz.exists():
        with zipfile.ZipFile(rs_cbz) as zf:
            rs_names = zf.namelist()
        check("CBZ contains 3 image files",
              sum(1 for n in rs_names if n.endswith('.jpg')) == 3)
        check("CBZ contains ComicInfo.xml", "ComicInfo.xml" in rs_names)

        with zipfile.ZipFile(rs_cbz) as zf:
            rs_comic_info = zf.read("ComicInfo.xml").decode("utf-8")
        check("ComicInfo.xml has correct series title",
              "<Series>Hero Returns</Series>" in rs_comic_info)
        check("ComicInfo.xml has Reset Scans publisher",
              "Reset Scans" in rs_comic_info)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — Registry smoke-tests
# ═══════════════════════════════════════════════════════════════════════════════

print("\n-- Registry -------------------------------------------------------------")

print("\nTest 9: get_scraper() resolves all name aliases")

for alias in ('manhuafast', 'manhuafast.com', 'manhuafast.net'):
    s = ms.get_scraper(alias)
    check(f"get_scraper('{alias}') -> ManhuaFastScraper",
          isinstance(s, ms.ManhuaFastScraper))
    s._close_driver()

for alias in ('resetscans', 'reset-scans', 'reset-scans.org'):
    s = ms.get_scraper(alias)
    check(f"get_scraper('{alias}') -> ResetScansScraper",
          isinstance(s, ms.ResetScansScraper))
    s._close_driver()

print("\nTest 10: both sites present in PRIMARY_SITES")
check("'manhuafast' in PRIMARY_SITES", 'manhuafast' in ms.PRIMARY_SITES)
check("'resetscans' in PRIMARY_SITES", 'resetscans' in ms.PRIMARY_SITES)


# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
total = len(results)
passed = sum(results)
print(f"Results: {passed}/{total} passed")
if passed == total:
    print("\033[32mAll tests passed.\033[0m")
    sys.exit(0)
else:
    print(f"\033[31m{total - passed} test(s) FAILED.\033[0m")
    sys.exit(1)
