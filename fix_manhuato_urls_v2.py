#!/usr/bin/env python3
"""
Targeted fix for ManhuaTo URL issues.

The problem: href values have leading spaces like " /manhua/..."
When concatenated with BASE_URL, you get "https://manhuato.com /manhua/..."

This fix:
1. Strips whitespace from href when extracted
2. Properly joins BASE_URL and href
3. Cleans URLs in get_pages as a safety net

Usage:
    python fix_manhuato_urls_v2.py scripts/manhwa_scraper.py
"""

import sys
import re
from pathlib import Path

def patch_file(filepath):
    filepath = Path(filepath)
    
    if not filepath.exists():
        print(f"Error: File not found: {filepath}")
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Backup
    backup_path = filepath.with_suffix('.py.urlfix_backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Backup saved to: {backup_path}")
    
    changes = 0
    
    # ===== FIX 1: Find and fix href extraction in ManhuaToScraper =====
    # The issue is: href = link.get('href', '') gets " /manhua/..." (with space)
    
    # We need to find all places where href is assigned and add .strip()
    # But only in the ManhuaToScraper class
    
    # Pattern to find: link.get('href') without strip
    pattern1 = r"(href\s*=\s*link\.get\(['\"]href['\"]\s*,\s*['\"]['\"]?\))"
    
    def add_strip(match):
        original = match.group(1)
        if '.strip()' not in original:
            return original + '.strip()'
        return original
    
    new_content = re.sub(pattern1, add_strip, content)
    if new_content != content:
        content = new_content
        print("✓ Added .strip() to href extractions")
        changes += 1
    
    # ===== FIX 2: Fix URL joining - ensure no double slashes or space issues =====
    # Pattern: self.BASE_URL + href  should properly handle slashes
    
    # Look for the URL construction in ManhuaTo get_chapters
    # Old pattern: full_url = href if href.startswith('http') else self.BASE_URL + href
    
    old_url_join = "full_url = href if href.startswith('http') else self.BASE_URL + href"
    new_url_join = """# Properly join URL parts
                if href.startswith('http'):
                    full_url = href
                else:
                    # Ensure clean join - remove trailing slash from base, add leading slash to href if needed
                    base = self.BASE_URL.rstrip('/')
                    path = href.lstrip('/')
                    full_url = f"{base}/{path}\""""
    
    if old_url_join in content:
        content = content.replace(old_url_join, new_url_join)
        print("✓ Fixed URL joining logic")
        changes += 1
    
    # ===== FIX 3: Add safety cleaning in get_pages =====
    # This catches any URLs that slipped through with issues
    
    # Find: logger.info(f"Loading chapter page: {chapter.url}")
    # or: self.driver.get(chapter.url)
    
    old_log = 'logger.info(f"Loading chapter page: {chapter.url}")'
    new_log = '''# Clean URL before use
            clean_url = chapter.url.strip()
            if ' ' in clean_url:
                clean_url = clean_url.replace(' ', '')
            logger.info(f"Loading chapter page: {clean_url}")'''
    
    if old_log in content and 'clean_url = chapter.url' not in content:
        content = content.replace(old_log, new_log)
        print("✓ Added URL cleaning in get_pages logging")
        changes += 1
    
    # Also fix the driver.get call
    old_get = 'self.driver.get(chapter.url)'
    new_get = 'self.driver.get(clean_url)'
    
    # Only replace within ManhuaTo get_pages context (after we added clean_url)
    if 'clean_url = chapter.url' in content and old_get in content:
        # Find the ManhuaTo get_pages method and replace there
        # This is tricky - we need to be careful not to replace in other classes
        
        # Simple approach: if clean_url is defined, replace driver.get(chapter.url)
        content = content.replace(old_get, new_get, 1)  # Only first occurrence
        print("✓ Fixed driver.get to use cleaned URL")
        changes += 1
    
    # ===== FIX 4: Filter to only cdn.manhuato images =====
    # This prevents grabbing tracking pixels from ad/redirect pages
    
    # Make the image filter more strict
    old_filter = '''if 'manhuato' not in src_lower and 'cdn.manhuato' not in src_lower:
                    continue'''
    new_filter = '''# Only accept images from cdn.manhuato.com
                if 'cdn.manhuato.com' not in src_lower:
                    continue'''
    
    if old_filter in content:
        content = content.replace(old_filter, new_filter)
        print("✓ Tightened image filter to cdn.manhuato.com only")
        changes += 1
    
    # Write patched file
    if changes > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n✓ Applied {changes} fix(es)")
    else:
        print("\nNo changes made - file may already be fixed or has different structure")
    
    return changes > 0

if __name__ == "__main__":
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        for path in ['manhwa_scraper.py', 'scripts/manhwa_scraper.py']:
            if Path(path).exists():
                filepath = path
                break
        else:
            print("Usage: python fix_manhuato_urls_v2.py /path/to/manhwa_scraper.py")
            sys.exit(1)
    
    success = patch_file(filepath)
    
    if success:
        print("\nTest with:")
        print(f'  python {filepath} --download-url "https://manhuato.com/manhua/eleceed" --chapters 1 --visible -o test')
