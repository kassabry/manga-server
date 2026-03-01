#!/usr/bin/env python3
"""
fetch_covers.py - Download proper cover art for existing series

Visits the source site for each series (using the URL stored in ComicInfo.xml),
extracts the cover image, and saves it to the series folder as cover.jpg.
The ORVault scanner will then use this instead of the first page of chapter 1.

Uses FlareSolverr (if available) to bypass Cloudflare protection on sites like Asura.

Usage:
    python fetch_covers.py /path/to/library/Manhwa
    python fetch_covers.py /path/to/library/Manhwa --dry-run
    python fetch_covers.py /path/to/library/Manhwa --force  # re-download even if cover exists
"""

import os
import re
import sys
import zipfile
import logging
import time
import random
from pathlib import Path
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Sites that need FlareSolverr due to Cloudflare / JS rendering
CLOUDFLARE_DOMAINS = ['asuracomic', 'drakecomic', 'manhuato', 'flamecomics']


def get_flaresolverr_url():
    """Get FlareSolverr URL from env or default"""
    return os.environ.get('FLARESOLVERR_URL', 'http://localhost:8191')


def flaresolverr_available():
    """Check if FlareSolverr is running"""
    try:
        resp = requests.get(get_flaresolverr_url(), timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def flaresolverr_get(url, max_timeout=60000):
    """Fetch a page through FlareSolverr to bypass Cloudflare"""
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": max_timeout
    }
    resp = requests.post(
        f"{get_flaresolverr_url()}/v1",
        json=payload,
        timeout=max_timeout // 1000 + 30
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data.get('message')}")
    solution = data["solution"]
    return solution["response"], solution.get("cookies", []), solution.get("userAgent", "")


def get_source_url_from_cbz(cbz_path: Path) -> str:
    """Extract the source URL (Web field) from ComicInfo.xml in a CBZ"""
    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            if 'ComicInfo.xml' not in zf.namelist():
                return ""
            xml_data = zf.read('ComicInfo.xml').decode('utf-8')
            root = ElementTree.fromstring(xml_data)
            web = root.findtext('Web', '')
            return web
    except Exception:
        return ""


def get_series_url_from_chapter_url(chapter_url: str) -> str:
    """Convert a chapter URL to a series URL"""
    if not chapter_url:
        return ""

    # Asura: https://asuracomic.net/series/slug-hash/chapter/1 -> .../series/slug-hash
    if 'asuracomic' in chapter_url:
        match = re.match(r'(https?://[^/]+/series/[^/]+)', chapter_url)
        return match.group(1) if match else ""

    # Flame: https://flamecomics.xyz/series/ID/HASH -> .../series/ID
    if 'flamecomics' in chapter_url:
        match = re.match(r'(https?://[^/]+/series/\d+)', chapter_url)
        return match.group(1) if match else ""

    # Drake: https://drakecomic.org/slug-chapter-N/ -> need to find series page
    if 'drakecomic' in chapter_url:
        match = re.match(r'(https?://[^/]+/[^/]+?)(?:-chapter-\d+.*)?/?$', chapter_url)
        return match.group(1) + '/' if match else ""

    # ManhuaTo: similar pattern
    if 'manhuato' in chapter_url:
        match = re.match(r'(https?://[^/]+/(?:manhua|manhwa|manga)/[^/]+)', chapter_url)
        return match.group(1) if match else ""

    return ""


def extract_cover_url(html: str, source_url: str) -> str:
    """Extract cover image URL from a series page"""
    soup = BeautifulSoup(html, 'html.parser')

    # 1. og:image meta tag (most reliable)
    og_img = soup.select_one('meta[property="og:image"]')
    if og_img:
        url = og_img.get('content', '').strip()
        if url and url.startswith('http') and not url.endswith('.gif'):
            return url

    # 2. Common cover selectors
    selectors = [
        '.summary_image img', '.thumb img', '.seriestuimg img',
        '.series-thumb img', '.manga-thumb img', '.comic-thumb img',
        '.cover img', '[class*="cover"] img', '[class*="thumb"] img',
        '.info-image img', '.manga-info-pic img',
        'img[class*="cover"]', 'img[class*="thumb"]',
    ]
    for sel in selectors:
        elem = soup.select_one(sel)
        if elem:
            src = elem.get('data-src') or elem.get('src', '')
            src = src.strip()
            if src and len(src) > 10 and not src.endswith('.gif'):
                if src.startswith('//'):
                    src = 'https:' + src
                if src.startswith('http'):
                    return src

    # 3. twitter:image
    tw_img = soup.select_one('meta[name="twitter:image"]')
    if tw_img:
        url = tw_img.get('content', '').strip()
        if url and url.startswith('http'):
            return url

    return ""


