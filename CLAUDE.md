# MangaShelf — Claude Working Notes

## Project Layout
- Repo root: `manga-server-full/` (git root)
- Next.js app: `mangashelf/` — build: `cd mangashelf && npx next build`
- Scrapers: `scripts/manhwa_scraper.py`, `scripts/lightnovel_scraper.py`
- Library: `library/{Manga,Manhwa,Manhua,LightNovels}/` — CBZ + EPUB files
- Docker entry: `docker-compose.yml` at repo root; app container named `orvault`

## Stack Constraints
- Prisma 6 only — Prisma 7 removes `url` in datasource, do not upgrade
- Next.js 16 with App Router — use `new Uint8Array(buffer)` not `Buffer` in NextResponse body
- Auth.js v5 beta (`next-auth@5.0.0-beta`) — session shape differs from stable docs
- Node 24 on Windows host; `node:22-alpine` in Docker image
- `package.json` requires `"type": "module"` for App Router

## Docker / Data Persistence
- DB at `mangashelf/data/mangashelf.db` via bind mount `./mangashelf/data:/app/data`
- Bind mounts survive `docker compose up --build` and `docker compose down`
- Data only lost if host `data/` dir is deleted (e.g. `git clean -fd` or fresh clone)
- `.gitkeep` keeps `data/` tracked; `.dockerignore` excludes it from build context
- `start.sh` logs `WARNING: Database has 0 users` on startup if DB is empty
- Library mount `./library:/library:ro` is independent of other containers

## Scanner (`src/lib/scanner.ts`)
- CRITICAL SAFETY: skip `cleanupDeletedSeries()` entirely if `validLibraryPaths.size === 0` — an empty set means the mount is unavailable, not that all series were deleted. Without this guard, a temporary mount failure wipes the entire DB.
- Cleanup deletes series/chapters whose `libraryPath` is no longer found on disk
- `SeriesPath` table tracks multiple source directories per merged series

## CBZ Reader (`src/lib/cbz.ts`)
- Files with "cover" in the name are excluded from the page list in `getPageList`
- `filterOutlierImages` reads both width+height from raw headers (no external deps)
- Webtoon detection: if a non-dominant group has avg aspect ratio ≥ 5:1 and the dominant group is ≤ 3:1, prefer the tall-strip group — promo covers from other series tend to be portrait images that outnumber the actual webtoon strips
- Page list is LRU-cached per file path; invalidated on server restart

## Scraper Patterns (`scripts/manhwa_scraper.py`)
- `--pages N` caps browse pages per category for Asura, ManhuaTo, Drake; caps scroll rounds for Flame
- `BaseSiteScraper.__init__` params: `headless`, `limit` (series count cap), `max_pages` (page cap)
- `get_scraper(site, headless, canvas, limit, max_pages)` — always pass all relevant params
- `max_pages` is fully wired through the codebase — new sites just need `if page > (self.max_pages or 200):` in their loop
- BeautifulSoup: always use `get_text(separator=' ', strip=True)` — without separator, `Chapter 1<span>3 years ago</span>` becomes `"Chapter 13 years ago"` and regex captures the wrong number
- Drake debug: if 0 series returned, check page title and body classes logged at DEBUG level (`--debug` flag)
- ManhuaTo uses FlareSolverr on ARM; `_fs_cookies_applied` caches session cookies after first solve

## Maintenance Scripts
- `scripts/fix_flame_chapters.py` — fixes wrong chapter numbers in already-downloaded Flame CBZs by sorting numerically and renumbering 1, 2, 3… Dry-run by default; use `--apply [--db path/to/mangashelf.db]`
- Run after any FlameComics re-scrape where chapter numbers look wrong (e.g. Ch.14 instead of Ch.1)

## Front-end Patterns (`mangashelf/src/`)
- Series page chapter count uses `displayChapterCount` — shows `max(chapters per source)` when "All Sources" is active, not the sum, to avoid inflated counts for multi-source series
- Python type hints `list[X]` / `X | Y` require Python 3.10+; Pi may run older — use `List[X]` from `typing` and avoid union shorthand in scripts

## Git Workflow
- Commit from `manga-server-full/` (the git root), not from `mangashelf/`
- Always run `cd mangashelf && npx next build` before pushing front-end changes
- Remote: `https://github.com/kassabry/manga-server.git` (main branch)
- `library/` is gitignored; `mangashelf/data/` tracks only `.gitkeep`
