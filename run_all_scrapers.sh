#!/bin/bash
# Run all scrapers sequentially
# On ARM (Raspberry Pi), Cloudflare sites use FlareSolverr instead of
# undetected-chromedriver. Make sure FlareSolverr is running:
#   docker compose up -d flaresolverr
# You can set FLARESOLVERR_URL if it's not at http://localhost:8191

set -e
cd "$(dirname "$0")"

# Start Xvfb once in the background (needed for Selenium fallback)
if command -v Xvfb &>/dev/null; then
    Xvfb :99 -screen 0 1920x1080x24 &>/dev/null &
    XVFB_PID=$!
    export DISPLAY=:99
    echo "Xvfb started on :99 (PID $XVFB_PID)"
    trap "kill $XVFB_PID 2>/dev/null" EXIT
else
    echo "WARNING: Xvfb not found. Selenium-based scrapers may fail."
    echo "Proceeding anyway (FlareSolverr will handle Cloudflare sites)."
fi

echo "=== Asura Scans ==="
python3 scripts/manhwa_scraper.py --site asura --download-all --filter "action,fantasy,adventure" --source-prefix -o ./library/Manhwa

echo "=== ManhuaTo ==="
python3 scripts/manhwa_scraper.py --site manhuato --download-all --filter "action,fantasy,adventure" --source-prefix -o ./library/Manhua

echo "=== Webtoon ==="
python3 scripts/manhwa_scraper.py --site webtoon --download-all --filter "action,fantasy,adventure" --source-prefix -o ./library/Manhwa

echo "=== Flame Comics ==="
python3 scripts/manhwa_scraper.py --site flame --download-all --filter "action,fantasy,adventure" --source-prefix -o ./library/Manhwa

echo "=== Drake Comics ==="
python3 scripts/manhwa_scraper.py --site drake --download-all --filter "action,fantasy,adventure" --source-prefix -o ./library/Manhwa

# MangaDot filters by origin/tag/chapter-count during discovery, so it takes no
# --filter. Run once per origin: KR lands in Manhwa, CN in Manhua.
# --tag-mode all means a series must carry EVERY tag in --tags, not any one of
# them (the default). Without it, "Action,Adventure,Shounen" keeps anything
# tagged Action, which is most of the catalogue.
echo "=== MangaDot (Manhwa / KR) ==="
python3 scripts/manhwa_scraper.py --site mangadot --download-all --origin KR \
  --tags "Action,Adventure" --tag-mode all --source-prefix -o ./library/Manhwa

echo "=== MangaDot (Manhua / CN) ==="
python3 scripts/manhwa_scraper.py --site mangadot --download-all --origin CN \
  --tags "Action,Adventure" --tag-mode all --source-prefix -o ./library/Manhua

echo "=== LightNovelPub ==="
python3 scripts/lightnovel_scraper.py --site lightnovelpub --download-all --popular --pages 10 --source-prefix -o ./library/LightNovels

echo "=== NovelBin ==="
python3 scripts/lightnovel_scraper.py --site novelbin --download-all --popular --pages 10 --source-prefix -o ./library/LightNovels

echo "=== All scrapers complete ==="