def download_cover(cover_url: str, series_dir: Path, referer: str = '') -> bool:
    """Download a cover image to the series directory"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        if referer:
            headers['Referer'] = referer

        resp = requests.get(cover_url, headers=headers, timeout=30)
        resp.raise_for_status()

        if len(resp.content) < 1000:
            return False

        content_type = resp.headers.get('content-type', '').lower()
        if 'png' in content_type or '.png' in cover_url.lower():
            ext = '.png'
        elif 'webp' in content_type or '.webp' in cover_url.lower():
            ext = '.webp'
        else:
            ext = '.jpg'

        cover_path = series_dir / f"cover{ext}"
        cover_path.write_bytes(resp.content)
        logger.info(f"  Saved cover: {cover_path.name} ({len(resp.content):,} bytes)")
        return True
    except Exception as e:
        logger.warning(f"  Failed to download cover: {e}")
        return False


def needs_flaresolverr(url):
    """Check if the URL belongs to a Cloudflare-protected site"""
    return any(domain in url for domain in CLOUDFLARE_DOMAINS)


def fetch_page_html(url, session, use_flaresolverr=False):
    """Fetch page HTML, using FlareSolverr if needed for Cloudflare sites"""
    if use_flaresolverr and needs_flaresolverr(url):
        logger.info(f"  Using FlareSolverr for Cloudflare-protected site")
        html, cookies, user_agent = flaresolverr_get(url)
        # Apply cookies to session for cover image download
        for c in cookies:
            session.cookies.set(c["name"], c["value"],
                                domain=c.get("domain", ""),
                                path=c.get("path", "/"))
        if user_agent:
            session.headers["User-Agent"] = user_agent
        return html
    else:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_covers.py /path/to/library [--dry-run] [--force]")
        sys.exit(1)

    library_path = Path(sys.argv[1])
    dry_run = '--dry-run' in sys.argv
    force = '--force' in sys.argv

    if not library_path.is_dir():
        print(f"Error: {library_path} is not a directory")
        sys.exit(1)

    # Check FlareSolverr availability
    use_fs = flaresolverr_available()
    if use_fs:
        logger.info("FlareSolverr detected - will use for Cloudflare-protected sites")
    else:
        logger.warning("FlareSolverr not available - Cloudflare-protected sites may fail")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    })

    fetched = 0
    skipped = 0
    failed = 0

    for series_dir in sorted(library_path.iterdir()):
        if not series_dir.is_dir() or series_dir.name.startswith('.'):
            continue

        # Check if cover already exists
        has_cover = any(series_dir.glob('cover.*'))
        if has_cover and not force:
            skipped += 1
            continue

        logger.info(f"Processing: {series_dir.name}")

        # Find a CBZ to get the source URL
        cbz_files = sorted(series_dir.glob('*.cbz'))
        if not cbz_files:
            logger.warning(f"  No CBZ files found")
            failed += 1
            continue

        # Try to get source URL from the first CBZ's ComicInfo.xml
        source_url = ""
        for cbz in cbz_files[:3]:  # Check first few CBZs
            chapter_url = get_source_url_from_cbz(cbz)
            if chapter_url:
                source_url = get_series_url_from_chapter_url(chapter_url)
                if source_url:
                    break

        if not source_url:
            logger.warning(f"  No source URL found in ComicInfo.xml")
            failed += 1
            continue

        logger.info(f"  Source: {source_url}")

        if dry_run:
            logger.info(f"  Would fetch cover from: {source_url}")
            fetched += 1
            continue

        # Fetch the series page
        try:
            html = fetch_page_html(source_url, session, use_flaresolverr=use_fs)
            cover_url = extract_cover_url(html, source_url)

            if not cover_url:
                logger.warning(f"  Could not find cover image on page")
                failed += 1
                continue

            logger.info(f"  Cover URL: {cover_url}")
            if download_cover(cover_url, series_dir, referer=source_url):
                fetched += 1
            else:
                failed += 1

            # Rate limit (longer for FlareSolverr to avoid overwhelming it)
            delay = random.uniform(3, 6) if (use_fs and needs_flaresolverr(source_url)) else random.uniform(1, 3)
            time.sleep(delay)

        except Exception as e:
            logger.error(f"  Error: {e}")
            failed += 1

    action = "Would fetch" if dry_run else "Fetched"
    print(f"\n{action} {fetched} covers, skipped {skipped} (already have), failed {failed}")


if __name__ == '__main__':
    main()
