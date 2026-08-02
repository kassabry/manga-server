#!/usr/bin/env python3
"""Populate the Recommendation table from AniList.

Builds "readers also liked" links between series that are ALREADY in the
library — a recommendation pointing at something you cannot open is noise, so
targets that do not resolve to a local series are dropped.

Run periodically, out of band with the scrapers.  Nothing here happens at page
load: the front-end only ever reads the precomputed rows, so a slow or
rate-limited AniList can never block a series page.

    # see what would change
    python scripts/fetch_recommendations.py --db mangashelf/data/mangashelf.db

    # write it
    python scripts/fetch_recommendations.py --db mangashelf/data/mangashelf.db --apply

Linking a local series to AniList:

  1. `Series.anilistId` if already known (MangaDot writes it to the sidecar and
     the scanner imports it; ids resolved by a previous run are reused).
  2. Otherwise MangaDot's search endpoint is used as the bridge — it indexes
     the same scanlation sources the library came from, so titles agree
     character-for-character far more often than AniList's own search matches
     them.  An EXACT normalized match on the title or any alt title auto-links;
     near-matches (>= 0.88) are written to a review CSV instead of guessed at,
     the same policy MangaDotAliasIndex uses for folder merges.

Python 3.8-compatible on purpose (the Pi may not be on 3.10): typing.List
rather than list[...], no `X | Y` unions.
"""

import argparse
import csv
import html as html_lib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unicodedata
import uuid
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import requests

ANILIST_API = 'https://graphql.anilist.co'
MANGADOT_BASE = 'https://mangadot.net'
USER_AGENT = 'Mozilla/5.0 (MangaShelf recommendations)'

# AniList allows ~90 requests/minute. Stay well under it.
ANILIST_DELAY = 0.8
MANGADOT_DELAY = 0.4

# Resolution is the expensive half of this script and it hits a third-party
# site, so a run is bounded by default. Ids are cached, so successive runs
# chew through the backlog instead of re-asking for what is already known.
DEFAULT_MAX_LOOKUPS = 250

# Where resolved ids are remembered between runs, next to the database.
CACHE_FILENAME = '.anilist_id_cache.json'

# Series per AniList query. The API caps perPage at 50; 25 keeps each query's
# complexity modest while still cutting request count by more than an order of
# magnitude versus one-series-at-a-time.
ANILIST_BATCH = 25

# Below this, two titles are unrelated and not worth reporting. Matches
# MangaDotAliasIndex.FUZZY_THRESHOLD.
FUZZY_THRESHOLD = 0.88

_STOP_WORDS = {
    'a', 'an', 'the',
    'and', 'but', 'or', 'nor', 'for', 'so', 'yet',
    'as', 'at', 'by', 'in', 'of', 'on', 'to', 'up', 'via',
    'with', 'from', 'into', 'onto', 'upon',
    'is', 'was', 'are', 'were',
}
_SOURCE_PREFIX_RE = re.compile(r'^\[[^\]]+\]\s*')

RECS_QUERY = '''
query ($ids: [Int], $perPage: Int) {
  Page(perPage: 50) {
    media(id_in: $ids, type: MANGA) {
      id
      recommendations(sort: RATING_DESC, perPage: $perPage) {
        nodes {
          rating
          mediaRecommendation { id title { romaji english } }
        }
      }
    }
  }
}
'''


def norm(title: str) -> str:
    """Comparison key: fold accents, drop punctuation and stop-words.

    Mirrors _md_norm in manhwa_scraper.py so the two agree on what counts as
    the same title.
    """
    if not title:
        return ''
    folded = unicodedata.normalize('NFKD', title.lower())
    folded = ''.join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r'[^\w\s]', ' ', folded)
    return ' '.join(w for w in folded.split() if w not in _STOP_WORDS)


