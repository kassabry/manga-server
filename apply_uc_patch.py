#!/usr/bin/env python3
"""
Patch script to add undetected-chromedriver support to manhwa_scraper.py

Usage:
    python apply_uc_patch.py /path/to/manhwa_scraper.py
"""

import sys
import re
from pathlib import Path

def patch_file(filepath):
    filepath = Path(filepath)
    
    if not filepath.exists():
        print(f"Error: File not found: {filepath}")
        return False
    
    # Read the file
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Backup
    backup_path = filepath.with_suffix('.py.bak')
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Backup saved to: {backup_path}")
    
    changes_made = 0
    
    # ===== PATCH 1: Add undetected-chromedriver import =====
    
    # Find the selenium import block
    selenium_import_pattern = r'(try:\s*\n\s*from selenium import webdriver.*?SELENIUM_AVAILABLE = True\s*\nexcept.*?SELENIUM_AVAILABLE = False)'
    
    new_selenium_import = '''try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
    
    # Try to import undetected-chromedriver for better bot detection bypass
    try:
        import undetected_chromedriver as uc
        UC_AVAILABLE = True
    except ImportError:
        UC_AVAILABLE = False
        
except ImportError:
    SELENIUM_AVAILABLE = False
    UC_AVAILABLE = False'''
    
    if 'UC_AVAILABLE' not in content:
        match = re.search(selenium_import_pattern, content, re.DOTALL)
        if match:
            content = content.replace(match.group(0), new_selenium_import)
            print("✓ Added undetected-chromedriver import")
            changes_made += 1
        else:
            # Try simpler approach - just add after SELENIUM_AVAILABLE = True
            if 'SELENIUM_AVAILABLE = True' in content and 'UC_AVAILABLE' not in content:
                old = 'SELENIUM_AVAILABLE = True'
                new = '''SELENIUM_AVAILABLE = True
    
    # Try to import undetected-chromedriver for better bot detection bypass
    try:
        import undetected_chromedriver as uc
        UC_AVAILABLE = True
    except ImportError:
        UC_AVAILABLE = False'''
                content = content.replace(old, new, 1)
                
                # Also need to add UC_AVAILABLE = False in the except block
                old2 = 'SELENIUM_AVAILABLE = False'
                new2 = '''SELENIUM_AVAILABLE = False
    UC_AVAILABLE = False'''
                content = content.replace(old2, new2, 1)
                print("✓ Added undetected-chromedriver import (simple method)")
                changes_made += 1
    else:
        print("  UC_AVAILABLE already defined, skipping import patch")
    
    # ===== PATCH 2: Add _detect_chrome_version method =====
    
    detect_chrome_method = '''
    def _detect_chrome_version(self):
        """Detect installed Chrome version for undetected-chromedriver compatibility"""
        import subprocess
        import re as regex
        try:
            # Windows - read from registry
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Google\\Chrome\\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            winreg.CloseKey(key)
            return int(version.split('.')[0])
        except:
            pass
        try:
            # Linux/Mac - run chrome --version
            result = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
            match = regex.search(r'(\\d+)\\.', result.stdout)
            if match:
                return int(match.group(1))
        except:
            pass
        return None

    def _inject_ad_blocker(self):
        """Inject JavaScript to block ads and popups"""
        try:
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': "window.open = function() { return null; }; if (Notification) { Notification.requestPermission = function() { return Promise.resolve('denied'); }; }"
            })
        except:
            pass
'''
    
    if '_detect_chrome_version' not in content:
        # Find a good place to insert - after _init_driver method or before it
        # Look for the class that contains _init_driver
        init_driver_match = re.search(r'(\n    def _init_driver\(self\):)', content)
        if init_driver_match:
            # Insert before _init_driver
            content = content.replace(init_driver_match.group(0), detect_chrome_method + init_driver_match.group(0))
            print("✓ Added _detect_chrome_version and _inject_ad_blocker methods")
            changes_made += 1
    else:
        print("  _detect_chrome_version already exists, skipping")
    
    # ===== PATCH 3: Update _init_driver to use undetected-chromedriver =====
    
    # Find the _init_driver method and replace it
    init_driver_pattern = r'def _init_driver\(self\):.*?(?=\n    def [a-z_]+\(self|\n\nclass |\Z)'
    
    new_init_driver = '''def _init_driver(self):
        """Initialize WebDriver with undetected-chromedriver if available"""
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium not available - install with: pip install selenium")
        if self.driver:
            return
        
        # Use undetected-chromedriver if available (much better at avoiding detection)
        if UC_AVAILABLE:
            logger.info("Using undetected-chromedriver")
            options = uc.ChromeOptions()
            
            if self.headless:
                options.add_argument('--headless=new')
            
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            
            # Block notifications and popups (anti-ad measures)
            options.add_argument('--disable-notifications')
            prefs = {
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_setting_values.popups": 2,
            }
            options.add_experimental_option("prefs", prefs)
            
            # Block known ad domains
            ad_domains = ["deshystria.com", "uncingle.com", "tragicuncy.com", "pushnow.net", "raposablie.com", "retileupfis.com", "popsmartblocker.pro"]
            block_rules = ",".join([f"MAP *.{d} 127.0.0.1, MAP {d} 127.0.0.1" for d in ad_domains])
            options.add_argument(f'--host-rules={block_rules}')
            
            try:
                # Detect Chrome version to avoid version mismatch errors
                chrome_version = self._detect_chrome_version()
                if chrome_version:
                    logger.info(f"Detected Chrome version: {chrome_version}")
                    self.driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_version)
                else:
                    self.driver = uc.Chrome(options=options, use_subprocess=True)
                
                # Inject ad-blocking script
                self._inject_ad_blocker()
                self.driver.implicitly_wait(10)
                return
                
            except Exception as e:
                logger.warning(f"undetected-chromedriver failed: {e}, falling back to regular selenium")
        
        # Fallback to regular selenium
        logger.info("Using regular selenium (undetected-chromedriver not available or failed)")
        options = Options()
        
        if self.headless:
            options.add_argument('--headless=new')
        
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-notifications')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        except Exception:
            self.driver = webdriver.Chrome(options=options)
        
        # Try to mask automation
        try:
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            })
        except:
            pass
        
        self.driver.implicitly_wait(10)

'''
    
    match = re.search(init_driver_pattern, content, re.DOTALL)
    if match:
        old_method = match.group(0)
        # Check if already patched
        if 'UC_AVAILABLE' in old_method:
            print("  _init_driver already patched, skipping")
        else:
            content = content.replace(old_method, new_init_driver)
            print("✓ Updated _init_driver to use undetected-chromedriver")
            changes_made += 1
    else:
        print("  Could not find _init_driver method")
    
    # Write patched file
    if changes_made > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n✓ Patch applied successfully! ({changes_made} changes)")
        print("\nTest with:")
        print(f'  python {filepath} --download-url "https://manhuato.com/manhua/eleceed" --chapters 1 --visible -o test')
    else:
        print("\nNo changes made - file may already be patched")
    
    return changes_made > 0

if __name__ == "__main__":
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        # Try common locations
        for path in ['manhwa_scraper.py', 'scripts/manhwa_scraper.py']:
            if Path(path).exists():
                filepath = path
                break
        else:
            print("Usage: python apply_uc_patch.py /path/to/manhwa_scraper.py")
            sys.exit(1)
    
    patch_file(filepath)
