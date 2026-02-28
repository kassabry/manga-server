#!/usr/bin/env python3
"""
Test script to verify undetected-chromedriver works with ManhuaTo.
Run this first before patching your full scraper.

Usage:
    python test_uc_manhuato.py
    python test_uc_manhuato.py --headless  # Run without visible browser
    
After manual verification, cookies are saved to manhuato_cookies.pkl
and will be reused in future runs.
"""

import sys
import time
import subprocess
import re
import pickle
import requests
from pathlib import Path

from bs4 import BeautifulSoup

COOKIE_FILE = Path("manhuato_cookies.pkl")

try:
    import undetected_chromedriver as uc
    print("✓ undetected_chromedriver imported successfully")
except ImportError:
    print("✗ undetected_chromedriver not installed!")
    print("  Install with: pip install undetected-chromedriver")
    sys.exit(1)

def save_cookies(driver):
    """Save cookies to file for future sessions"""
    cookies = driver.get_cookies()
    with open(COOKIE_FILE, 'wb') as f:
        pickle.dump(cookies, f)
    print(f"✓ Saved {len(cookies)} cookies to {COOKIE_FILE}")

def load_cookies(driver):
    """Load cookies from file if available"""
    if not COOKIE_FILE.exists():
        return False
    try:
        with open(COOKIE_FILE, 'rb') as f:
            cookies = pickle.load(f)
        # First navigate to the domain so we can set cookies
        driver.get("https://manhuato.com")
        time.sleep(1)
        for cookie in cookies:
            try:
                driver.add_cookie(cookie)
            except:
                pass  # Some cookies may fail to add
        print(f"✓ Loaded {len(cookies)} cookies from {COOKIE_FILE}")
        return True
    except Exception as e:
        print(f"⚠ Could not load cookies: {e}")
        return False

def get_chrome_version():
    """Detect installed Chrome version"""
    try:
        # Windows
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
        version, _ = winreg.QueryValueEx(key, "version")
        winreg.CloseKey(key)
        major = int(version.split('.')[0])
        print(f"✓ Detected Chrome version: {version} (major: {major})")
        return major
    except:
        pass
    
    try:
        # Try command line (works on Linux/Mac)
        result = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
        match = re.search(r'(\d+)\.', result.stdout)
        if match:
            major = int(match.group(1))
            print(f"✓ Detected Chrome version: {major}")
            return major
    except:
        pass
    
    print("⚠ Could not detect Chrome version, will try auto-detect")
    return None

