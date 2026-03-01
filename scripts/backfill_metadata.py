#!/usr/bin/env python3
"""
backfill_metadata.py - Re-fetch series metadata from source sites and update CBZ files

For series downloaded before genre/description extraction was fixed, this script:
1. Reads the source URL from ComicInfo.xml in the first CBZ
2. Fetches series details (genres, description, author, artist, rating, status)
3. Updates ComicInfo.xml in ALL CBZ files for that series

Usage:
    python backfill_metadata.py /path/to/library/Manhwa
    python backfill_metadata.py /path/to/library/Manhwa --dry-run
    python backfill_metadata.py /path/to/library/Manhwa --series "Solo Leveling"
"""

import os
import re
import sys
import time
import random
import zipfile
import logging
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing: pip install requests beautifulsoup4")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# FlareSolverr for Cloudflare-protected sites
FLARESOLVERR_URL = os.environ.get('FLARESOLVERR_URL', 'http://localhost:8191')
CLOUDFLARE_DOMAINS = ['asuracomic', 'drakecomic', 'flamecomics']


def flaresolverr_available():
    try:
        resp = requests.get(FLARESOLVERR_URL, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def flaresolverr_get(url):
    payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
    resp = requests.post(f"{FLARESOLVERR_URL}/v1", json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data.get('message')}")
    return data["solution"]["response"]


def needs_flaresolverr(url):
    return any(d in url for d in CLOUDFLARE_DOMAINS)


def fetch_page(url, session, use_fs=False):
    if use_fs and needs_flaresolverr(url):
        logger.info(f"  Using FlareSolverr for {url}")
        return flaresolverr_get(url)
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def escape_xml(text):
    if not text:
        return ""
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;'))


def extract_asura_details(soup):
    """Extract series metadata from an Asura series page."""
    details = {}

    # Genres
    genre_links = soup.select('a[href*="/series?page=1&genres="]')
    if genre_links:
        seen = set()
        genres = []
        for link in genre_links:
            text = link.get_text(strip=True).strip(',').strip()
            if text and text.lower() not in seen:
                seen.add(text.lower())
                genres.append(text)
        if genres:
            details['genres'] = ', '.join(genres)

    # Synopsis
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
                    details['description'] = re.sub(r'\s+', ' ', text)[:2000]
            break

    # Status
    for h3 in soup.select('h3'):
        if h3.get_text(strip=True) == 'Status':
            next_h3 = h3.find_next_sibling('h3')
            if next_h3:
                text = next_h3.get_text(strip=True)
                details['status'] = text.capitalize()
            break

    # Rating — normalize to 5-point scale
    for div in soup.select('div[class*="italic"]'):
        text = div.get_text(strip=True)
        try:
            val = float(text)
            if 0 < val <= 10:
                # Normalize: Asura uses 10-point scale, store as 5-point
                details['rating'] = round(val / 2, 1) if val > 5 else round(val, 1)
                break
        except ValueError:
            continue

    # Author
    for h3 in soup.select('h3'):
        if h3.get_text(strip=True) == 'Author':
            next_h3 = h3.find_next_sibling('h3')
            if next_h3:
                text = next_h3.get_text(strip=True)
                if text and text != '_':
                    details['author'] = text
            break

    # Artist
    for h3 in soup.select('h3'):
        if h3.get_text(strip=True) == 'Artist':
            next_h3 = h3.find_next_sibling('h3')
            if next_h3:
                text = next_h3.get_text(strip=True)
                if text and text != '_':
                    details['artist'] = text
            break

    return details


def extract_drake_details(soup):
    """Extract series metadata from a Drake Comics series page."""
    details = {}

    # Genres - Drake uses .mgen or genre containers
    mgen = soup.select_one('.mgen')
    if mgen:
        genres = [a.get_text(strip=True) for a in mgen.select('a') if a.get_text(strip=True)]
        if genres:
            details['genres'] = ', '.join(genres)

    # Description
    for selector in ['.entry-content[itemprop="description"]', '.summary__content', '.desc', '.description']:
        elem = soup.select_one(selector)
        if elem:
            text = elem.get_text(strip=True)
            if len(text) > 20:
                details['description'] = re.sub(r'\s+', ' ', text)[:2000]
                break

    # Status
    for selector in ['.imptdt', '.tsinfo']:
        container = soup.select_one(selector)
        if container:
            text = container.get_text(strip=True).lower()
            if 'ongoing' in text:
                details['status'] = 'Ongoing'
            elif 'completed' in text:
                details['status'] = 'Completed'

    return details


def extract_flame_details(soup):
    """Extract series metadata from a Flame Comics series page."""
    # Flame has similar structure to Drake (WordPress manga theme)
    return extract_drake_details(soup)


def get_details_for_url(url, session, use_fs):
    """Fetch and parse series details from a source URL."""
    html = fetch_page(url, session, use_fs)
    soup = BeautifulSoup(html, 'html.parser')

    if 'asuracomic' in url:
        return extract_asura_details(soup)
    elif 'drakecomic' in url:
        return extract_drake_details(soup)
    elif 'flamecomics' in url:
        return extract_flame_details(soup)
    return {}


def read_comic_info(cbz_path):
    """Read ComicInfo.xml from a CBZ file."""
    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            if 'ComicInfo.xml' not in zf.namelist():
                return None
            return zf.read('ComicInfo.xml').decode('utf-8')
    except Exception:
        return None


def get_web_url(xml_content):
    """Extract <Web> URL from ComicInfo.xml."""
    match = re.search(r'<Web>(.*?)</Web>', xml_content)
    if match:
        return match.group(1).replace('&amp;', '&')
    return None


def get_series_url(xml_content):
    """Extract series URL from chapter URL in ComicInfo.xml.

    Chapter URLs look like:
    - https://asuracomic.net/series/solo-leveling-abc123/chapter/1
    - https://drakecomic.org/manga/series-name/chapter-1/
    """
    web_url = get_web_url(xml_content)
    if not web_url:
        return None

    if 'asuracomic' in web_url:
        # Strip /chapter/N from the end
        match = re.match(r'(https?://[^/]+/series/[^/]+)', web_url)
        if match:
            return match.group(1)
    elif 'drakecomic' in web_url:
        match = re.match(r'(https?://[^/]+/manga/[^/]+)', web_url)
        if match:
            return match.group(1) + '/'
    elif 'flamecomics' in web_url:
        match = re.match(r'(https?://[^/]+/series/[^/]+)', web_url)
        if match:
            return match.group(1)

    return None


def xml_has_field(xml_content, field):
    """Check if a ComicInfo.xml field has meaningful content."""
    match = re.search(rf'<{field}>(.*?)</{field}>', xml_content)
    return match and match.group(1).strip() not in ('', '_')


def needs_backfill(xml_content):
    """Check if ComicInfo.xml is missing genres or description."""
    has_genre = xml_has_field(xml_content, 'Genre')
    has_summary = xml_has_field(xml_content, 'Summary')
    return not has_genre or not has_summary


def update_xml(xml_content, details):
    """Update ComicInfo.xml with new metadata fields."""
    modified = False

    def set_field(xml, tag, value):
        nonlocal modified
        if not value:
            return xml
        existing = re.search(rf'<{tag}>(.*?)</{tag}>', xml)
        if existing and existing.group(1).strip() not in ('', '_'):
            return xml  # Don't overwrite existing data
        escaped = escape_xml(value)
        if existing:
            xml = xml.replace(existing.group(0), f'<{tag}>{escaped}</{tag}>')
        else:
            # Insert before </ComicInfo>
            xml = xml.replace('</ComicInfo>', f'  <{tag}>{escaped}</{tag}>\n</ComicInfo>')
        modified = True
        return xml

    xml_content = set_field(xml_content, 'Genre', details.get('genres'))
    xml_content = set_field(xml_content, 'Tags', details.get('genres'))
    xml_content = set_field(xml_content, 'Summary', details.get('description'))
    xml_content = set_field(xml_content, 'Writer', details.get('author'))
    xml_content = set_field(xml_content, 'Penciller', details.get('artist'))

    if details.get('rating'):
        existing_rating = re.search(r'<CommunityRating>(.*?)</CommunityRating>', xml_content)
        if not existing_rating or not existing_rating.group(1).strip():
            # Rating is already normalized to 5-point scale by extract_*_details()
            xml_content = set_field(xml_content, 'CommunityRating', f'{details["rating"]:.1f}')

    if details.get('status'):
        existing_notes = re.search(r'<Notes>(.*?)</Notes>', xml_content)
        if existing_notes:
            notes = existing_notes.group(1)
            if 'Status:' not in notes:
                new_notes = f"{notes} | Status: {details['status']}"
                xml_content = xml_content.replace(existing_notes.group(0),
                                                   f'<Notes>{escape_xml(new_notes)}</Notes>')
                modified = True

    return xml_content, modified


def update_cbz(cbz_path, new_xml, dry_run=False):
    """Rewrite CBZ with updated ComicInfo.xml."""
    if dry_run:
        return True
    try:
        temp_path = cbz_path.with_suffix('.cbz.tmp')
        with zipfile.ZipFile(cbz_path, 'r') as zf_in:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_STORED) as zf_out:
                for item in zf_in.infolist():
                    if item.filename == 'ComicInfo.xml':
                        zf_out.writestr(item, new_xml.encode('utf-8'))
                    else:
                        zf_out.writestr(item, zf_in.read(item.filename))
        temp_path.replace(cbz_path)
        return True
    except Exception as e:
        logger.error(f"  Error writing {cbz_path.name}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Backfill series metadata into CBZ files')
    parser.add_argument('library', type=Path, help='Path to library directory (e.g. /app/library/Manhwa)')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without modifying files')
    parser.add_argument('--series', type=str, help='Only process this series (by folder name)')
    parser.add_argument('--force', action='store_true', help='Re-fetch even if genres/description exist')
    args = parser.parse_args()

    if not args.library.is_dir():
        print(f"Error: {args.library} is not a directory")
        sys.exit(1)

    use_fs = flaresolverr_available()
    if use_fs:
        logger.info("FlareSolverr detected - will use for Cloudflare-protected sites")
    else:
        logger.info("FlareSolverr not available - Cloudflare sites may fail")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    # Find series directories
    series_dirs = sorted([d for d in args.library.iterdir() if d.is_dir()])
    if args.series:
        series_dirs = [d for d in series_dirs if d.name == args.series]
        if not series_dirs:
            print(f"Series folder '{args.series}' not found")
            sys.exit(1)

    updated_series = 0
    updated_files = 0
    skipped = 0

    for series_dir in series_dirs:
        cbz_files = sorted(series_dir.glob('*.cbz'))
        if not cbz_files:
            continue

        # Read ComicInfo from first CBZ to get source URL and check if backfill needed
        first_xml = read_comic_info(cbz_files[0])
        if not first_xml:
            logger.debug(f"No ComicInfo.xml in {cbz_files[0].name}")
            continue

        if not args.force and not needs_backfill(first_xml):
            skipped += 1
            continue

        series_url = get_series_url(first_xml)
        if not series_url:
            logger.debug(f"No source URL for {series_dir.name}")
            skipped += 1
            continue

        logger.info(f"Processing: {series_dir.name} ({len(cbz_files)} chapters)")
        logger.info(f"  Source: {series_url}")

        try:
            details = get_details_for_url(series_url, session, use_fs)
        except Exception as e:
            logger.error(f"  Failed to fetch details: {e}")
            continue

        if not details:
            logger.info(f"  No metadata found")
            continue

        found = []
        if details.get('genres'):
            found.append(f"genres={details['genres']}")
        if details.get('description'):
            found.append(f"desc={details['description'][:80]}...")
        if details.get('author'):
            found.append(f"author={details['author']}")
        if details.get('status'):
            found.append(f"status={details['status']}")
        if details.get('rating'):
            found.append(f"rating={details['rating']}/5")
        logger.info(f"  Found: {', '.join(found)}")

        # Update all CBZ files in the series
        series_updated = 0
        total_cbz = len(cbz_files)
        for idx, cbz_path in enumerate(cbz_files, 1):
            xml = read_comic_info(cbz_path)
            if not xml:
                continue
            new_xml, modified = update_xml(xml, details)
            if modified:
                if args.dry_run:
                    pass  # Don't log every file in dry-run
                else:
                    if update_cbz(cbz_path, new_xml):
                        series_updated += 1
            # Progress logging for large series
            if total_cbz > 50 and idx % 50 == 0:
                logger.info(f"  Progress: {idx}/{total_cbz} files...")

        if series_updated > 0 or args.dry_run:
            updated_series += 1
            updated_files += series_updated
            action = "Would update" if args.dry_run else "Updated"
            count = total_cbz if args.dry_run else series_updated
            logger.info(f"  {action} {count}/{total_cbz} CBZ files")

        # Rate limit
        time.sleep(random.uniform(1, 3))

    print(f"\nDone! {'Would update' if args.dry_run else 'Updated'} {updated_series} series "
          f"({updated_files} files), skipped {skipped} (already complete)")


if __name__ == '__main__':
    main()
