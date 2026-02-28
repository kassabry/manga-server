#!/usr/bin/env python3
"""
Fix for the href whitespace bug in ManhuaTo scraper.

This fixes URLs like "https://manhuato.com /manhua/..." (note the space)
which cause ERR_NAME_NOT_RESOLVED errors.

Run in the same directory as manhwa_scraper.py:
    python fix_href_whitespace.py
"""

import sys
from pathlib import Path

def fix_file(filepath):
    print(f"Fixing href whitespace issues in {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Backup
    backup_path = filepath.with_suffix('.py.href_backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Backup saved to {backup_path}")
    
    fixes_made = 0
    
    # Fix 1: ManhuaTo get_chapters - href not stripped
    old = "href = link.get('href', '')"
    new = "href = link.get('href', '').strip()  # Strip whitespace from href"
    if old in content:
        content = content.replace(old, new)
        fixes_made += 1
        print("  ✓ Fixed: ManhuaTo get_chapters href stripping")
    
    # Fix 2: URL construction without proper slash handling
    # Look for patterns like: self.BASE_URL + href
    # This should check if href starts with / to avoid double slashes or missing slashes
    
    old2 = "full_url = href if href.startswith('http') else self.BASE_URL + href"
    new2 = """# Build URL properly - handle leading slash
                if href.startswith('http'):
                    full_url = href
                elif href.startswith('/'):
                    full_url = self.BASE_URL + href
                else:
                    full_url = self.BASE_URL + '/' + href"""
    
    if old2 in content:
        content = content.replace(old2, new2)
        fixes_made += 1
        print("  ✓ Fixed: URL construction with proper slash handling")
    
    if fixes_made > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n✓ Applied {fixes_made} fix(es) to {filepath}")
    else:
        print("\n⚠ No fixes needed or patterns not found")
        print("  The file may already be fixed or have different code structure")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        filepath = Path(sys.argv[1])
    else:
        filepath = Path("manhwa_scraper.py")
        if not filepath.exists():
            filepath = Path("scripts/manhwa_scraper.py")
    
    if not filepath.exists():
        print(f"Error: Could not find {filepath}")
        print("Usage: python fix_href_whitespace.py /path/to/manhwa_scraper.py")
        sys.exit(1)
    
    fix_file(filepath)