def test_manhuato(headless=False, test_chapter=None):
    print("\n--- Testing ManhuaTo with undetected-chromedriver ---\n")
    
    # Detect Chrome version
    chrome_version = get_chrome_version()
    
    # Series page URL - we'll find chapter 1 from here (just like the scraper does)
    series_url = "https://manhuato.com/manhua/eleceed"
    
    # If a specific chapter URL was provided, use that
    specific_chapter_url = test_chapter
    
    options = uc.ChromeOptions()
    if headless:
        options.add_argument('--headless=new')
    
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    
    # Block notification prompts (the "Allow notifications" scam)
    options.add_argument('--disable-notifications')
    
    # Block popups
    options.add_argument('--disable-popup-blocking')  # We'll handle popups ourselves
    
    # Set preferences to block notifications and popups
    prefs = {
        "profile.default_content_setting_values.notifications": 2,  # 2 = Block
        "profile.default_content_setting_values.popups": 2,  # 2 = Block
        "profile.default_content_setting_values.automatic_downloads": 2,  # Block auto downloads
    }
    options.add_experimental_option("prefs", prefs)
    
    # Block known ad/scam domains
    ad_domains = [
        "deshystria.com",
        "uncingle.com",
        "tragicuncy.com",
        "pushnow.net",
        "pushwelcome.com",
        "push-notification.com",
        "raposablie.com",
        "retileupfis.com",
        "pushance.com",
        "notifpushing.com",
        "pushnext.com",
        "popsmartblocker.pro",
        "shein.com",
        "sheincorp.cn",
    ]
    # Create host rules to block these domains (including subdomains)
    block_rules = ",".join([f"MAP *.{domain} 127.0.0.1, MAP {domain} 127.0.0.1" for domain in ad_domains])
    options.add_argument(f'--host-rules={block_rules}')
    
    print(f"Starting Chrome (headless={headless})...")
    print(f"  Blocking {len(ad_domains)} known ad domains")
    
    try:
        # Specify version_main to match your Chrome version
        if chrome_version:
            driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_version)
        else:
            driver = uc.Chrome(options=options, use_subprocess=True)
        print("✓ Chrome started successfully")
    except Exception as e:
        print(f"✗ Failed to start Chrome: {e}")
        return False
    
    try:
        # Try to load saved cookies first
        cookies_loaded = load_cookies(driver)
        
        # Inject ad-blocking script that runs on every page
        ad_block_script = """
        // Block ad-related functions
        window.open = function() { return null; };  // Block popups
        
        // Block notification requests
        if (Notification) {
            Notification.requestPermission = function() { 
                return Promise.resolve('denied'); 
            };
        }
        
        // Block redirects to known ad domains
        var adDomains = ['deshystria', 'uncingle', 'tragicuncy', 'pushnow', 'pushwelcome',
                         'popads', 'popcash', 'propellerads', 'adsterra', 'exoclick',
                         'juicyads', 'trafficjunky', 'clickadu', 'hilltopads', 'raposablie',
                         'popsmartblocker', 'shein', 'retileupfis'];
        
        // Override location assignment to block ad redirects
        var originalLocation = window.location.href;
        var locationDescriptor = Object.getOwnPropertyDescriptor(window, 'location');
        
        // Block location.href changes to ad sites
        var checkAndBlock = function(url) {
            if (typeof url === 'string') {
                var urlLower = url.toLowerCase();
                for (var i = 0; i < adDomains.length; i++) {
                    if (urlLower.indexOf(adDomains[i]) !== -1) {
                        console.log('Blocked redirect to:', url);
                        return true;
                    }
                }
                // Also block if not manhuato.com
                if (urlLower.indexOf('manhuato.com') === -1 && 
                    urlLower.indexOf('about:blank') === -1 &&
                    !urlLower.startsWith('javascript:')) {
                    console.log('Blocked external redirect to:', url);
                    return true;
                }
            }
            return false;
        };
        
        // Block location.assign and location.replace
        var origAssign = window.location.assign;
        var origReplace = window.location.replace;
        window.location.assign = function(url) {
            if (!checkAndBlock(url)) origAssign.call(window.location, url);
        };
        window.location.replace = function(url) {
            if (!checkAndBlock(url)) origReplace.call(window.location, url);
        };
        
        // Block setTimeout/setInterval that might do redirects
        var origSetTimeout = window.setTimeout;
        window.setTimeout = function(fn, delay) {
            if (typeof fn === 'string' && (fn.indexOf('location') !== -1 || fn.indexOf('href') !== -1)) {
                console.log('Blocked suspicious setTimeout');
                return 0;
            }
            return origSetTimeout.apply(window, arguments);
        };
        
        // Override createElement to block ad scripts
        var originalCreateElement = document.createElement;
        document.createElement = function(tagName) {
            var element = originalCreateElement.call(document, tagName);
            if (tagName.toLowerCase() === 'script') {
                var originalSetAttribute = element.setAttribute;
                element.setAttribute = function(name, value) {
                    if (name === 'src' && adDomains.some(function(p) { return value.indexOf(p) !== -1; })) {
                        console.log('Blocked ad script:', value);
                        return;
                    }
                    return originalSetAttribute.call(element, name, value);
                };
            }
            return element;
        };
        
        // Block onclick handlers that open ads
        document.addEventListener('click', function(e) {
            var target = e.target;
            while (target && target !== document) {
                if (target.onclick && target.onclick.toString().indexOf('window.open') !== -1) {
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('Blocked ad click');
                    return false;
                }
                target = target.parentElement;
            }
        }, true);
        """
        
        try:
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': ad_block_script
            })
            print("✓ Injected ad-blocking script")
        except Exception as e:
            print(f"⚠ Could not inject ad-blocking script: {e}")
        
        # Step 1: Go to series page and find chapter 1 URL (like the scraper does)
        # Skip if a specific chapter URL was provided
        if specific_chapter_url:
            chapter_1_url = specific_chapter_url
            print(f"\nStep 1: Using provided chapter URL: {chapter_1_url}")
        else:
            print(f"\nStep 1: Finding chapter URL from series page...")
            print(f"Navigating to: {series_url}")
            driver.get(series_url)
            
            print("Waiting for page load...")
            time.sleep(3)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Find chapter links (same selector as scraper)
            chapter_links = soup.select('a[href*="-chapter-"]')
            print(f"Found {len(chapter_links)} chapter links")
            
            if not chapter_links:
                print("✗ No chapter links found on series page!")
                print("  This might mean bot detection is blocking the series page.")
                return False
            
            # Find chapter 1 (it's usually near the end since chapters are listed newest-first)
            chapter_1_url = None
            for link in chapter_links:
                href = link.get('href', '').strip()  # Strip whitespace!
                # Match chapter-1 followed by non-digit (to avoid matching chapter-10, chapter-100, etc.)
                if re.search(r'chapter-1(?!\d)', href.lower()):
                    if href.startswith('http'):
                        chapter_1_url = href
                    elif href.startswith('/'):
                        chapter_1_url = f"https://manhuato.com{href}"
                    else:
                        chapter_1_url = f"https://manhuato.com/{href}"
                    break
            
            if not chapter_1_url:
                # Just use the last chapter (oldest)
                href = chapter_links[-1].get('href', '').strip()
                if href.startswith('http'):
                    chapter_1_url = href
                elif href.startswith('/'):
                    chapter_1_url = f"https://manhuato.com{href}"
                else:
                    chapter_1_url = f"https://manhuato.com/{href}"
                print(f"  Could not find chapter 1 specifically, using: {chapter_1_url}")
            else:
                print(f"✓ Found chapter 1: {chapter_1_url}")
        
        # Step 2: Navigate to the chapter page
        print(f"\nStep 2: Loading chapter page...")
        print(f"Navigating to: {chapter_1_url}")
        
        # Navigate with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                driver.get(chapter_1_url)
                time.sleep(2)
                
                # Quick check if we're on the right page
                current_url = driver.current_url.lower()
                if 'manhuato.com' in current_url and 'chapter' in current_url:
                    print(f"✓ Successfully loaded chapter page (attempt {attempt + 1})")
                    break
                elif 'manhuato.com' not in current_url:
                    print(f"  Attempt {attempt + 1}: Redirected to {current_url[:50]}... Retrying...")
                    time.sleep(1)
                    continue
            except Exception as e:
                print(f"  Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    print("  Retrying...")
                    time.sleep(2)
                    continue
                else:
                    raise
        
        print("Waiting for page to stabilize...")
        time.sleep(2)
        
        # Check for bot detection and try to bypass it
        page_source = driver.page_source.lower()
        
        # Check if we're on an ad/scam page (redirected away from manhuato)
        current_url = driver.current_url.lower()
        if 'manhuato.com' not in current_url:
            print(f"\n⚠ Redirected to ad page: {current_url[:60]}...")
            print("  The site has aggressive redirect ads.")
            print("  Attempting to navigate back...")
            
            # Try a fresh navigation
            try:
                driver.get(chapter_1_url)
                time.sleep(3)
            except Exception as e:
                print(f"  Navigation failed: {e}")
                print("  Will try to extract what we can from current page...")
        
        # Remove ad overlays via JavaScript (even if on wrong page)
        print("\nRemoving ad overlays...")
        remove_overlay_js = """
        // Remove common ad overlay elements
        var selectors = [
            '[class*="overlay"]',
            '[class*="popup"]',
            '[class*="modal"]',
            '[id*="overlay"]',
            '[id*="popup"]',
            '[id*="modal"]',
            '[class*="ad-"]',
            '[id*="ad-"]',
            'iframe[src*="ad"]',
            'div[onclick]',  // Divs with click handlers (often ad traps)
            '[class*="verify"]',
            '[id*="verify"]',
        ];
        
        var removed = 0;
        selectors.forEach(function(sel) {
            try {
                document.querySelectorAll(sel).forEach(function(el) {
                    // Don't remove the actual content
                    if (!el.querySelector('img[src*="chapter"]') && 
                        !el.querySelector('img[src*="cdn"]') &&
                        !el.classList.contains('reading-content')) {
                        el.remove();
                        removed++;
                    }
                });
            } catch(e) {}
        });
        
        // Remove any full-screen overlays
        document.querySelectorAll('div').forEach(function(el) {
            var style = window.getComputedStyle(el);
            if (style.position === 'fixed' && 
                (style.zIndex > 1000 || style.width === '100%' || style.height === '100%')) {
                if (!el.querySelector('img')) {
                    el.remove();
                    removed++;
                }
            }
        });
        
        // Re-enable scrolling if disabled
        document.body.style.overflow = 'auto';
        document.documentElement.style.overflow = 'auto';
        
        return removed;
        """
        
        try:
            removed = driver.execute_script(remove_overlay_js)
            print(f"  Removed {removed} overlay elements")
        except Exception as e:
            print(f"  Could not remove overlays: {e}")
        
        time.sleep(1)
        
        # Close any popup windows that opened
        original_window = driver.current_window_handle
        if len(driver.window_handles) > 1:
            print(f"  Closing {len(driver.window_handles) - 1} popup window(s)...")
            for window in driver.window_handles:
                if window != original_window:
                    try:
                        driver.switch_to.window(window)
                        driver.close()
                    except:
                        pass
            driver.switch_to.window(original_window)
        
        # Check again if we got redirected
        current_url = driver.current_url.lower()
        if 'manhuato.com' not in current_url:
            print(f"  Still on wrong page ({current_url[:40]}...), trying fresh navigation...")
            try:
                driver.get(chapter_1_url)
                time.sleep(3)
            except Exception as e:
                print(f"  Could not navigate: {e}")
        
        # Step 3: Try to find images BEFORE scrolling (scrolling often triggers ad redirects)
        print("\nStep 3: Searching for chapter images...")
        
        # First, force lazy images to reveal their URLs via JavaScript
        try:
            driver.execute_script("""
                // Log all images with lazy load attributes
                document.querySelectorAll('img').forEach(function(img) {
                    console.log('IMG:', img.src, img.dataset.src, img.dataset.original, img.dataset.lazySrc);
                });
            """)
        except:
            pass
        
        # First, try to extract images WITHOUT scrolling
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        all_imgs = soup.select('img')
        print(f"Total <img> tags found initially: {len(all_imgs)}")
        
        # Look for actual chapter images
        chapter_images = []
        for img in all_imgs:
            src = img.get('data-original') or img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
            if src and not src.startswith('data:'):
                src_lower = src.lower()
                # Skip obvious non-chapter images
                if any(skip in src_lower for skip in ['logo', 'icon', 'avatar', 'banner', 'ad', 'thumb', 'game']):
                    continue
                # Include likely chapter images
                if any(inc in src_lower for inc in ['chapter', 'manhua', 'uploads', 'cdn', 'wp-content', 'media']) or \
                   any(ext in src_lower for ext in ['.jpg', '.png', '.webp']):
                    if src not in chapter_images:
                        chapter_images.append(src)
        
        print(f"Chapter images found (before scroll): {len(chapter_images)}")
        
        # If we found images, we might not need to scroll at all
        if len(chapter_images) >= 5:
            print("✓ Found enough images without scrolling - skipping scroll to avoid ad triggers")
        else:
            # Only scroll if we need more images, and do it carefully
            print("Need more images, attempting careful scroll...")
            
            try:
                # Store original URL to detect redirects
                original_url = driver.current_url
                
                # Remove ad overlay elements first
                remove_overlay_js = """
                var removed = 0;
                document.querySelectorAll('div, section, aside').forEach(function(el) {
                    var style = window.getComputedStyle(el);
                    if ((style.position === 'fixed' || style.position === 'absolute') && 
                        parseInt(style.zIndex) > 100) {
                        if (!el.querySelector('img[src*="chapter"]') && 
                            !el.querySelector('img[src*="cdn"]') &&
                            !el.querySelector('img[src*="uploads"]')) {
                            el.remove();
                            removed++;
                        }
                    }
                });
                // Remove onclick handlers (ad traps)
                document.querySelectorAll('[onclick]').forEach(function(el) {
                    el.removeAttribute('onclick');
                });
                // Remove event listeners that might trigger ads
                document.querySelectorAll('a[href*="click"], a[target="_blank"]').forEach(function(el) {
                    if (!el.querySelector('img')) {
                        el.remove();
                        removed++;
                    }
                });
                document.body.style.overflow = 'auto';
                return removed;
                """
                
                try:
                    removed = driver.execute_script(remove_overlay_js)
                    if removed > 0:
                        print(f"  Removed {removed} potential ad elements")
                except:
                    pass
                
                # Scroll using JavaScript (safer than ActionChains)
                for i in range(3):
                    # Check if we got redirected
                    if 'manhuato.com' not in driver.current_url.lower():
                        print(f"  ⚠ Redirected to ad! Will use images found so far...")
                        break
                    
                    try:
                        driver.execute_script(f"window.scrollBy(0, 800);")
                        time.sleep(0.5)
                    except:
                        break
                
                # Scroll back to top
                try:
                    driver.execute_script("window.scrollTo(0, 0);")
                except:
                    pass
                    
            except Exception as e:
                print(f"  Scroll section error: {e}")
        
        # Re-parse after scrolling (if we scrolled)
        if len(chapter_images) < 5:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            all_imgs = soup.select('img')
            
            # Force lazy images to load via JavaScript
            try:
                driver.execute_script("""
                    document.querySelectorAll('img').forEach(function(img) {
                        if (img.dataset.src) img.src = img.dataset.src;
                        if (img.dataset.original) img.src = img.dataset.original;
                        if (img.dataset.lazySrc) img.src = img.dataset.lazySrc;
                    });
                """)
                time.sleep(1)
                soup = BeautifulSoup(driver.page_source, 'html.parser')
            except:
                pass
            
            # Re-scan for images
            for img in soup.select('img'):
                src = img.get('data-original') or img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
                if src and not src.startswith('data:'):
                    src_lower = src.lower()
                    if any(skip in src_lower for skip in ['logo', 'icon', 'avatar', 'banner', 'ad', 'thumb', 'game']):
                        continue
                    if any(inc in src_lower for inc in ['chapter', 'manhua', 'uploads', 'cdn', 'wp-content', 'media']) or \
                       any(ext in src_lower for ext in ['.jpg', '.png', '.webp']):
                        if src not in chapter_images:
                            chapter_images.append(src)
        
        print(f"\nFinal chapter images found: {len(chapter_images)}")
        
        # Try to enumerate more images based on URL pattern
        if chapter_images:
            print("\nStep 4: Enumerating additional images based on URL pattern...")
            
            # Detect pattern from found images
            # Pattern like: https://cdn.manhuato.com/images/manga/eleceed/chapter-1/0.png
            base_url = None
            extension = None
            max_found = -1
            
            for img_url in chapter_images:
                # Look for numbered images
                match = re.search(r'(.+/)(\d+)(\.[a-z]+)$', img_url, re.I)
                if match:
                    base_url = match.group(1)
                    num = int(match.group(2))
                    extension = match.group(3)
                    if num > max_found:
                        max_found = num
            
            if base_url and extension:
                print(f"  Detected pattern: {base_url}[NUMBER]{extension}")
                print(f"  Highest image number found so far: {max_found}")
                
                # Try to find more images by incrementing
                session = requests.Session()
                
                # Get cookies from the browser
                try:
                    browser_cookies = driver.get_cookies()
                    for cookie in browser_cookies:
                        session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))
                    print(f"  Using {len(browser_cookies)} cookies from browser")
                except:
                    print("  Could not get browser cookies")
                
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': chapter_1_url,  # Use actual chapter URL as referer
                    'Origin': 'https://manhuato.com',
                })
                
                # Start from max_found + 1 and keep going until we get failures
                consecutive_failures = 0
                current_num = max_found + 1
                found_new = 0
                
                print(f"  Checking for images starting from {current_num}...")
                
                while consecutive_failures < 5:  # Stop after 5 consecutive failures (more lenient)
                    test_url = f"{base_url}{current_num}{extension}"
                    
                    try:
                        # Use GET instead of HEAD - some CDNs don't respond to HEAD
                        resp = session.get(test_url, timeout=10, stream=True)
                        
                        # Check if it's actually an image
                        content_type = resp.headers.get('Content-Type', '')
                        content_length = int(resp.headers.get('Content-Length', 0))
                        
                        # Debug: show what we're getting
                        if current_num < max_found + 10:  # Show first few attempts
                            print(f"    Image {current_num}: status={resp.status_code}, type={content_type[:30] if content_type else 'none'}, len={content_length}")
                        
                        if resp.status_code == 200 and ('image' in content_type or content_length > 1000):
                            if test_url not in chapter_images:
                                chapter_images.append(test_url)
                                found_new += 1
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                        
                        # Close the stream without downloading full content
                        resp.close()
                        
                    except requests.exceptions.RequestException as e:
                        if current_num < max_found + 10:
                            print(f"    Image {current_num}: error - {e}")
                        consecutive_failures += 1
                    
                    current_num += 1
                    
                    # Safety limit
                    if current_num > 500:
                        print(f"  Reached safety limit at image {current_num}")
                        break
                
                print(f"  Found {found_new} additional images (checked up to {current_num - 1})")
                
                # Also check for images we might have missed (0 to max_found)
                for i in range(max_found + 1):
                    test_url = f"{base_url}{i}{extension}"
                    if test_url not in chapter_images:
                        try:
                            resp = session.get(test_url, timeout=10, stream=True)
                            content_type = resp.headers.get('Content-Type', '')
                            if resp.status_code == 200 and 'image' in content_type:
                                chapter_images.append(test_url)
                                found_new += 1
                            resp.close()
                        except:
                            pass
                
                # Sort images by number
                def get_num(url):
                    match = re.search(r'/(\d+)\.[a-z]+$', url, re.I)
                    return int(match.group(1)) if match else 0
                
                chapter_images.sort(key=get_num)
                
                print(f"  Total images after enumeration: {len(chapter_images)}")
        
        # If no images found, try waiting longer and triggering lazy load via JS only (no scrolling)
        if not chapter_images:
            print("\nNo images found yet, trying JavaScript-based image loading...")
            
            # Try to trigger image loading via JavaScript (safer than scrolling)
            try:
                driver.execute_script("""
                    // Force all lazy images to load
                    document.querySelectorAll('img').forEach(function(img) {
                        if (img.dataset.src) img.src = img.dataset.src;
                        if (img.dataset.original) img.src = img.dataset.original;
                        if (img.dataset.lazySrc) img.src = img.dataset.lazySrc;
                        // Trigger load event
                        img.loading = 'eager';
                    });
                """)
            except Exception as e:
                print(f"  JS injection failed: {e}")
            
            time.sleep(2)
            
            # Re-parse only if we're still on manhuato
            try:
                if 'manhuato.com' in driver.current_url.lower():
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    all_imgs = soup.select('img')
                    
                    for img in all_imgs:
                        src = img.get('data-original') or img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
                        if src and not src.startswith('data:'):
                            src_lower = src.lower()
                            if any(skip in src_lower for skip in ['logo', 'icon', 'avatar', 'banner', 'ad', 'thumb', 'game']):
                                continue
                            if any(inc in src_lower for inc in ['chapter', 'manhua', 'uploads', 'cdn', 'wp-content', 'media']) or \
                               any(ext in src_lower for ext in ['.jpg', '.png', '.webp']):
                                if src not in chapter_images:
                                    chapter_images.append(src)
                    
                    print(f"After JS loading: {len(chapter_images)} images found")
                else:
                    print("  Got redirected, skipping JS loading")
            except Exception as e:
                print(f"  Error during JS loading: {e}")
        
        if chapter_images:
            print("\n✓ SUCCESS! Found chapter images:")
            for i, img in enumerate(chapter_images[:5], 1):
                print(f"  {i}. {img[:80]}...")
            if len(chapter_images) > 5:
                print(f"  ... and {len(chapter_images) - 5} more")
            
            # Save cookies for future use
            save_cookies(driver)
            
            success = True
        else:
            # Check if we're on an ad page
            current_url = driver.current_url.lower()
            if 'manhuato.com' not in current_url:
                print(f"\n✗ Got redirected to ad page: {current_url[:60]}...")
                print("  The site has very aggressive ads that redirect before content loads.")
                print("\n  WORKAROUND OPTIONS:")
                print("  1. Try a different manga reader site (Asura, Flame, Webtoon)")
                print("  2. Use a browser with uBlock Origin to access manhuato.com manually")
                print("  3. Use an ad-blocking DNS like NextDNS or Pi-hole")
            else:
                print("\n✗ No chapter images found!")
                print("  This could mean:")
                print("  1. Bot detection is blocking image loading")
                print("  2. The page structure has changed")
                print("  3. Images are loaded by JavaScript that hasn't executed")
            
            # Show what we did find
            print("\nAll image sources found on page:")
            try:
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                for img in soup.select('img')[:10]:
                    src = img.get('src', img.get('data-src', 'no-src'))
                    print(f"  - {src[:60]}...")
            except:
                print("  Could not parse page")
            
            success = False
        
        if not headless:
            print("\n--- Browser will stay open for 10 seconds so you can inspect ---")
            time.sleep(10)
        
        return success
        
    except Exception as e:
        print(f"\n✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        print("\nClosing browser...")
        driver.quit()

if __name__ == "__main__":
    headless = '--headless' in sys.argv
    manual_mode = '--manual' in sys.argv
    
    # Allow specifying a different chapter to test
    test_chapter = None
    for arg in sys.argv:
        if arg.startswith('--chapter='):
            test_chapter = arg.split('=')[1]
    
    # Option to clear saved cookies
    if '--clear-cookies' in sys.argv:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
            print("✓ Cleared saved cookies")
        else:
            print("No saved cookies to clear")
        if len(sys.argv) == 2:  # Only --clear-cookies was passed
            sys.exit(0)
    
    if manual_mode:
        print("\n=== MANUAL MODE ===")
        print("In manual mode, the script will pause to let you interact with the browser.")
        print("This helps with sites that have aggressive ad redirects.")
        print("")
    
    if test_chapter:
        print(f"\n=== Testing specific chapter: {test_chapter} ===\n")
    
    success = test_manhuato(headless, test_chapter)
    
    print("\n" + "="*50)
    if success:
        print("TEST PASSED! undetected-chromedriver works with ManhuaTo")
        print(f"\nCookies saved to {COOKIE_FILE}")
        print("Future runs will use these cookies to skip verification.")
        print("\nNow you can either:")
        print("  1. Run: python apply_uc_patch.py scripts/manhwa_scraper.py")
        print("  2. Or manually update your scraper (see instructions)")
    else:
        print("TEST FAILED!")
        print("\nManhuaTo has very aggressive ad redirects that are difficult to bypass.")
        print("\nRECOMMENDED ALTERNATIVES:")
        print("  1. Use different sites: Asura, Flame, or Webtoon work better")
        print("  2. Install uBlock Origin in your regular Chrome and browse manually")
        print("  3. Use a Pi-hole or NextDNS to block ad domains at network level")
        print("\nOther options:")
        print("  --clear-cookies  : Delete saved cookies and start fresh")
        print("  --manual        : Pause for manual interaction")
    print("="*50)
