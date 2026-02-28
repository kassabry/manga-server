#!/usr/bin/env python3
"""
Alternative ManhuaTo scraper using requests (no browser).
This avoids browser-triggered ad redirects.

Usage:
    python test_manhuato_requests.py
"""

import requests
from bs4 import BeautifulSoup
import re
import time

# Use a realistic browser user agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def test_manhuato_requests():
    print("--- Testing ManhuaTo with requests (no browser) ---\n")
    
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # Step 1: Get series page
    series_url = "https://manhuato.com/manhua/eleceed"
    print(f"Step 1: Fetching series page...")
    print(f"  URL: {series_url}")
    
    try:
        resp = session.get(series_url, timeout=15)
        resp.raise_for_status()
        print(f"  ✓ Got response: {resp.status_code}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Find chapter links
    chapter_links = soup.select('a[href*="-chapter-"]')
    print(f"  Found {len(chapter_links)} chapter links")
    
    if not chapter_links:
        print("  ✗ No chapter links found!")
        return False
    
    # Find chapter 1
    chapter_1_url = None
    for link in chapter_links:
        href = link.get('href', '').strip()
        if re.search(r'chapter-1(?!\d)', href.lower()):
            if href.startswith('http'):
                chapter_1_url = href
            elif href.startswith('/'):
                chapter_1_url = f"https://manhuato.com{href}"
            else:
                chapter_1_url = f"https://manhuato.com/{href}"
            break
    
    if not chapter_1_url:
        # Use last chapter
        href = chapter_links[-1].get('href', '').strip()
        if href.startswith('http'):
            chapter_1_url = href
        elif href.startswith('/'):
            chapter_1_url = f"https://manhuato.com{href}"
        else:
            chapter_1_url = f"https://manhuato.com/{href}"
    
    print(f"  ✓ Found chapter 1: {chapter_1_url}")
    
    # Step 2: Get chapter page
    print(f"\nStep 2: Fetching chapter page...")
    print(f"  URL: {chapter_1_url}")
    
    time.sleep(1)  # Be polite
    
    try:
        resp = session.get(chapter_1_url, timeout=15)
        resp.raise_for_status()
        print(f"  ✓ Got response: {resp.status_code}")
        
        # Check for redirect
        if 'manhuato.com' not in resp.url.lower():
            print(f"  ⚠ Got redirected to: {resp.url}")
            print("  This shouldn't happen with requests - the site might be blocking scrapers")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Step 3: Find images
    print(f"\nStep 3: Searching for images...")
    
    all_imgs = soup.select('img')
    print(f"  Total <img> tags: {len(all_imgs)}")
    
    chapter_images = []
    for img in all_imgs:
        # Try different attributes
        src = img.get('data-original') or img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
        
        if not src or src.startswith('data:'):
            continue
        
        src_lower = src.lower()
        
        # Skip non-chapter images
        if any(skip in src_lower for skip in ['logo', 'icon', 'avatar', 'banner', 'ad', 'thumb', 'game', 'small']):
            continue
        
        # Include likely chapter images
        if any(inc in src_lower for inc in ['chapter', 'manhua', 'uploads', 'cdn', 'wp-content', 'media']) or \
           any(ext in src_lower for ext in ['.jpg', '.png', '.webp']):
            if src not in chapter_images:
                chapter_images.append(src)
    
    print(f"  Chapter images found: {len(chapter_images)}")
    
    if chapter_images:
        print("\n✓ SUCCESS! Found chapter images:")
        for i, img in enumerate(chapter_images[:5], 1):
            print(f"  {i}. {img[:80]}...")
        if len(chapter_images) > 5:
            print(f"  ... and {len(chapter_images) - 5} more")
        
        # Test if we can actually download an image
        print("\nStep 4: Testing image download...")
        test_img = chapter_images[0]
        try:
            img_resp = session.get(test_img, timeout=15)
            if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                print(f"  ✓ Successfully downloaded image ({len(img_resp.content)} bytes)")
            else:
                print(f"  ⚠ Image download returned {img_resp.status_code}, {len(img_resp.content)} bytes")
        except Exception as e:
            print(f"  ⚠ Could not download test image: {e}")
        
        return True
    else:
        print("\n✗ No chapter images found!")
        print("  The images might be loaded via JavaScript, which requests can't execute.")
        print("  This method won't work for this site.")
        
        # Show what we found
        print("\n  All images found:")
        for img in all_imgs[:10]:
            src = img.get('src', img.get('data-src', 'no-src'))
            print(f"    - {src[:60]}...")
        
        return False

if __name__ == "__main__":
    success = test_manhuato_requests()
    
    print("\n" + "="*50)
    if success:
        print("REQUESTS METHOD WORKS!")
        print("\nThis means we can scrape ManhuaTo without a browser.")
        print("The images are available in the HTML without JavaScript.")
    else:
        print("REQUESTS METHOD FAILED")
        print("\nThe site requires JavaScript to load images.")
        print("You'll need to use the Selenium approach or try different sites.")
    print("="*50)