def bare_title(name: str) -> str:
    """Strip a leading [Source] prefix from a library folder or series title."""
    return _SOURCE_PREFIX_RE.sub('', name or '').strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def new_id() -> str:
    """Primary key for a Recommendation row.

    Prisma's @default(cuid()) is applied client-side, so rows inserted here
    have to bring their own id. Only uniqueness matters.
    """
    return 'rec' + uuid.uuid4().hex[:22]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def json_from_html(body: str) -> Optional[dict]:
    """Pull a JSON document out of what FlareSolverr hands back.

    FlareSolverr returns the *rendered* page, so a JSON endpoint comes back
    wrapped in Chrome's viewer markup (`<html><body><pre>{...}</pre>`) rather
    than as a bare document. Falls through progressively so a change in that
    wrapper does not break everything.
    """
    if not body:
        return None
    text = body.strip()

    try:
        return json.loads(text)
    except ValueError:
        pass

    match = re.search(r'<pre[^>]*>(.*?)</pre>', text, re.S | re.I)
    candidate = match.group(1) if match else re.sub(r'<[^>]+>', '', text)
    candidate = html_lib.unescape(candidate).strip()

    try:
        return json.loads(candidate)
    except ValueError:
        pass

    # Last resort: the outermost braces in whatever is left.
    start, end = candidate.find('{'), candidate.rfind('}')
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start:end + 1])
        except ValueError:
            pass
    print('    could not parse JSON from FlareSolverr response')
    return None


class ChallengeBlocked(Exception):
    """MangaDot is behind a Cloudflare challenge we could not clear."""


