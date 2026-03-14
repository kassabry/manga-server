# MangaShelf — Iteration Learnings

A running log of bugs found, root causes, and how they were fixed.
Reference this before making changes to avoid repeating past mistakes.

---

## 2026-03-14 — Scanner Wipes DB on Empty Library Mount

**Symptom:** After manhwa-downloader container went down, all series disappeared from orvault. AutoScan logs showed `+0 series, +0 chapters, 0 updated` every 30 minutes indefinitely.

**Root cause:** `cleanupDeletedSeries()` in `scanner.ts` receives `validLibraryPaths` (a Set built by walking the library). When the `/library` mount is temporarily unavailable, all `readdir` calls fail silently and the Set is empty. The cleanup then sees every DB entry as "missing" and deletes everything.

**Fix:** Added guard before calling cleanup — if `validLibraryPaths.size === 0`, log a warning and skip cleanup entirely. An empty library is almost certainly a mount issue, not mass deletion.

**File:** `mangashelf/src/lib/scanner.ts`

---

## 2026-03-14 — CBZ Outlier Filter Keeps Promo Covers Instead of Webtoon Strips

**Symptom:** Chapter 1 of "Revenge of the Iron-Blooded Sword Hound" (and similar series) displayed promo covers for other series instead of actual chapter pages.

**Root cause:** The outlier filter grouped images by width and kept the most-numerous group. A chapter had 4 webtoon strips (801px × ~15000px) and 9 promo images (2001px × ~2800px). The promo images "won" because they were more numerous, and the actual chapter strips were filtered out.

**Fix:** Extended `getImageDimensions` to return both width and height. Added webtoon strip detection: if a non-dominant group has avg aspect ratio ≥ 5:1 AND the dominant group has avg ratio ≤ 3:1, prefer the tall-strip group. Webtoon strips are always extremely tall (15:1+ ratio); promo covers are portrait (1.4:1).

**File:** `mangashelf/src/lib/cbz.ts`

---

## 2026-03-14 — FlameComics Chapter Numbers Show as 13, 23, 33 Instead of 1, 2, 3

**Symptom:** Academy's Genius Swordsman (scraped from FlameComics) showed chapters numbered 13, 23, 33, 43... instead of 1, 2, 3, 4...

**Root cause:** FlameComics renders chapter entries with the chapter number and timestamp as sibling inline elements: `<a>Chapter 1<span>3 years ago</span></a>`. BeautifulSoup's `get_text(strip=True)` concatenates text nodes without any separator, producing `"Chapter 13 years ago"`. The regex `chapter\s*(\d+)` then greedily matches `"13"` instead of `"1"`.

**Fix:** Changed `link.get_text(strip=True)` to `link.get_text(separator=' ', strip=True)` so the output becomes `"Chapter 1 3 years ago"` and the regex correctly captures `"1"`. Also added a fallback to look for specific chapter-number elements first.

**General rule:** Always use `separator=' '` with BeautifulSoup's `get_text()` when the result will be parsed with regex. Inline sibling elements have no natural separator.

**File:** `scripts/manhwa_scraper.py` — `FlameFullScraper.get_chapters()`

---

## 2026-03-14 — Database Lost After Docker Rebuild (First Deploy)

**Symptom:** After rebuilding the Docker image, users and all data were gone.

**Root cause:** `mangashelf/data/` was not tracked by git (gitignored entirely) so on a fresh clone or `git clean -fd`, the directory didn't exist. Docker created it as an empty directory on first run and `start.sh` initialized a fresh DB.

**Fix:**
- Added `mangashelf/data/.gitkeep` so the directory is always present after clone
- Changed `.gitignore` from `/data/` to `/data/*` + `!/data/.gitkeep`
- Added `.dockerignore` to exclude `data/`, `node_modules/`, `.next/` from build context
- Added startup check in `start.sh` that warns if User table is empty

**Note:** Regular `docker compose up --build` does NOT lose data — bind mounts persist on the host. Data is only lost on fresh clone without running `mkdir -p mangashelf/data` first.

**Files:** `mangashelf/.gitignore`, `mangashelf/.dockerignore`, `mangashelf/data/.gitkeep`, `mangashelf/start.sh`

---

## 2026-03-14 — Chapter Count Shows Sum Across Sources Instead of Max

**Symptom:** "The Tutorial is Too Hard" showed 524+ chapters when viewed with all sources, when the actual maximum from any single source was 524.

**Root cause:** `filteredChapters.length` when `sourceFilter === "all"` returns the total count across all sources (Asura + ManhuaTo = inflated number).

**Fix:** Added `displayChapterCount` — when showing all sources with multiple present, compute `Math.max(...uniqueSources.map(s => chapters from s))` instead of total length.

**File:** `mangashelf/src/app/series/[id]/page.tsx`

---

## General Patterns Learned

- **Scraper pagination:** All paginated scrapers (Asura, ManhuaTo, Drake) had hardcoded `page > 200` safety caps. Moved to `self.max_pages or 200` so `--pages N` CLI arg works for all sites.
- **FlameComics scroll:** Uses infinite scroll not pagination. `max_scrolls` now respects `self.max_pages`.
- **Drake 0 results:** If `div.bs` selector fails, try `div.bsx`, `.listupd article`, `article.item`, `div.utao`, `li.el` — common WP manga theme variants. Enable `--debug` to see page title/body classes.
- **`npx next build` is the pre-commit check** — catches TypeScript errors across all routes before pushing.
