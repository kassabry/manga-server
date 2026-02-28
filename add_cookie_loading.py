#!/usr/bin/env python3
"""
Add cookie loading to ManhuaTo scraper.
This loads cookies saved by test_uc_manhuato.py

Usage:
    python add_cookie_loading.py scripts/manhwa_scraper.py
"""

import sys
from pathlib import Path

COOKIE_LOADING_CODE = '''
    def _load_manhuato_cookies(self):
        """Load saved ManhuaTo cookies to bypass verification"""
        import pickle
        cookie_file = Path("manhuato_cookies.pkl")
        if not cookie_file.exists():
            return False
        try:
            with open(cookie_file, 'rb') as f:
                cookies = pickle.load(f)
            # Navigate to domain first
            self.driver.get("https://manhuato.com")
            time.sleep(1)
            for cookie in cookies:
                try:
                    self.driver.add_cookie(cookie)
                except:
                    pass
            logger.info(f"Loaded {len(cookies)} ManhuaTo cookies")
            return True
        except Exception as e:
            logger.debug(f"Could not load cookies: {e}")
            return False
'''

def patch_file(filepath):
    filepath = Path(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Backup
    backup = filepath.with_suffix('.py.cookie_backup')
    with open(backup, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Backup: {backup}")
    
    changes = 0
    
    # Add Path import if not present
    if 'from pathlib import Path' not in content:
        content = 'from pathlib import Path\n' + content
        print("✓ Added Path import")
        changes += 1
    
    # Add cookie loading method to ManhuaToScraper
    if '_load_manhuato_cookies' not in content:
        # Find ManhuaToScraper class and add method
        marker = 'class ManhuaToScraper(BaseScraper):'
        if marker in content:
            # Find the end of class definition line
            idx = content.find(marker)
            # Find the next line after class definition
            newline_idx = content.find('\n', idx)
            # Insert after the docstring if present, or after class line
            # Look for the first method
            next_def = content.find('\n    def ', newline_idx)
            if next_def > 0:
                content = content[:next_def] + COOKIE_LOADING_CODE + content[next_def:]
                print("✓ Added _load_manhuato_cookies method")
                changes += 1
    
    # Modify get_pages to load cookies before navigating
    old_load = 'logger.info(f"Loading chapter page: {chapter_url}")'
    new_load = '''# Try to load saved cookies for ManhuaTo
            self._load_manhuato_cookies()
            logger.info(f"Loading chapter page: {chapter_url}")'''
    
    # Also try without f-string variant
    old_load2 = 'logger.info(f"Loading chapter page: {chapter.url}")'
    new_load2 = '''# Try to load saved cookies for ManhuaTo
            self._load_manhuato_cookies()
            logger.info(f"Loading chapter page: {chapter.url}")'''
    
    if old_load in content and '_load_manhuato_cookies()' not in content.split(old_load)[0][-200:]:
        content = content.replace(old_load, new_load, 1)
        print("✓ Added cookie loading before page load")
        changes += 1
    elif old_load2 in content and '_load_manhuato_cookies()' not in content.split(old_load2)[0][-200:]:
        content = content.replace(old_load2, new_load2, 1)
        print("✓ Added cookie loading before page load")
        changes += 1
    
    if changes > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n✓ Applied {changes} changes")
        print("\nMake sure manhuato_cookies.pkl exists (run test_uc_manhuato.py first)")
    else:
        print("\nNo changes made")
    
    return changes > 0

if __name__ == "__main__":
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        for p in ['manhwa_scraper.py', 'scripts/manhwa_scraper.py']:
            if Path(p).exists():
                filepath = p
                break
        else:
            print("Usage: python add_cookie_loading.py /path/to/manhwa_scraper.py")
            sys.exit(1)
    
    patch_file(filepath)