class MangaDotClient:
    """MangaDot API access that can clear a Cloudflare challenge.

    MangaDot sits behind Cloudflare. It often serves plain requests fine, then
    starts challenging once a run makes a few hundred of them. FlareSolverr
    (already part of this project's docker stack for ManhuaTo) solves the
    challenge in a headless browser; we take its cookies and User-Agent and go
    back to ordinary requests. cf_clearance is bound to the User-Agent, so
    adopting FlareSolverr's is not optional.
    """

    def __init__(self, flaresolverr_url: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        self.fs_url = (flaresolverr_url
                       or os.environ.get('FLARESOLVERR_URL', 'http://localhost:8191'))
        self._solved = False
        self._announced = False

    @staticmethod
    def _is_challenge(resp) -> bool:
        if resp.status_code not in (403, 503):
            return False
        return ('cf-mitigated' in resp.headers
                or 'server' in resp.headers and 'cloudflare' in resp.headers['server'].lower()
                or 'Just a moment' in resp.text[:1000])

    def flaresolverr_available(self) -> bool:
        try:
            return requests.get(self.fs_url, timeout=5).status_code == 200
        except Exception:
            return False

    def _solver_get(self, url: str) -> Optional[dict]:
        """Fetch a URL *through* FlareSolverr's browser and parse the JSON.

        Cookies alone are not enough. Cloudflare binds cf_clearance to the TLS
        fingerprint of the browser that earned it, and requests' fingerprint is
        not Chrome's — replaying the cookies gets challenged straight back.
        (The same constraint is noted on _flaresolverr_post in
        manhwa_scraper.py.) So the real request goes through the browser, and
        the cookies are kept only as a fast path worth trying first.
        """
        resp = requests.post(
            '%s/v1' % self.fs_url,
            json={'cmd': 'request.get', 'url': url, 'maxTimeout': 60000},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != 'ok':
            raise ChallengeBlocked('FlareSolverr: %s' % data.get('message', 'unknown'))

        solution = data.get('solution') or {}
        for cookie in solution.get('cookies') or []:
            domain = (cookie.get('domain') or '').strip()
            if not domain:
                continue
            self.session.cookies.set(cookie['name'], cookie['value'],
                                     domain=domain, path=cookie.get('path', '/'))
        if solution.get('userAgent'):
            self.session.headers['User-Agent'] = solution['userAgent']
        self._solved = True

        return json_from_html(solution.get('response') or '')

    def get_json(self, url: str) -> Optional[dict]:
        """Fetch JSON, going through FlareSolverr if Cloudflare intervenes.

        Raises ChallengeBlocked when even the browser cannot get through — the
        caller stops rather than grinding through the rest of the library
        collecting identical failures.
        """
        # Fast path: a plain request, which works until Cloudflare decides
        # otherwise and costs nothing when it does work.
        challenged = False
        for _ in range(3):
            try:
                resp = self.session.get(url, timeout=30)
            except Exception as e:
                print('    request failed (%s): %s' % (type(e).__name__, e))
                return None

            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                wait = int(resp.headers.get('Retry-After') or 60)
                print('    rate limited, waiting %ss' % wait)
                time.sleep(wait)
                continue
            if self._is_challenge(resp):
                challenged = True
            elif resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    return None
            else:
                print('    HTTP %s on %s' % (resp.status_code, url[:70]))
                return None
            break

        if not challenged:
            return None

        if not self._announced:
            print('    Cloudflare challenge — routing requests through FlareSolverr')
            self._announced = True
            if not self.flaresolverr_available():
                raise ChallengeBlocked(
                    'Cloudflare challenge, and FlareSolverr is not reachable at %s'
                    % self.fs_url)
        return self._solver_get(url)


class AniListUnavailable(Exception):
    """AniList refused the request outright — retrying will not help."""


def anilist_post(payload: dict, retries: int = 3) -> Optional[dict]:
    """POST a GraphQL query to AniList. Honours 429 Retry-After.

    A 403 here is not a transient failure: AniList returns one when the API is
    switched off wholesale (it has been disabled before "due to severe
    stability issues"). Retrying that just multiplies noise, so it aborts with
    whatever reason the API gave.
    """
    for attempt in range(retries):
        try:
            resp = requests.post(
                ANILIST_API, json=payload, timeout=30,
                headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'},
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get('Retry-After') or 60)
                print('    AniList rate limited, waiting %ss' % wait)
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                reason = 'HTTP 403'
                try:
                    errors = resp.json().get('errors') or []
                    if errors and errors[0].get('message'):
                        reason = errors[0]['message']
                except ValueError:
                    pass
                raise AniListUnavailable(reason)
            resp.raise_for_status()
            return resp.json()
        except AniListUnavailable:
            raise
        except Exception as e:
            print('    AniList request failed (%s): %s' % (type(e).__name__, e))
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return None


def anilist_recommendations(ids: List[int], per_series: int) -> Dict[int, List[dict]]:
    """Map AniList media id -> list of {rating, id, title} recommendations."""
    body = anilist_post({
        'query': RECS_QUERY,
        'variables': {'ids': ids, 'perPage': per_series},
    })
    out = {}  # type: Dict[int, List[dict]]
    if not body:
        return out
    if body.get('errors'):
        print("    AniList error: %s" % body['errors'][0].get('message'))
    for media in (((body.get('data') or {}).get('Page') or {}).get('media') or []):
        recs = []
        for node in ((media.get('recommendations') or {}).get('nodes') or []):
            target = node.get('mediaRecommendation') or {}
            if not target.get('id'):
                continue
            recs.append({
                'rating': int(node.get('rating') or 0),
                'id': int(target['id']),
                'title': (target.get('title') or {}).get('english')
                         or (target.get('title') or {}).get('romaji') or '',
                'romaji': (target.get('title') or {}).get('romaji') or '',
            })
        out[int(media['id'])] = recs
    return out


def mangadot_lookup(client: MangaDotClient,
                    title: str) -> Tuple[Optional[int], str, Optional[dict], float]:
    """Resolve a title to an AniList id via MangaDot.

    Returns (anilist_id, matched_via, best_fuzzy_item, best_fuzzy_score).
    anilist_id is set only on an EXACT normalized match.
    """
    key = norm(bare_title(title))
    if not key:
        return None, '', None, 0.0

    # The search parameter is `search=`. `q=`, `query=` and `title=` are
    # silently ignored and hand back the unfiltered catalogue.
    url = '%s/api/search?page=1&search=%s' % (
        MANGADOT_BASE, requests.utils.quote(bare_title(title)))
    body = client.get_json(url)
    items = (body or {}).get('manga_list') or []

    hit = None
    via = ''
    for item in items:
        if norm(item.get('title') or '') == key:
            hit, via = item, 'title'
            break
        for alt in item.get('alt_titles') or []:
            if norm(alt) == key:
                hit, via = item, 'alt:%s' % alt
                break
        if hit:
            break

    if hit:
        time.sleep(MANGADOT_DELAY)
        # anilist_id is only on the detail endpoint — the search listing
        # carries no external ids at all.
        detail = client.get_json('%s/api/manga/%s' % (MANGADOT_BASE, hit.get('id')))
        value = ((detail or {}).get('manga') or {}).get('anilist_id')
        if value:
            return int(value), via, None, 1.0
        # Matched the series but it carries no AniList id — nothing to link.
        return None, '', None, 0.0

    best, score = None, 0.0
    for item in items:
        s = similarity(key, norm(item.get('title') or ''))
        if s > score:
            best, score = item, s
    if best and score >= FUZZY_THRESHOLD:
        return None, '', best, score
    return None, '', None, 0.0


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def load_series(con: sqlite3.Connection) -> List[dict]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        'SELECT id, title, altTitles, anilistId, libraryPath FROM "Series"'
    ).fetchall()
    out = []
    for r in rows:
        alts = []
        if r['altTitles']:
            try:
                parsed = json.loads(r['altTitles'])
                if isinstance(parsed, list):
                    alts = [a for a in parsed if isinstance(a, str)]
            except Exception:
                pass
        out.append({
            'id': r['id'],
            'title': r['title'],
            'alts': alts,
            'anilistId': r['anilistId'],
            'libraryPath': r['libraryPath'],
        })
    return out


def sidecar_anilist_id(library_path: Optional[str]) -> Optional[int]:
    """Read anilistId from the scraper sidecar, if one is on disk."""
    if not library_path:
        return None
    try:
        with open(os.path.join(library_path, '.mangadot_meta.json'),
                  encoding='utf-8') as f:
            value = json.load(f).get('anilistId')
        return int(value) if value else None
    except Exception:
        return None


def build_indexes(series: List[dict]) -> Tuple[Dict[int, str], Dict[str, str]]:
    """(anilist id -> series id, normalized title -> series id)."""
    by_anilist = {}  # type: Dict[int, str]
    by_title = {}    # type: Dict[str, str]
    for s in series:
        if s['anilistId']:
            by_anilist.setdefault(int(s['anilistId']), s['id'])
        for name in [s['title']] + s['alts']:
            key = norm(bare_title(name))
            if key:
                by_title.setdefault(key, s['id'])
    return by_anilist, by_title


def resolve_cache_path(db_path: str, override: Optional[str]) -> Tuple[str, List[str]]:
    """Pick where the id cache lives: (write_path, paths_to_try_reading).

    The database directory is the natural home but is not always writable —
    on the Pi the library sits on a mount owned by another user. Falling back
    keeps a long resolve run resumable instead of silently discarding it.
    """
    if override:
        return override, [override]

    db_dir = os.path.dirname(os.path.abspath(db_path))
    candidates = [
        os.path.join(db_dir, CACHE_FILENAME),
        os.path.join(os.getcwd(), CACHE_FILENAME),
        os.path.join(tempfile.gettempdir(), CACHE_FILENAME),
    ]
    for path in candidates:
        directory = os.path.dirname(path) or '.'
        if os.access(directory, os.W_OK):
            return path, candidates
    return candidates[-1], candidates


def load_cache(path: str) -> Dict[str, Optional[int]]:
    """Remembered title -> AniList id (null for a confirmed miss).

    Resolution is slow and hits a third party, so a dry run is worth as much
    as a real one: both populate this, and neither re-asks what it already
    knows. Without it, a 1900-series dry run throws away 40 minutes of work.
    """
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(path: str, cache: Dict[str, Optional[int]]) -> bool:
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=0, sort_keys=True)
        return True
    except Exception as e:
        print('  WARNING: could not write id cache to %s (%s)' % (path, e))
        print('  Pass --cache-file to put it somewhere writable, or this run\'s'
              ' lookups are lost.')
        return False


