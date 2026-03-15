# Code Security & Bug Review Report
Generated: 2026-03-14 21:42:00 UTC

## Files Reviewed
- `scripts/manhwa_scraper.py`
- `scripts/manhwa_downloader.py`
- `fix_href_whitespace.py`
- `fix_manhuato_comprehensive.py`
- `fix_manhuato_url.py`
- `fix_manhuato_urls_v2.py`
- `patch_manhuato_ads.py`
- `apply_uc_patch.py`
- `add_cookie_loading.py`
- `test_manhuato_requests.py`
- `test_uc_manhuato.py`

---

## CRITICAL: Pickle Deserialization — Remote Code Execution Risk

**Files:** `scripts/manhwa_scraper.py` (line 127), `add_cookie_loading.py` (line ~31), `scripts/manhwa_scraper.py` cookie loader

```python
# manhwa_scraper.py - ProgressTracker.load()
with open(self.cache_file, 'rb') as f:
    self.downloaded = pickle.load(f)  # UNSAFE

# add_cookie_loading.py - _load_manhuato_cookies()
with open(cookie_file, 'rb') as f:
    cookies = pickle.load(f)  # UNSAFE
```

**Risk:** `pickle.load()` on an untrusted file executes arbitrary Python code. Although these files are written by the script itself, they are stored in user-accessible directories (`test/`, `test_downloads/`, `scripts/`, project root). If any of these `.pkl` files are replaced by a malicious file (e.g., via a compromised download, path traversal, or social engineering), it will execute arbitrary code on the next run.

**Severity:** HIGH (code execution upon next script invocation)

**Recommendation:** Replace `pickle` with `json` for both the progress cache and cookie storage. Selenium cookies are JSON-serializable dicts.

---

## HIGH: Path Traversal in Filename Sanitization

**File:** `scripts/manhwa_downloader.py` (line 210), `scripts/manhwa_scraper.py` (same helper)

```python
@staticmethod
def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '', name)  # Does NOT remove '..' sequences
    name = re.sub(r'\s+', ' ', name)
    return name.strip()[:200]
```

**Risk:** The regex removes `\` and `/` individually but a series title like `..` (two dots) or a title containing OS-traversal sequences after stripping will remain. On Windows `Path(output_dir) / ".."` resolves to the parent directory. A scraper site returning a title like `.. Something` or crafting a title that after sanitization becomes `..` could write files outside the intended library path.

**Severity:** HIGH (potential directory traversal on malicious site data)

**Recommendation:** After sanitization, resolve the final path with `Path.resolve()` and assert it is still a child of the intended output directory.

---

## MEDIUM: No Domain Validation on Downloaded Image URLs

**Files:** `scripts/manhwa_downloader.py` (line 160–166), `scripts/manhwa_scraper.py` download logic, `patch_manhuato_ads.py`

```python
for i, page_url in enumerate(pages, 1):
    # page_url comes directly from scraped HTML with no domain whitelist
    if not self._download_image(page_url, img_path, chapter.url):
```

**Risk:** A compromised or malicious scraper site could serve `<img>` tags pointing to internal network resources (SSRF), or to very large files causing disk exhaustion. There is no size limit on downloads and no domain allowlisting.

**Severity:** MEDIUM

**Recommendation:** Validate that image URLs belong to the expected CDN domain before downloading. Add a `max_size` check during streaming download.

---

## MEDIUM: Bare `except: pass` Blocks — Silent Failures

**Files:** `scripts/manhwa_scraper.py` (multiple locations), `scripts/manhwa_downloader.py`

```python
try:
    self.driver.execute_cdp_cmd(...)
except:
    pass  # Swallows KeyboardInterrupt, SystemExit, MemoryError
```

**Count:** 15+ bare `except:` blocks across the scraper files.

**Risk:** Bare `except` catches `KeyboardInterrupt`, `SystemExit`, and `MemoryError`. Users cannot Ctrl+C out of certain operations. Critical failures are silently ignored, making debugging very difficult.

**Severity:** MEDIUM (operational reliability)

**Recommendation:** Replace `except:` with `except Exception:` throughout.

---

## MEDIUM: URL Substring Extension Detection (Incorrect File Extension)

**File:** `scripts/manhwa_downloader.py` (line 221–228)

```python
@staticmethod
def _get_extension(url: str) -> str:
    url_lower = url.lower()
    if '.png' in url_lower:   # Matches "notpng.phpx?x=.png" → wrongly returns .png
        return '.png'
    elif '.webp' in url_lower:
        return '.webp'
```

**Risk:** Checks for extension substring anywhere in the URL rather than in the path component only. A URL with a query parameter like `?format=.png.jpg` would return the wrong extension. More critically, `image.jpg?size=200x200.png` returns `.png` instead of `.jpg`.

**Severity:** LOW-MEDIUM (file corruption / CBZ reader issues)

**Recommendation:** Use `Path(urllib.parse.urlparse(url).path).suffix` or check only the URL path segment.

---

## MEDIUM: Image Enumeration Loop — Unthrottled HTTP Requests

**Files:** `patch_manhuato_ads.py` (line 114–133), `fix_manhuato_comprehensive.py` (line 206–230)

```python
while consecutive_failures < 3 and current_num < 200:
    test_url = f"{base_url}{current_num}{extension}"
    resp = session.head(test_url, timeout=5)   # No delay between requests
    current_num += 1
