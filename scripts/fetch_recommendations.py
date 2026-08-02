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
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

ANILIST_API = 'https://graphql.anilist.co'
MANGADOT_BASE = 'https://mangadot.net'
USER_AGENT = 'Mozilla/5.0 (MangaShelf recommendations)'

# AniList allows ~90 requests/minute. Stay well under it.
ANILIST_DELAY = 0.8
MANGADOT_DELAY = 0.4

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

def http_json(url: str, data: Optional[bytes] = None,
              headers: Optional[Dict[str, str]] = None,
              timeout: int = 30, retries: int = 3) -> Optional[dict]:
    """GET/POST returning parsed JSON, or None. Honours 429 Retry-After."""
    hdrs = {'User-Agent': USER_AGENT}
    if headers:
        hdrs.update(headers)

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get('Retry-After') or 60)
                print("    rate limited, waiting %ss" % wait)
                time.sleep(wait)
                continue
            # A 404 is a real answer, not a transient failure.
            if e.code == 404:
                return None
            print("    HTTP %s on %s" % (e.code, url[:70]))
        except Exception as e:
            print("    request failed (%s): %s" % (type(e).__name__, e))
        if attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
    return None


def anilist_recommendations(ids: List[int], per_series: int) -> Dict[int, List[dict]]:
    """Map AniList media id -> list of {rating, id, title} recommendations."""
    payload = json.dumps({
        'query': RECS_QUERY,
        'variables': {'ids': ids, 'perPage': per_series},
    }).encode('utf-8')
    body = http_json(ANILIST_API, data=payload,
                     headers={'Content-Type': 'application/json'})
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


def mangadot_lookup(title: str) -> Tuple[Optional[int], str, Optional[dict], float]:
    """Resolve a title to an AniList id via MangaDot.

    Returns (anilist_id, matched_via, best_fuzzy_item, best_fuzzy_score).
    anilist_id is set only on an EXACT normalized match.
    """
    key = norm(bare_title(title))
    if not key:
        return None, '', None, 0.0

    url = '%s/api/search?page=1&search=%s' % (
        MANGADOT_BASE, urllib.parse.quote(bare_title(title)))
    body = http_json(url)
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
        detail = http_json('%s/api/manga/%s' % (MANGADOT_BASE, hit.get('id')))
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

    if unresolved and not args.no_resolve:
        print('\nResolving %d series to AniList via MangaDot...' % len(unresolved))
        for s in unresolved:
            aid, via, fuzzy, score = mangadot_lookup(s['title'])
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
    for i in range(0, len(ids), ANILIST_BATCH):
        batch = ids[i:i + ANILIST_BATCH]
        all_recs.update(anilist_recommendations(batch, args.per_series))
        print('  %d/%d' % (min(i + ANILIST_BATCH, len(ids)), len(ids)))
        time.sleep(ANILIST_DELAY)

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
