# Adding Custom Manhwa/Manhua Sources

This guide explains how to configure your manga server to download from specific sites like Asura Scans, Flame Comics, Drake Comics, and similar scanlation sites.

---

## NEW: Scrape Entire Sites

You can now scrape ALL series from a site instead of specifying each one.

### List All Series from a Site

```bash
# Get a list of ALL series from Asura Scans
python scripts/manhwa_scraper.py --site asura --list-all -o asura_all_series.yaml

# Same for Flame Comics
python scripts/manhwa_scraper.py --site flame --list-all -o flame_all_series.yaml

# Same for Drake Comics  
python scripts/manhwa_scraper.py --site drake --list-all -o drake_all_series.yaml
```

This creates a YAML file listing every series on the site. You can then:
1. Review the list
2. Set `enabled: false` for series you don't want
3. Use it for downloading

### Download ALL Series from a Site

⚠️ **Warning: This downloads A LOT of data (potentially hundreds of GB)**

```bash
# Download EVERYTHING from Asura (careful!)
python scripts/manhwa_scraper.py --site asura --download-all -o library/Manhwa

# Download with a limit (for testing)
python scripts/manhwa_scraper.py --site asura --download-all --limit 5 -o library/Manhwa
```

### Filter by Genre/Keywords

Only download series matching certain keywords:

```bash
# Only cultivation/martial arts manhwa
python scripts/manhwa_scraper.py --site asura --download-all \
    --filter "cultivation,martial,murim" -o library/Manhwa

# Only romance
python scripts/manhwa_scraper.py --site flame --download-all \
    --filter "romance,love" -o library/Manhwa

# Only isekai/reincarnation
python scripts/manhwa_scraper.py --site asura --download-all \
    --filter "isekai,reincarnation,regression" -o library/Manhwa
```

### Recommended Workflow

1. **First, get the series list:**
   ```bash
   python scripts/manhwa_scraper.py --site asura --list-all -o my_asura_list.yaml
   ```

2. **Review and edit the YAML:**
   ```yaml
   series:
     - title: "Solo Leveling"
       url: "https://asuracomic.net/series/solo-leveling"
       enabled: true    # Keep this one
       
     - title: "Some Series I Don't Want"
       url: "..."
       enabled: false   # Skip this one
   ```

3. **Download your curated list:**
   ```bash
   python scripts/manhwa_scraper.py --config my_asura_list.yaml -o library/Manhwa
   ```

### Resume Interrupted Downloads

The scraper automatically tracks progress. If it stops (network issue, reboot, etc.), just run the same command again - it will skip already-downloaded chapters.

```bash
# This will resume where it left off
python scripts/manhwa_scraper.py --site asura --download-all -o library/Manhwa
```

### Storage Estimates

