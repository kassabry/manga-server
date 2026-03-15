#!/usr/bin/env python3
"""
Patch for ManhuaTo get_pages method to remove ad overlays.
Run after applying the UC patch.

Usage:
    python patch_manhuato_ads.py scripts/manhwa_scraper.py
"""

import sys
import re
from pathlib import Path

NEW_GET_PAGES = '''    def get_pages(self, chapter: Chapter) -> List[str]:
        """Get image URLs for a chapter with ad blocking and URL enumeration"""
        try:
            logger.info(f"Loading chapter page: {chapter.url}")
            
            # Use selenium to load the page
            self._init_driver()
            
            # Try to load the page (may redirect to ads)
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver.get(chapter.url)
                    time.sleep(2)
                    
                    if 'manhuato.com' in self.driver.current_url.lower():
                        break
                    else:
                        logger.warning(f"Redirected to {self.driver.current_url[:50]}..., retrying...")
                        time.sleep(1)
                except Exception as e:
                    logger.warning(f"Navigation attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
            
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
                    src = self.BASE_URL + src
                
                # Filter for chapter images
                src_lower = src.lower()
                skip_keywords = ['logo', 'icon', 'loading', 'avatar', 'banner', 'ad', 'thumb', 'small', 'game']
                include_keywords = ['media', 'chapter', 'manhua', 'uploads', 'images', 'files', 'cdn', 'wp-content']
                
                if any(kw in src_lower for kw in skip_keywords):
                    continue
                
                if any(kw in src_lower for kw in include_keywords) or \\
                   any(ext in src_lower for ext in ['.jpg', '.png', '.webp']):
                    if src not in pages:
                        pages.append(src)
            
            # Enumerate more images based on URL pattern
            if pages:
                import re
                import requests as req
                
                base_url = None
                extension = None
                max_found = -1
                
                for img_url in pages:
                    match = re.search(r'(.+/)(\\d+)(\\.[a-z]+)$', img_url, re.I)
                    if match:
                        base_url = match.group(1)
                        num = int(match.group(2))
                        extension = match.group(3)
                        if num > max_found:
                            max_found = num
                
                if base_url and extension:
                    logger.info(f"Enumerating images from pattern: {base_url}[N]{extension}")
                    
                    session = req.Session()
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': 'https://manhuato.com/',
                    })
                    
                    # Find all images by enumeration (rate-limited to avoid CDN bans)
                    consecutive_failures = 0
                    current_num = 0
                    ENUM_DELAY = 0.3  # seconds between probes

                    while consecutive_failures < 3 and current_num < 200:
                        test_url = f"{base_url}{current_num}{extension}"

                        if test_url not in pages:
                            try:
                                resp = session.head(test_url, timeout=5)
                                if resp.status_code == 200:
                                    pages.append(test_url)
                                    consecutive_failures = 0
                                else:
                                    consecutive_failures += 1
                            except Exception:
                                consecutive_failures += 1
                            time.sleep(ENUM_DELAY)
                        else:
                            consecutive_failures = 0

                        current_num += 1
                    
                    # Sort by number
                    def get_num(url):
                        m = re.search(r'/(\\d+)\\.[a-z]+$', url, re.I)
                        return int(m.group(1)) if m else 0
                    
                    pages.sort(key=get_num)
            
            logger.info(f"Found {len(pages)} page images")
            return pages
            
        except Exception as e:
            logger.error(f"Error getting pages: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []
'''

def patch_file(filepath):
    print(f"Patching ManhuaTo get_pages in {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the ManhuaTo class and its get_pages method
    # Pattern to find the get_pages method in ManhuaTo class
    pattern = r'(class ManhuaToScraper.*?)(    def get_pages\(self, chapter: Chapter\).*?)(?=\n    def [a-z_]+\(self|class [A-Z]|\Z)'
    
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        print("Could not find ManhuaTo get_pages method")
        print("You may need to manually replace the get_pages method")
        return False
    
    # Replace the get_pages method
    old_method = match.group(2)
    new_content = content.replace(old_method, NEW_GET_PAGES + "\n")
    
    # Backup
    backup_path = filepath.with_suffix('.py.ads_backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Backup saved to {backup_path}")
    
    # Write new content
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("✓ Patched ManhuaTo get_pages with ad removal")
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1:
        filepath = Path(sys.argv[1])
    else:
        filepath = Path("manhwa_scraper.py")
        if not filepath.exists():
            filepath = Path("scripts/manhwa_scraper.py")
    
    if not filepath.exists():
        print(f"Error: Could not find {filepath}")
        sys.exit(1)
    
    patch_file(filepath)
