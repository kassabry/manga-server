# File Change Log

This file records all files modified by Claude Code sessions, with timestamps.

---

## 2026-03-14 22:30:00 UTC — Test & Verification Session

Ran 23 automated tests against all changed logic. One regression caught and fixed.

### Files Modified

| File | Change | Timestamp |
|------|--------|-----------|
| `scripts/manhwa_scraper.py` | **BUG FIX (found in testing)** `_sanitize_filename`: chain `.lstrip('.').strip()` — without the second `.strip()`, input `".. evil"` produced `" evil"` (leading space) instead of `"evil"`, which would create a directory with a leading-space name. | 2026-03-14 22:30:00 UTC |
| `scripts/manhwa_downloader.py` | **BUG FIX (found in testing)** Same `.lstrip('.').strip()` fix as above. | 2026-03-14 22:30:00 UTC |

### Test Results

| Suite | Cases | Result |
|-------|-------|--------|
| `_sanitize_filename` — traversal, null bytes, dots, unicode, length cap | 11 | ✅ All pass |
| `_get_extension` — plain URLs, query-string traps, no-extension | 8 | ✅ All pass |
| `ProgressTracker` JSON round-trip | 1 | ✅ Pass |
| Path traversal guard (`relative_to` assertion) | 2 | ✅ All pass |
| Syntax check — all 5 modified `.py` files | 5 | ✅ All pass |

---

## 2026-03-14 22:10:00 UTC — Security & Bug Fix Session

All issues identified in the code review were remediated.

### Files Modified

| File | Change | Timestamp |
|------|--------|-----------|
| `scripts/manhwa_scraper.py` | **CRITICAL** Replace `pickle` with `json` in `ProgressTracker` (with one-time migration from old `.pkl`); add `import json`, remove top-level `import pickle`. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_scraper.py` | **CRITICAL** Replace `pickle.load()` with `json.load()` for ManhuaTo cookie loading in `get_pages`. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_scraper.py` | **HIGH** Fix `_sanitize_filename`: strip null bytes, strip leading dots (prevents `..` traversal), return `_unnamed` for empty result. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_scraper.py` | **HIGH** Add path-traversal guard in `download_chapter`: assert `series_dir` resolves inside `output_dir`. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_scraper.py` | **MEDIUM** Replace all 20 bare `except:` blocks with `except Exception:`. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_scraper.py` | **MEDIUM** Add 0.3s rate-limiting delay to ManhuaTo image-enumeration loop. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_scraper.py` | **LOW** Fix `_get_extension`: use `urlparse` + `PurePosixPath.suffix` instead of substring search. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_scraper.py` | **LOW** Fix `_apply_flaresolverr_cookies`: skip cookies with empty domain. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_downloader.py` | **HIGH** Fix `_sanitize_filename`: strip null bytes, leading dots; return `_unnamed` for empty result. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_downloader.py` | **HIGH** Add path-traversal guard in `download_chapter`. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_downloader.py` | **MEDIUM** Add image domain allowlist (`_ALLOWED_IMAGE_DOMAINS`, `_is_allowed_image_url`) and 50 MB size cap in `_download_image`. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_downloader.py` | **MEDIUM** Track `success_count` in `download_chapter`; abort CBZ creation and return `False` if zero images downloaded. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_downloader.py` | **MEDIUM** Fix `download_from_url`: fall back to URL-slug title instead of `"Unknown"` when title detection fails. | 2026-03-14 22:10:00 UTC |
| `scripts/manhwa_downloader.py` | **LOW** Fix `_get_extension`: use `urlparse` + `PurePosixPath.suffix`. | 2026-03-14 22:10:00 UTC |
| `add_cookie_loading.py` | **CRITICAL** Replace `pickle.load()` with `json.load()` and update cookie filename to `manhuato_cookies.json`. | 2026-03-14 22:10:00 UTC |
| `patch_manhuato_ads.py` | **MEDIUM** Add 0.3s rate-limiting delay to image-enumeration loop; replace bare `except:` with `except Exception:`. | 2026-03-14 22:10:00 UTC |
| `fix_manhuato_comprehensive.py` | **MEDIUM** Add 0.3s rate-limiting delay to image-enumeration loop; replace bare `except:` with `except Exception:`. | 2026-03-14 22:10:00 UTC |
| `.gitignore` | **LOW** Add `manhuato_cookies.json` to the credentials ignore section. | 2026-03-14 22:10:00 UTC |

### Files Created

| File | Action | Timestamp |
|------|--------|-----------|
| `CODE_REVIEW_REPORT.md` | CREATED | 2026-03-14 21:42:00 UTC |
| `CHANGES.md` | CREATED | 2026-03-14 21:42:00 UTC |

---

## 2026-03-14 21:42:00 UTC — Code Review Session

_Review only — no source files were changed._

---

_Future entries should be appended above this line in reverse-chronological order._
