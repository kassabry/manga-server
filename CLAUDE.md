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

## MangaDot Scraper (`MangaDotScraper`)
- Discovery uses the JSON API `GET /api/search`, not DOM scraping — each list item already has `country_of_origin`, `genres`, `tag_list`, `chapter_count` and `alt_titles`, so no per-series detail fetch is needed
- CRITICAL: origin must be passed as `origin[]=KR&origin[]=CN`. The plain repeated form `origin=KR&origin=CN` (which the site's own search URL uses) is **last-wins** on the API and silently returns CN only — dropping all ~6400 KR series
- `genre=` is ignored server-side; tag filtering is client-side against `genres` + `tag_list` (Shounen appears in one or the other depending on the series)
- `chapter_count` is the *latest chapter number*, not the count of available chapters — a 406 series may have only ~350 posted. Use it for coarse filtering only
- Chapter list and page images are client-rendered — Selenium required. The `/api/manga/{id}/chapters` endpoint is 401 without an account, but the rendered page is fully readable logged-out
- Chapter list: click `SHOW N MORE CHAPTERS` to expand. Do NOT click the `N VERSIONS` buttons — toggling them collapses the list (127 links → 11)
- Hydration gotcha: the SSR page ships one chapter anchor ("Start Reading") plus an inert copy of the expander button. Waiting on "any chapter anchor exists" fires the click before React attaches handlers and silently yields a collapsed list — wait for `> 3` anchors instead
- Multi-group chapters put "Ch. N" on an ancestor, not the anchor (only ~10 of 127 anchors carry it) — walk up 4 levels when parsing the number
- Origin routing is per-invocation via `--origin KR -o library/Manhwa` / `--origin CN -o library/Manhua`
- Alt-title merging: exact match on title or any "Other Names" entry auto-merges into the existing folder; near-matches go to `mangadot_merge_candidates.csv` for review (apply via `suggest_merges.py`). Disable with `--no-alias-merge`

### Page collection (`get_pages`)
- The reader lazy-loads images on scroll. Walk it with a step of ~0.8 × viewport height and bound the loop by `document.body.scrollHeight` **re-read every pass** (it grows as images resolve) — never by a fixed iteration count
- A fixed `range(40)` of `innerHeight * 1.5` jumps was silently truncating long chapters: a simulated 147-page chapter collected **34 pages**, and the resulting CBZ looks complete. Big jumps also outrun the lazy-load observer
- The chosen version advertises its page count (`_md_version['pages']`, from "… · MD 147p"). Use it as ground truth: stop early once all pages are in, retry once if short, and log an ERROR if still short — never return a silently truncated chapter
- `scripts/find_truncated_chapters.py` finds already-downloaded victims by comparing CBZ image count against `.mangadot_versions.json`. `--apply` deletes them; the next normal scrape refetches. No scraper flag needed
- Deleting a CBZ is enough to force a refetch: `download_chapter` only honours the tracker when the file is still on disk, and otherwise discards the tracker entry and re-downloads ("Re-downloading (file missing)"). `--tracker` on the repair script is optional tidiness, not a requirement
- Default tolerance is 90% of the advertised count, because `_filter_outlier_images_by_dimension` legitimately removes a few promo images per chapter

### Multi-version chapters
- Each version is its own anchor: `└ ○ upload {Group} · MD {N}p {date}` — group and page count parse straight out of it
- DOM order is NOT quality order (Ch. 215 of manga/26041 lists a 4p version before a 5p one), so never just take the first anchor
- Page count is a floor, not a ranking: a long-strip chapter cut into 6 tall images can equal one cut into 147 short ones, so `PAGE_FLOOR_RATIO` (0.5) only drops stub uploads, and `--prefer-groups` decides among what survives. A preferred group posting a stub still loses
- `.mangadot_versions.json` per series dir records the chosen version's url/group/pages; `is_upgrade()` compares it on later runs
- Chapters with no manifest entry are never upgraded — that's deliberate, otherwise the first run after adding version tracking re-downloads the whole back catalogue
- `--max-upgrades` (default 25) caps re-downloads per run; upgrades delete the CBZ and clear the tracker entry so the normal path re-fetches it
- `--prefer-groups` is OPTIONAL — with it empty, real groups beat ungrouped uploads and more pages wins the tie, which is already sensible
- The site spells ungrouped uploads "No Group", "No-group" and "(no group)"; `_group_rank` matches all three and sorts them last
- `--report-groups -o groups.csv` surveys which groups win contested chapters (win rate, stub rate, avg pages) and prints a suggested `--prefer-groups` line. Bound the survey with `--pages`/`--limit`; it needs a Selenium chapter-list load per series
- Real signal from a 4-series survey: on the same 339 contested chapters Asura Scans won 94% with 0% stubs, Drake Scans 16% with 46% stubs — worth surveying before assuming page count alone is enough

## Recommendations (`scripts/fetch_recommendations.py`)
- Precomputed into the `Recommendation` table; the series page only ever reads rows, so AniList is never on the page-load path
- Only links series **already in the library** — a recommendation you cannot open is noise. Expect most AniList targets to be dropped
- A small library legitimately yields zero rows: 11 niche manhwa produced 85 targets, none of them local. That is correct behaviour, not a bug
- MangaDex has no recommendations API (`/manga/{id}/recommendations` 404s) — do not retry it. AniList GraphQL (`https://graphql.anilist.co`) is the source
- MangaDot is the title→AniList bridge: `GET /api/search?search={title}`. The param is **`search=`** — `q=`, `query=`, `title=` are silently ignored and return the unfiltered catalogue
- `anilist_id` is NOT in the search listing. It is on the detail endpoint `GET /api/manga/{id}` under `manga.anilist_id` (unauthenticated, ~3KB). Sampled 12/12 coverage
- This bridge beats searching AniList by title because MangaDot indexes the same scanlation sources the library came from (items carry `source_url` like `asurascans.com/...`), so titles agree exactly — 14/14 on the real library
- Exact `_md_norm` match on title or alt title auto-links; ≥0.88 near-matches go to `anilist_link_candidates.csv` for review, matching `MangaDotAliasIndex` policy
- `--apply` deletes and rewrites edges only for the series it fetched, so `--only` never wipes the rest of the library
- SQLite enforces the `ON DELETE CASCADE` only when `PRAGMA foreign_keys = ON`. Prisma sets it; a raw Python connection does not, so scripts deleting series directly will orphan rows
- **MangaDot is behind Cloudflare.** It serves plain requests fine for a while, then challenges once a run makes a few hundred (`cf-mitigated: challenge`, "Just a moment..."). Route through FlareSolverr — same stack already used for ManhuaTo, `FLARESOLVERR_URL` or `--flaresolverr-url`. cf_clearance is bound to the User-Agent, so adopt FlareSolverr's UA along with its cookies
- **Never retry a 403.** Neither site's 403 is transient, and retrying triples the request volume — that is what tripped MangaDot's challenge in the first place. Abort and surface the reason
- **AniList returns a 403 with a human-readable `errors[0].message` when their API is switched off wholesale** (seen 2026-08-02: "temporarily disabled due to severe stability issues"). Not a rate limit, not fixable from here — read the message rather than retrying
- Resolution is cached in `.anilist_id_cache.json` beside the DB, written even when a run aborts, so a 1900-series run resumes instead of restarting. `--max-lookups` (default 250) bounds each run

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