```

**Risk:** Makes up to 200 rapid-fire HTTP requests with no rate limiting. This will trigger IP bans on CDN services and is also the pattern of a DoS amplifier if the base URL is user-controlled.

**Severity:** MEDIUM (operational: IP ban; security: if base_url is attacker-controlled)

---

## LOW: FlareSolverr Cookie Session Poisoning

**File:** `scripts/manhwa_scraper.py` (line 283–293)

```python
def _apply_flaresolverr_cookies(self, cookies: list, user_agent: str = ""):
    for c in cookies:
        self.session.cookies.set(
            c["name"], c["value"],
            domain=c.get("domain", ""),   # Empty string if missing
        )
```

**Risk:** If FlareSolverr returns cookies without a domain (e.g., due to a malformed response), cookies with `domain=""` are set and may be sent to unintended hosts during the same session.

**Severity:** LOW

---

## LOW: Patch Scripts Use Fragile String Replacement on Source Files

**Files:** All `fix_*.py` and `apply_uc_patch.py` scripts

```python
content = content.replace(old, new)   # No count limit, no structural validation
```

**Risk:** The patch scripts modify source code by naive string replacement. If the target code has already been partially patched, or if whitespace differs, patches silently fail or apply incorrectly. There is no checksum or structural validation of the result, so a malformed file could be silently written.

**Severity:** LOW (developer tooling risk, not runtime security)

---

## LOW: `manhuato_cookies.pkl` in Project Root (Credential Storage)

**File:** `manhuato_cookies.pkl` (in project root and `scripts/`)

**Risk:** Pickle files containing authentication cookies are stored in the project root, outside the `scripts/` directory. These could be accidentally committed to git (though `library/` is gitignored, individual pickle files may not be). If committed, they expose authenticated session cookies.

**Severity:** LOW

**Recommendation:** Add `*.pkl` to `.gitignore` and store cookie files in a dedicated `~/.config/manga-server/` path.

---

## BUG: `download_from_url` Series Title — Falls Back to "Unknown"

**File:** `scripts/manhwa_downloader.py` (line 431–437)

```python
series = Series(title="Unknown", url=url, source="auto")
soup = scraper._get_soup(url, use_selenium=True)
title_elem = soup.select_one('h1, .entry-title, .post-title')
if title_elem:
    series.title = title_elem.get_text(strip=True)
```

**Bug:** If the title element is not found, the series directory is named `Unknown`, and all series downloaded via `--url` with failed title detection share the same directory, overwriting each other's CBZ files.

**Severity:** MEDIUM (data loss bug)

---

## BUG: `_create_cbz` Skips Files but Never Reports Partial Downloads

**File:** `scripts/manhwa_downloader.py` (line 199–204), `scripts/manhwa_scraper.py`

```python
def _create_cbz(self, source_dir: Path, output_path: Path):
    with zipfile.ZipFile(output_path, 'w', ...) as zf:
        for img_file in sorted(source_dir.iterdir()):
            if img_file.suffix.lower() in ['.jpg', ...]:
                zf.write(img_file, img_file.name)
# If 0 files match, an empty CBZ is written with no error
```

**Bug:** If all page downloads fail, an empty `.cbz` is still created and `cbz_path.exists()` returns `True` on the next run — permanently skipping the chapter without warning.

**Severity:** MEDIUM (silent data loss)

---

## BUG: `BaseSiteScraper._get_soup` — `use_selenium=False` path does not call `_delay()`

Wait, actually `_delay()` IS called at the top of `_get_soup`. This is correct. No bug here.

---

## Summary Table

| Severity | Issue | File(s) |
|----------|-------|---------|
| CRITICAL | Pickle deserialization (RCE) | `manhwa_scraper.py`, `add_cookie_loading.py` |
| HIGH | Path traversal via series title | `manhwa_downloader.py`, `manhwa_scraper.py` |
| MEDIUM | No image URL domain validation (SSRF/disk exhaustion) | Both scrapers |
| MEDIUM | Bare `except: pass` (15+ instances) | Both scrapers |
| MEDIUM | Empty CBZ on total page failure (silent data loss) | Both scrapers |
| MEDIUM | Series dir collision when title = "Unknown" | `manhwa_downloader.py` |
| MEDIUM | Unthrottled image enumeration loop | `patch_manhuato_ads.py`, `fix_manhuato_comprehensive.py` |
| LOW | URL extension detection by substring | `manhwa_downloader.py` |
| LOW | FlareSolverr cookie domain empty string | `manhwa_scraper.py` |
| LOW | Fragile string-replacement patch scripts | All `fix_*.py` files |
| LOW | `*.pkl` credential files not gitignored | Project root |