def write_review_csv(path: str, rows: List[dict]) -> None:
    fields = ['local_title', 'mangadot_title', 'mangadot_id',
              'similarity', 'anilist_id', 'action']
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r['similarity'], reverse=True))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description='Populate the Recommendation table from AniList.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--db', required=True, help='Path to mangashelf.db')
    parser.add_argument('--apply', action='store_true',
                        help='Write changes (default: dry run)')
    parser.add_argument('--min-rating', type=int, default=5,
                        help='Drop recommendations below this AniList vote '
                             'count (default: 5). Niche series attract 1-2 '
                             'vote pairings that are essentially noise')
    parser.add_argument('--per-series', type=int, default=10,
                        help='Recommendations to request per series (default: 10)')
    parser.add_argument('--review-csv', default='anilist_link_candidates.csv',
                        help='Where to write near-match titles for review')
    parser.add_argument('--only', help='Only process series whose title '
                                       'contains this substring')
    parser.add_argument('--no-resolve', action='store_true',
                        help='Skip AniList id lookup; only use ids already known')
    parser.add_argument('--max-lookups', type=int, default=DEFAULT_MAX_LOOKUPS,
                        help='Cap MangaDot lookups per run (default: %d, 0 for '
                             'no cap). Results are cached, so successive runs '
                             'work through the backlog' % DEFAULT_MAX_LOOKUPS)
    parser.add_argument('--refresh-cache', action='store_true',
                        help='Ignore %s and look everything up again' % CACHE_FILENAME)
    parser.add_argument('--cache-file',
                        help='Where to keep resolved ids. Defaults to %s beside '
                             'the database, falling back to the working '
                             'directory then the temp dir if that is not '
                             'writable' % CACHE_FILENAME)
    parser.add_argument('--flaresolverr-url',
                        help='FlareSolverr endpoint for clearing MangaDot\'s '
                             'Cloudflare challenge (default: $FLARESOLVERR_URL '
                             'or http://localhost:8191)')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print('ERROR: database not found: %s' % args.db)
        return 1

    mode = 'APPLYING CHANGES' if args.apply else 'DRY RUN (nothing written)'
    print('\n%s' % ('=' * 70))
    print('  fetch_recommendations.py — %s' % mode)
    print('  Database: %s' % args.db)
    print('%s\n' % ('=' * 70))

    con = sqlite3.connect(args.db)
    series = load_series(con)
    if args.only:
        needle = args.only.lower()
        series = [s for s in series if needle in (s['title'] or '').lower()]
    print('Loaded %d series' % len(series))

    # -- 1. make sure every series has an AniList id where we can get one ----

    review_rows = []  # type: List[dict]
    resolved_now = []  # type: List[Tuple[str, int]]

    # A sidecar written since the last library scan is authoritative. Persist
    # what it says too, so the DB is the single source of truth and a later
    # --no-resolve run does not come up empty.
    for s in series:
        if not s['anilistId']:
            found = sidecar_anilist_id(s['libraryPath'])
            if found:
                s['anilistId'] = found
                resolved_now.append((s['id'], found))

    unresolved = [s for s in series if not s['anilistId']]

    cache_path, cache_candidates = resolve_cache_path(args.db, args.cache_file)
    cache = {}
    if not args.refresh_cache:
        for candidate in cache_candidates:
            cache = load_cache(candidate)
            if cache:
                print('Reusing %d cached id lookup(s) from %s'
                      % (len(cache), candidate))
                break

    # Anything the cache already knows costs nothing.
    for s in unresolved[:]:
        key = norm(bare_title(s['title']))
        if key in cache:
            if cache[key]:
                s['anilistId'] = cache[key]
                resolved_now.append((s['id'], cache[key]))
            unresolved.remove(s)

    if unresolved and not args.no_resolve:
        budget = args.max_lookups if args.max_lookups > 0 else len(unresolved)
        todo = unresolved[:budget]
        print('\nResolving %d of %d unresolved series via MangaDot%s...'
              % (len(todo), len(unresolved),
                 '' if len(todo) == len(unresolved) else ' (--max-lookups)'))

        client = MangaDotClient(args.flaresolverr_url)
        blocked = None
        try:
            for s in todo:
                key = norm(bare_title(s['title']))
                aid, via, fuzzy, score = mangadot_lookup(client, s['title'])
                cache[key] = aid
                if aid:
                    s['anilistId'] = aid
                    resolved_now.append((s['id'], aid))
                    print('  LINK   %-44s -> %s (via %s)'
                          % (bare_title(s['title'])[:44], aid, via))
                elif fuzzy is not None:
                    review_rows.append({
                        'local_title': s['title'],
                        'mangadot_title': fuzzy.get('title', ''),
                        'mangadot_id': fuzzy.get('id', ''),
                        'similarity': round(score, 4),
                        'anilist_id': '',
                        'action': '',
                    })
                    print('  REVIEW %-44s ~ %s (%.2f)'
                          % (bare_title(s['title'])[:44],
                             (fuzzy.get('title') or '')[:30], score))
                else:
                    print('  MISS   %s' % bare_title(s['title'])[:44])
                time.sleep(MANGADOT_DELAY)
        except ChallengeBlocked as e:
            blocked = e
        except KeyboardInterrupt:
            print('\nInterrupted — keeping what has been resolved so far.')

        # Written even on an abort: the lookups already made were expensive.
        cached_ok = save_cache(cache_path, cache)

        if blocked:
            print('\n%s' % ('-' * 70))
            print('STOPPED: %s' % blocked)
            print('MangaDot is behind Cloudflare. Start FlareSolverr (it is in')
            print('docker-compose.yml) and set FLARESOLVERR_URL, or pass')
            print('--flaresolverr-url.')
            if cached_ok:
                print('Progress so far is cached in %s, so re-running resumes.'
                      % cache_path)
            else:
                print('This run\'s lookups could NOT be cached (see warning above),')
                print('so re-running starts over until --cache-file points somewhere')
                print('writable.')
            print('%s' % ('-' * 70))
    elif not unresolved:
        print('\nEvery series already has an id or a cached lookup.')

    if review_rows:
        write_review_csv(args.review_csv, review_rows)
        print('\nWrote %d near-match(es) to %s for review'
              % (len(review_rows), args.review_csv))

    linked = [s for s in series if s['anilistId']]
    print('\n%d/%d series have an AniList id' % (len(linked), len(series)))
    if not linked:
        print('Nothing to fetch.')
        return 0

    # -- 2. fetch recommendations in batches --------------------------------

    by_anilist, by_title = build_indexes(series)
    ids = [int(s['anilistId']) for s in linked]

    print('\nFetching recommendations (%d series, %d per batch)...'
          % (len(ids), ANILIST_BATCH))
    all_recs = {}  # type: Dict[int, List[dict]]
    try:
        for i in range(0, len(ids), ANILIST_BATCH):
            batch = ids[i:i + ANILIST_BATCH]
            all_recs.update(anilist_recommendations(batch, args.per_series))
            print('  %d/%d' % (min(i + ANILIST_BATCH, len(ids)), len(ids)))
            time.sleep(ANILIST_DELAY)
    except AniListUnavailable as e:
        print('\n%s' % ('-' * 70))
        print('STOPPED: AniList refused the request.')
        print('  %s' % e)
        print('Nothing is wrong with your library or the resolved ids — those')
        print('are cached. Re-run once AniList is serving again.')
        print('%s' % ('-' * 70))
        con.close()
        return 1

    # -- 3. map targets back to local series --------------------------------

    edges = []  # type: List[Tuple[str, str, int]]
    dropped_offsite = 0
    dropped_lowrated = 0
    for s in linked:
        recs = all_recs.get(int(s['anilistId'])) or []
        for rec in recs:
            if rec['rating'] < args.min_rating:
                dropped_lowrated += 1
                continue
            # Match on AniList id first — exact by construction. Titles are
            # only a fallback for local series linked by a different route.
            target = by_anilist.get(rec['id'])
            if not target:
                for name in (rec['title'], rec['romaji']):
                    target = by_title.get(norm(bare_title(name)))
                    if target:
                        break
            if not target:
                dropped_offsite += 1
                continue
            if target == s['id']:
                continue
            edges.append((s['id'], target, rec['rating']))

    print('\n%d in-library recommendation(s)' % len(edges))
    print('  dropped: %d not in library, %d below --min-rating %d'
          % (dropped_offsite, dropped_lowrated, args.min_rating))

    with_recs = len(set(e[0] for e in edges))
    print('  %d/%d series will show recommendations' % (with_recs, len(series)))

    if not args.apply:
        print('\nDry run — re-run with --apply to write.')
        for src, dst, rating in edges[:15]:
            titles = {s['id']: bare_title(s['title']) for s in series}
            print('  %-38s -> %-38s (%d)'
                  % (titles.get(src, '?')[:38], titles.get(dst, '?')[:38], rating))
        if len(edges) > 15:
            print('  ... and %d more' % (len(edges) - 15))
        con.close()
        return 0

    # -- 4. write ------------------------------------------------------------

    cur = con.cursor()
    for series_id, aid in resolved_now:
        cur.execute('UPDATE "Series" SET "anilistId" = ? WHERE id = ?', (aid, series_id))

    # Replace this run's edges wholesale so recommendations that AniList has
    # since dropped do not linger. Only series we actually fetched are cleared,
    # so a --only run never wipes the rest of the library.
    for series_id in set(s['id'] for s in linked):
        cur.execute('DELETE FROM "Recommendation" WHERE "seriesId" = ?', (series_id,))

    cur.executemany(
        'INSERT OR REPLACE INTO "Recommendation" '
        '(id, "seriesId", "targetSeriesId", rating, source) VALUES (?, ?, ?, ?, ?)',
        [(new_id(), src, dst, rating, 'anilist') for src, dst, rating in edges],
    )
    con.commit()
    print('\nWrote %d recommendation(s); linked %d new AniList id(s).'
          % (len(edges), len(resolved_now)))
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