| Site | ~Series Count | ~Total Size |
|------|---------------|-------------|
| Asura Scans | 200+ | 300-500 GB |
| Flame Comics | 100+ | 150-300 GB |
| Drake Comics | 100+ | 150-300 GB |
| ManhuaTo | 1000+ | 500+ GB |
| Webtoon ORIGINALS | 500+ | 500-800 GB |
| Webtoon CANVAS | 10,000+ | Many TB (don't try this!) |

**Tip:** Use `--filter` to keep it manageable, or be selective with your YAML file.

---

## ManhuaTo (manhuato.com)

ManhuaTo has a large collection of manhwa, manhua, and manga with generally good quality scans.

```bash
# List all series from ManhuaTo
python scripts/manhwa_scraper.py --site manhuato --list-all -o manhuato_all.yaml

# Download only manhwa
python scripts/manhwa_scraper.py --site manhuato --download-all --filter "manhwa" -o library/Manhwa

# Download fantasy manhua
python scripts/manhwa_scraper.py --site manhuato --download-all --filter "manhua,fantasy" -o library/Manhua
```

---

## Choosing Between Sources (Multi-Source Management)

Since popular series like Solo Leveling appear on multiple sites, you might want to compare quality and choose the best source. Here are your options:

### Option 1: Separate Folders by Source (Recommended)

Organize downloads so each source has its own folder:

```
library/
├── Manhwa/
│   ├── [Asura] Solo Leveling/
│   │   ├── Chapter 001.cbz
│   │   └── ...
│   ├── [Webtoon] Solo Leveling/
│   │   ├── Chapter 001.cbz
│   │   └── ...
│   └── [ManhuaTo] Solo Leveling/
│       └── ...
```

To do this, use the `--source-prefix` option (or manually organize):

```bash
# Download from Asura with source prefix
python scripts/manhwa_scraper.py --site asura --download-all \
    --filter "solo leveling" --source-prefix -o library/Manhwa

# Compare with Webtoon version
python scripts/manhwa_scraper.py --site webtoon --download-all \
    --filter "solo leveling" --source-prefix -o library/Manhwa
```

### Option 2: Separate Kavita Libraries

Create multiple libraries in Kavita, one per source:

1. **In Kavita Settings → Libraries:**
   - Create "Asura Scans" library → `/library/Asura/`
   - Create "Webtoon" library → `/library/Webtoon/`
   - Create "ManhuaTo" library → `/library/ManhuaTo/`

2. **Download to separate directories:**
   ```bash
   python scripts/manhwa_scraper.py --site asura --download-all -o library/Asura
   python scripts/manhwa_scraper.py --site webtoon --download-all -o library/Webtoon
   ```

3. **In Kavita's UI:** You can switch between libraries to compare the same series from different sources.

### Option 3: Source Tags in Filename

Include source in the series folder name:

```yaml
# In sources.yaml
series:
  - title: "Solo Leveling [Asura]"
    url: "https://asuracomic.net/series/solo-leveling"
    source: asura
    
  - title: "Solo Leveling [Webtoon]"
    url: "https://www.webtoons.com/en/action/solo-leveling/list?title_no=3162"
    source: webtoon
```

### Comparing Quality Between Sources

Different sites may have:
- **Different scan quality** (resolution, compression)
- **Different translation quality** (official vs fan translation)
- **Different chapter availability** (some sites have more chapters)
- **Different update speed** (some sites update faster)

**Quick comparison strategy:**
1. Download Chapter 1 from each source
2. Open the CBZ files and compare image quality
3. Delete the lower-quality versions
4. Continue downloading from your preferred source

### Deduplication

If you accidentally download duplicates, you can identify them:

```bash
# Find potential duplicates (series with similar names)
ls library/Manhwa/ | sort | uniq -d

# Or use fdupes to find duplicate files
sudo apt install fdupes
fdupes -r library/Manhwa/
```

---

## Webtoon (Official Platform)

Webtoon is special because it's an **official platform** with free (ad-supported) content. The scraper downloads only FREE chapters - paid/locked episodes are skipped.

### Webtoon ORIGINALS (Professional Series)

```bash
# List all ORIGINALS series
python scripts/manhwa_scraper.py --site webtoon --list-all -o webtoon_originals.yaml

# Download all free fantasy ORIGINALS
python scripts/manhwa_scraper.py --site webtoon --download-all --filter "fantasy" -o library/Webtoon

# Download action and thriller series
python scripts/manhwa_scraper.py --site webtoon --download-all --filter "action,thriller" -o library/Webtoon
```

### Webtoon CANVAS (User-Created Series)

CANVAS has thousands of amateur series. Use the `--canvas` flag:

```bash
# List all CANVAS series
python scripts/manhwa_scraper.py --site webtoon --canvas --list-all -o webtoon_canvas.yaml

# Download top CANVAS romance series
python scripts/manhwa_scraper.py --site webtoon --canvas --download-all --filter "romance" -o library/Webtoon
```

### Webtoon URL Format

Webtoon series URLs look like:
```
https://www.webtoons.com/en/fantasy/tower-of-god/list?title_no=95
```

Add them to your `sources.yaml`:
```yaml
series:
  - title: "Tower of God"
    url: "https://www.webtoons.com/en/fantasy/tower-of-god/list?title_no=95"
    source: webtoon
    enabled: true
```

### Important Notes for Webtoon

- **Only FREE chapters** are downloaded (paid/Fast Pass episodes are skipped)
- **Rate limiting** - Webtoon enforces limits, the scraper adds delays automatically
- **Official content** - Consider supporting creators via the app if you enjoy their work
- **Large library** - ORIGINALS has ~500+ series, CANVAS has thousands

---

## Overview

There are **two approaches** to get content from specific sources:

| Approach | Pros | Cons |
|----------|------|------|
| **Kaizoku + Lua Scrapers** | Integrated UI, automatic scheduling | Scrapers can break when sites change |
| **Python Downloader Script** | More flexible, easier to debug | Manual/cron-based, no web UI |

I recommend using **both**: Kaizoku for sites it supports well, and the Python script as a backup for troublesome sites.

---

## Approach 1: Kaizoku with Custom Lua Scrapers

Kaizoku uses **mangal** under the hood, which supports custom Lua scrapers.

### Step 1: Copy Scrapers to Config Directory

On your Pi, after the containers are running:

```bash
# Create the mangal sources directory
mkdir -p /mnt/manga-storage/manga-server/config/kaizoku/.config/mangal/sources

# Copy the scrapers (from this package)
cp config/scrapers/*.lua /mnt/manga-storage/manga-server/config/kaizoku/.config/mangal/sources/
```

### Step 2: Verify Scrapers are Loaded

```bash
# Enter the Kaizoku container
docker exec -it kaizoku sh

# List available sources
mangal sources list
```

You should see your custom sources (AsuraScans, FlameComics, DrakeComics) in the list.

### Step 3: Test a Scraper

```bash
# Still inside the container
mangal inline --source AsuraScans --query "Solo Leveling" -j
```

This should return JSON with search results.

### Step 4: Use in Kaizoku Web UI

1. Open Kaizoku at `http://your-pi:3000`
2. Click "Add Series"
3. Select your custom source from the dropdown
4. Search and add series

### Troubleshooting Lua Scrapers

**Scraper not appearing:**
```bash
# Check for syntax errors
docker exec -it kaizoku mangal sources list
```

**Scraper returns empty results:**
- The site may have changed its structure
- Try the Python downloader instead
- Check if the site requires Cloudflare bypass

**Rate limiting:**
- Add delays between requests
- Use FlareSolverr for Cloudflare-protected sites

---

## Approach 2: Python Downloader Script

This is more reliable for sites that frequently change or have anti-bot protection.

### Step 1: Install Dependencies

On your Pi:

```bash
# Install Chrome (for Selenium)
sudo apt update
sudo apt install -y chromium-browser chromium-chromedriver

# Install Python dependencies
pip install requests beautifulsoup4 selenium webdriver-manager pyyaml --break-system-packages
```

### Step 2: Configure Your Series

Edit `config/sources.yaml`:

```yaml
output_directory: /mnt/manga-storage/manga-server/library/Manhwa

series:
  # Add your actual series URLs here
  - url: "https://asuracomic.net/series/solo-leveling"
    category: Manhwa
    enabled: true
    
  - url: "https://flamecomics.xyz/series/omniscient-readers-viewpoint/"
    category: Manhwa
    enabled: true
    
  - url: "https://drakecomic.org/manga/return-of-the-mount-hua-sect/"
    category: Manhua
    enabled: true
```

### Step 3: Run the Downloader

```bash
cd /mnt/manga-storage/manga-server

# Download a single series by URL
python scripts/manhwa_downloader.py \
  --url "https://asuracomic.net/series/your-series" \
  --output library/Manhwa

# Or download all series from config
python scripts/manhwa_downloader.py \
  --config config/sources.yaml
```

### Step 4: Set Up Automatic Downloads (Cron)

```bash
# Edit crontab
crontab -e

# Add this line to check for new chapters every 6 hours
0 */6 * * * cd /mnt/manga-storage/manga-server && python scripts/manhwa_downloader.py --config config/sources.yaml >> logs/downloader.log 2>&1
```

### Step 5: Trigger Kavita Scan

After downloading, Kavita needs to scan for new content:

```bash
# Create a script to download and scan
cat > /mnt/manga-storage/manga-server/scripts/update.sh << 'EOF'
#!/bin/bash
cd /mnt/manga-storage/manga-server

# Download new chapters
python scripts/manhwa_downloader.py --config config/sources.yaml

# Trigger Kavita library scan (requires API key)
# Get your JWT token from Kavita first
# curl -X POST "http://localhost:5000/api/Library/scan-all" \
#   -H "Authorization: Bearer YOUR_JWT_TOKEN"

echo "Update complete: $(date)"
EOF

chmod +x /mnt/manga-storage/manga-server/scripts/update.sh
```

---

## Hybrid Approach: Docker Container for Python Downloader

For a cleaner setup, you can run the Python downloader in Docker:

### Add to docker-compose.yml:

```yaml
  # Manhwa Downloader Service
  manhwa-downloader:
    image: python:3.11-slim
    container_name: manhwa-downloader
    volumes:
      - ./scripts:/scripts
      - ./config:/config
      - ./library:/library
      - ./logs:/logs
    environment:
      - TZ=America/Chicago
    command: >
      sh -c "
        pip install requests beautifulsoup4 selenium webdriver-manager pyyaml &&
        apt-get update && apt-get install -y chromium chromium-driver &&
        while true; do
          python /scripts/manhwa_downloader.py --config /config/sources.yaml --output /library/Manhwa
          echo 'Sleeping for 6 hours...'
          sleep 21600
        done
      "
    restart: unless-stopped
    networks:
      - manga-network
```

---

## Site-Specific Notes

### Asura Scans (asuracomic.net)

- **URL Format:** `https://asuracomic.net/series/SERIES-NAME`
- **Protection:** Cloudflare (may need FlareSolverr)
- **Notes:** 
  - Site redesigns frequently
  - Uses JavaScript for chapter loading
  - Best with Selenium/headless browser

### Flame Comics (flamecomics.xyz)

- **URL Format:** `https://flamecomics.xyz/series/SERIES-NAME/`
- **Theme:** Madara WordPress theme
- **Notes:**
  - Relatively stable structure
  - Standard selectors work well

### Drake Comics (drakecomic.org)

- **URL Format:** `https://drakecomic.org/manga/SERIES-NAME/`
- **Theme:** Similar to Asura/Reaper
- **Notes:**
  - May have anti-bot protection
  - Image URLs can be obfuscated

### Other Similar Sites

The scrapers should work with sites using similar themes:

- ReaperScans
- LuminousScans
- Manhwa18 (different structure)
- Webtoon (official, has API)

---

## Finding Series URLs

1. **Go to the site** (e.g., asuracomic.net)
2. **Search for your series**
3. **Click on the series** (not a chapter)
4. **Copy the URL** from your browser's address bar
5. **Add to sources.yaml** or use with `--url` flag

Example URLs:
```
✓ https://asuracomic.net/series/solo-leveling
✗ https://asuracomic.net/series/solo-leveling/chapter-1  (this is a chapter URL)
```

---

## Monitoring Downloads

### Check Logs

```bash
# Kaizoku logs
docker compose logs -f kaizoku

# Python downloader logs
tail -f /mnt/manga-storage/manga-server/logs/downloader.log
```

### Check Downloaded Files

```bash
# List recent downloads
ls -lt /mnt/manga-storage/manga-server/library/Manhwa/*/

# Check disk usage
du -sh /mnt/manga-storage/manga-server/library/*
```

---

## When Scrapers Break

Sites frequently change their structure. When a scraper stops working:

1. **Check if the site is up** - visit it in your browser
2. **Check for Cloudflare** - if you see a challenge page, enable FlareSolverr
3. **Inspect the HTML** - the selectors may have changed
4. **Update the scraper** - modify the CSS selectors in the Lua or Python file
5. **Check GitHub** - someone may have already fixed it

### Quick Selector Fix

If images aren't downloading, the image selector likely changed:

```bash
# In browser, right-click an image > Inspect
# Find the pattern for image elements
# Update the scraper's selector
```

---

## Legal Reminder

Remember that downloading copyrighted content without authorization may violate laws in your jurisdiction. Consider:

- Supporting official releases when available
- Using legal platforms like Webtoon, Tapas, Tappytoon
- Checking if the content is officially free

This setup is intended for personal archival and convenience.
