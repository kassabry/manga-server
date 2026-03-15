#!/usr/bin/env python3
"""
Comprehensive fix for ManhuaTo scraper issues:
1. Fix href whitespace bug in get_chapters (space in URLs)
2. Fix redirect handling in get_pages
3. Add image URL enumeration
4. Better URL validation

Usage:
    python fix_manhuato_comprehensive.py scripts/manhwa_scraper.py
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
    backup_path = filepath.with_suffix('.py.manhuato_backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Backup saved to: {backup_path}")
    
    changes = 0
    
    # ===== FIX 1: Strip whitespace from ALL href extractions =====
    
    # Replace all instances of getting href without strip
    # Pattern: .get('href', '') or .get("href", "")
    patterns_to_fix = [
        ("link.get('href', '')", "link.get('href', '').strip()"),
        ('link.get("href", "")', 'link.get("href", "").strip()'),
        (".get('href', '')", ".get('href', '').strip()"),
        ('.get("href", "")', '.get("href", "").strip()'),
    ]
    
    for old, new in patterns_to_fix:
        # Don't double-add strip
        if old in content and new not in content:
            content = content.replace(old, new)
            print(f"✓ Fixed: Added .strip() to href extraction")
            changes += 1
            break  # Only do once to avoid duplicates
    
    # ===== FIX 2: Fix URL construction - remove double slashes and spaces =====
    
    # Find and fix URL construction patterns
    # Pattern: self.BASE_URL + href
    old_patterns = [
        "full_url = href if href.startswith('http') else self.BASE_URL + href",
        'full_url = href if href.startswith("http") else self.BASE_URL + href',
    ]
    
    new_url_code = '''# Build URL properly
                href = href.strip()
                if href.startswith('http'):
                    full_url = href
                else:
                    # Remove leading slash from href if BASE_URL ends with slash
                    if self.BASE_URL.endswith('/') and href.startswith('/'):
                        href = href[1:]
                    elif not self.BASE_URL.endswith('/') and not href.startswith('/'):
                        href = '/' + href
                    full_url = self.BASE_URL + href
                full_url = full_url.replace(' ', '')  # Remove any spaces'''
    
    for old_pattern in old_patterns:
        if old_pattern in content:
            content = content.replace(old_pattern, new_url_code)
            print("✓ Fixed: URL construction with proper slash/space handling")
            changes += 1
            break
    
    # ===== FIX 3: Replace ManhuaTo get_pages method =====
    
    # Find the ManhuaToScraper class and its get_pages method
    manhuato_get_pages_pattern = r'(class ManhuaToScraper\(BaseScraper\):.*?)(    def get_pages\(self, chapter: Chapter\) -> List\[str\]:.*?)(?=\n    def [a-z_]+\(self|\nclass [A-Z]|\Z)'
    
    new_get_pages = '''    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter with ad blocking and URL enumeration"""
        import requests as req
        
        try:
            # Fix URL - strip whitespace and remove any spaces
            chapter_url = chapter.url.strip().replace(' ', '').replace('/ /', '/')
            logger.info(f"Loading chapter page: {chapter_url}")
            
            # Use selenium to load the page
            self._init_driver()
            
            # Try to load the page with retries (ads may redirect)
            max_retries = 5
            loaded_successfully = False
            
            for attempt in range(max_retries):
                try:
                    self.driver.get(chapter_url)
                    time.sleep(2)
                    
                    current_url = self.driver.current_url.lower()
                    if 'manhuato.com' in current_url:
                        logger.info(f"Successfully loaded chapter page (attempt {attempt + 1})")
                        loaded_successfully = True
                        break
                    else:
                        logger.warning(f"Redirected to {current_url[:60]}..., retrying...")
                        time.sleep(1)
                        # Force navigate back
                        self.driver.get(chapter_url)
                except Exception as e:
                    logger.warning(f"Navigation attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
            
            # Check if we're on the right page
            if not loaded_successfully or 'manhuato.com' not in self.driver.current_url.lower():
                logger.error(f"Could not load chapter page after {max_retries} attempts")
                logger.error(f"Current URL: {self.driver.current_url}")
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
            except:
                pass
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            pages = []
            
            # Find images (without scrolling to avoid ad triggers)
            for img in soup.select('img'):
                src = img.get('data-original') or img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
                
                if not src or src.startswith('data:') or len(src) < 10:
                    continue
                
                src = src.strip()
                
                # Ensure full URL
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = self.BASE_URL.rstrip('/') + src
                
                # Filter for chapter images - must be from manhuato CDN
                src_lower = src.lower()
                
                # Only accept images from manhuato CDN
                if 'cdn.manhuato' not in src_lower:
                    continue
                
                skip_keywords = ['logo', 'icon', 'loading', 'avatar', 'banner', 'ad', 'thumb', 'small', 'game']
                if any(kw in src_lower for kw in skip_keywords):
                    continue
                
                if src not in pages:
                    pages.append(src)
            
            logger.info(f"Found {len(pages)} images from page HTML")
            
            # Enumerate more images based on URL pattern
            if pages:
                import re as regex
                
                base_url = None
                extension = None
                max_found = -1
                
                for img_url in pages:
                    match = regex.search(r'(.+/)(\\d+)(\\.[a-z]+)$', img_url, regex.I)
                    if match:
                        base_url = match.group(1)
                        num = int(match.group(2))
                        extension = match.group(3)
                        if num > max_found:
                            max_found = num
                
                if base_url and extension and 'cdn.manhuato' in base_url.lower():
                    logger.info(f"Enumerating images from pattern: {base_url}[N]{extension}")
                    
                    session = req.Session()
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': chapter_url,
                    })
                    
                    # Find all images by enumeration starting from 0 (rate-limited)
                    consecutive_failures = 0
                    current_num = 0
                    ENUM_DELAY = 0.3  # seconds between probes

                    while consecutive_failures < 5 and current_num < 300:
                        test_url = f"{base_url}{current_num}{extension}"

                        if test_url not in pages:
                            try:
                                resp = session.get(test_url, timeout=10, stream=True)
                                content_type = resp.headers.get('Content-Type', '')

                                if resp.status_code == 200 and 'image' in content_type:
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
                        m = regex.search(r'/(\\d+)\\.[a-z]+$', url, regex.I)
                        return int(m.group(1)) if m else 0
                    
                    pages.sort(key=get_num)
            
            logger.info(f"Found {len(pages)} page images total")
            return pages
            
        except Exception as e:
            logger.error(f"Error getting pages: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []
'''
    
    match = re.search(manhuato_get_pages_pattern, content, re.DOTALL)
    if match:
        old_method = match.group(2)
        # Only replace if not already patched
        if 'Enumerating images' not in old_method:
            content = content.replace(old_method, new_get_pages)
            print("✓ Replaced ManhuaTo get_pages with improved version")
            changes += 1
        else:
            print("  get_pages already patched")
    else:
        print("  Could not find ManhuaTo get_pages method - may need manual edit")
    
    # Write patched file
    if changes > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n✓ Applied {changes} fix(es)")
    else:
        print("\nNo changes made")
    
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
            print("Usage: python fix_manhuato_comprehensive.py /path/to/manhwa_scraper.py")
            sys.exit(1)
    
    patch_file(filepath)
    print("\nTest with:")
    print(f'  python {filepath} --download-url "https://manhuato.com/manhua/eleceed" --chapters 1 --visible -o test')
