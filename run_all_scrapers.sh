#!/bin/bash
# Run all scrapers sequentially
# On ARM (Raspberry Pi), Drake and ManhuaTo use FlareSolverr instead of
# undetected-chromedriver. Make sure FlareSolverr is running:
#   docker compose -f docker-compose-custom-sources.yml up -d flaresolverr
# You can set FLARESOLVERR_URL if it's not at http://localhost:8191

set -e
cd "$(dirname "$0")"

echo "=== Asura Scans ==="
xvfb-run python3 scripts/manhwa_scraper.py --site asura --list-all -o asura.yaml && \
xvfb-run python3 scripts/manhwa_scraper.py --site asura --download-all -o ./library/Manhwa

echo "=== Flame Comics ==="
xvfb-run python3 scripts/manhwa_scraper.py --site flame --list-all -o flame.yaml && \
xvfb-run python3 scripts/manhwa_scraper.py --site flame --download-all -o ./library/Manhwa

echo "=== Drake Comics ==="
xvfb-run python3 scripts/manhwa_scraper.py --site drake --list-all -o drake.yaml && \
xvfb-run python3 scripts/manhwa_scraper.py --site drake --download-all -o ./library/Manhwa

echo "=== ManhuaTo ==="
xvfb-run python3 scripts/manhwa_scraper.py --site manhuato --list-all -o manhuato.yaml && \
xvfb-run python3 scripts/manhwa_scraper.py --site manhuato --download-all -o ./library/Manhua

echo "=== Webtoon ==="
xvfb-run python3 scripts/manhwa_scraper.py --site webtoon --list-all -o webtoon.yaml && \
xvfb-run python3 scripts/manhwa_scraper.py --site webtoon --download-all -o ./library/Manhwa

echo "=== LightNovelPub ==="
xvfb-run python3 scripts/lightnovel_scraper.py --site lightnovelpub --list-all --popular --pages 10 -o lightnovelpub_popular.yaml && \
xvfb-run python3 scripts/lightnovel_scraper.py --site lightnovelpub --download-all --popular --pages 10 -o ./library/LightNovels

echo "=== NovelBin ==="
xvfb-run python3 scripts/lightnovel_scraper.py --site novelbin --list-all --popular --pages 10 -o novelbin_popular.yaml && \
xvfb-run python3 scripts/lightnovel_scraper.py --site novelbin --download-all --popular --pages 10 -o ./library/LightNovels

echo "=== All scrapers complete ==="
