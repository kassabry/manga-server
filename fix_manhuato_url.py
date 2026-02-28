#!/usr/bin/env python3
"""
Simple fix for ManhuaTo URL space issue.
This adds a URL cleaning step at the START of get_pages method.

Usage:
    python fix_manhuato_url.py scripts/manhwa_scraper.py
"""

import sys
from pathlib import Path

def patch_file(filepath):
    filepath = Path(filepath)
    
    if not filepath.exists():
        print(f"Error: File not found: {filepath}")
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Backup
    backup_path = filepath.with_suffix('.py.url_backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Backup saved to: {backup_path}")
    
    changes = 0
    
    # ===== FIX 1: Add URL cleaning to ManhuaTo get_pages =====
    # Find: logger.info(f"Loading chapter page: {chapter.url}")
    # Add URL cleaning before it
    
    old_line = 'logger.info(f"Loading chapter page: {chapter.url}")'
    new_lines = '''# Fix URL - remove spaces and double slashes
            chapter_url = chapter.url.strip().replace(' ', '').replace('//manhua', '/manhua')
            logger.info(f"Loading chapter page: {chapter_url}")'''
    
    if old_line in content and 'chapter_url = chapter.url.strip()' not in content:
        content = content.replace(old_line, new_lines)
        print("✓ Added URL cleaning to get_pages")
        changes += 1
    
    # Also need to replace chapter.url with chapter_url in the rest of the method
    # Find the get_pages method in ManhuaToScraper and replace chapter.url references
    
    # Look for self.driver.get(chapter.url) and replace with self.driver.get(chapter_url)
    old_get = 'self.driver.get(chapter.url)'
    new_get = 'self.driver.get(chapter_url)'
    
    if old_get in content:
        content = content.replace(old_get, new_get)
        print("✓ Fixed driver.get to use cleaned URL")
        changes += 1
    
    # ===== FIX 2: Add .strip() to href extraction if not present =====
    
    # Check for href extraction without strip in ManhuaTo section
    if "href = link.get('href', '')" in content:
        # Only fix in ManhuaTo class - look for context
        lines = content.split('\n')
        new_lines_list = []
        in_manhuato = False
        
        for line in lines:
            if 'class ManhuaToScraper' in line:
                in_manhuato = True
            elif line.startswith('class ') and 'ManhuaTo' not in line:
                in_manhuato = False
            
            # Fix href in ManhuaTo class
            if in_manhuato and "href = link.get('href', '')" in line and '.strip()' not in line:
                line = line.replace("href = link.get('href', '')", "href = link.get('href', '').strip()")
                changes += 1
                print("✓ Added .strip() to href in ManhuaTo")
            
            new_lines_list.append(line)
        
        content = '\n'.join(new_lines_list)
    
    # ===== FIX 3: Filter images to only accept manhuato CDN =====
    # This prevents grabbing images from ad/redirect pages
    
    # Look for the image filtering in ManhuaTo get_pages
    old_filter = "if 'manhuato' not in src_lower and 'cdn.manhuato' not in src_lower:"
    new_filter = "if 'cdn.manhuato' not in src_lower:  # Only accept manhuato CDN images"
    
    if old_filter in content:
        content = content.replace(old_filter, new_filter)
        print("✓ Tightened image filter to only cdn.manhuato")
        changes += 1
    
    # Write patched file
    if changes > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n✓ Applied {changes} fix(es)")
        print("\nTest with:")
        print(f'  python {filepath} --download-url "https://manhuato.com/manhua/eleceed" --chapters 1 --visible -o test')
    else:
        print("\nNo changes needed or already patched")
    
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
            print("Usage: python fix_manhuato_url.py /path/to/manhwa_scraper.py")
            sys.exit(1)
    
    patch_file(filepath)
