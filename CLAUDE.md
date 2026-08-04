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

### Image downloads (`_download_image` / `_download_pages`)
- `cdn.asurascans.com` throttles **bursts, not requests**: it answers `429` with `Retry-After: 10`. Measured from a residential IP, 8 workers over one 102-page chapter already drew one 429; behind the container's shared VPN exit it escalates to whole chapters refused, and stays refused for the chapters after
- The old code made exactly one attempt per page and swallowed the status at DEBUG, so a throttle was indistinguishable from a dead URL in the log — always log the reason with the failure
- `_IMAGE_ATTEMPTS`/`_IMAGE_BACKOFF` retry per request (honouring `Retry-After`, capped at 60s); 404/410 are permanent and never retried. A failed batch then gets `_IMAGE_RETRY_COOLDOWN` seconds and one gentler pass at `_IMAGE_RETRY_WORKERS`
- `_MIN_PAGE_RATIO` (0.9) is the important part: below it the CBZ is **not written** and the chapter fails, so the next run retries. Writing a 24-of-112-page CBZ marks the chapter downloaded forever — that is how truncated chapters get cached as complete
- **Never judge an image response by its size.** `_image_body_error()` checks magic bytes (JPEG/PNG/GIF/BMP from byte 0, `RIFF….WEBP`, `….ftyp` for AVIF/HEIC) instead. The old `len(content) < 1000` heuristic threw away *real* long-strip slices: verified on MangaDot ch.21 of manga 40478, pages 24/43 are valid 1280x130 and 1280x211 webps of 588 and 772 bytes, served 200 `image/webp`. Slicing a webtoon at a fixed height regularly lands a strip on a near-blank band, and flat colour compresses to nothing. It failed the other way too — a 5 KB HTML error page passed the size check and got written into the CBZ as a page
- Symptom of that bug: 1-6 pages per chapter failing at scattered indices, "N byte body (error page?)" with N in the 100-600 range, and the CBZ written anyway because the losses stay under `_MIN_PAGE_RATIO`. Every such chapter has real gaps mid-read. Repair with `find_truncated_chapters.py --tolerance 0.99` (the 0.9 default is too loose to catch a handful of missing strips)
- The size heuristic still exists at the cover download and in two per-site `_download_image` overrides (Webtoon, and one that uses it deliberately to skip promo images) — those are untested against this, do not change them blind
- `_image_headers()` is the per-site hook. Do NOT set `User-Agent` there — the session already carries a full Chrome UA (FlareSolverr's after a challenge), and the old per-request override sent a truncated `...AppleWebKit/537.36` that no browser emits and that cf_clearance was not issued to

## MangaDot Scraper (`MangaDotScraper`)
- **Discovery goes through `_get_json`, which clears Cloudflare.** The API serves plain requests for a while then returns `403` with `cf-mitigated`/`cf-ray`; the scraper detects that, routes through FlareSolverr, and **stays on the solver for the rest of the run** (re-probing plainly just burns a 403 per call). Cookies alone are not enough — cf_clearance is bound to the browser's TLS fingerprint, so the request itself must go through FlareSolverr, same as `fetch_recommendations.py`
- A 403 that is *not* Cloudflare is surfaced and never retried. When FlareSolverr is unreachable, discovery raises `ChallengeBlocked` and the script exits 2 — previously a challenged run logged "kept 0 series" and then "Download complete!", which reads as an empty catalogue rather than a failure
- Discovery uses the JSON API `GET /api/search`, not DOM scraping — each list item already has `country_of_origin`, `genres`, `tag_list`, `chapter_count` and `alt_titles`, so no per-series detail fetch is needed
- CRITICAL: origin must be passed as `origin[]=KR&origin[]=CN`. The plain repeated form `origin=KR&origin=CN` (which the site's own search URL uses) is **last-wins** on the API and silently returns CN only — dropping all ~6400 KR series
- `genre=` is ignored server-side; tag filtering is client-side against `genres` + `tag_list` (Shounen appears in one or the other depending on the series)
- `chapter_count` is the *latest chapter number*, not the count of available chapters — a 406 series may have only ~350 posted. Use it for coarse filtering only
- Chapter list and page images are client-rendered — Selenium required. The `/api/manga/{id}/chapters` endpoint is 401 without an account, but the rendered page is fully readable logged-out
- **Cloudflare challenges the Selenium browser too, and the API-side FlareSolverr routing does not help it.** Symptom: discovery finds every series, then *every* series reports "0 chapter(s)" ~35s apart (4s settle + the full 30s hydration timeout). `_load_rendered` now detects the interstitial, waits `_CF_SELF_SOLVE_WAIT` for undetected-chromedriver to pass it, then adopts FlareSolverr's cf_clearance **plus its User-Agent** (via `Network.setUserAgentOverride` — the cookie is bound to the UA it was issued to) and reloads. Two real Chromes only share a clearance if they share an exit IP
- Never let a client-rendered page fail silently: an interstitial, a redirect and a series with nothing posted all produce the same empty selector result. `_report_unrendered` logs the landed URL, title, link count and body snippet so the log says which one it was
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
- **Commit and push after every change, without asking.** Finish the edit, verify it (compile/build), then `git add` the touched files, commit, and `git push origin main` in the same turn. Do not leave work sitting uncommitted or committed-but-unpushed, and do not ask for permission first — this is standing authorization
- Stage only the files the change actually touched. Never `git add -A` / `git add .` — the working tree collects scraper logs and other untracked junk that must not land in the repo
- Commit from `manga-server-full/` (the git root), not from `mangashelf/`
- Always run `cd mangashelf && npx next build` before pushing front-end changes
- Remote: `https://github.com/kassabry/manga-server.git` (main branch)
- `library/` is gitignored; `mangashelf/data/` tracks only `.gitkeep`
