# Manga Server - Complete Setup Guide

A self-hosted manga/manhwa/manhua server with automatic downloading, metadata fetching, and iPhone access.

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         Your Server                                 │
│                                                                     │
│  ┌──────────────┐     ┌─────────────┐     ┌──────────────┐        │
│  │   Kaizoku    │────▶│   Library   │◀────│    Kavita    │        │
│  │ (Downloader) │     │   /Manga    │     │   (Reader)   │        │
│  └──────────────┘     │   /Manhwa   │     └──────┬───────┘        │
│         │             │   /Manhua   │            │                 │
│         ▼             └─────────────┘            │                 │
│  ┌──────────────┐                         ┌──────┴───────┐        │
│  │ FlareSolverr │                         │     Komf     │        │
│  │  (CF Bypass) │                         │  (Metadata)  │        │
│  └──────────────┘                         └──────────────┘        │
│                                                                     │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ Cloudflare Tunnel
                              ▼
                        ┌──────────┐
                        │  iPhone  │
                        └──────────┘
```

## Components

| Service | Purpose | Port |
|---------|---------|------|
| Kavita | Reading server & library management | 5000 |
| Kaizoku | Download manager with scheduling | 3000 |
| Komf | Automatic metadata & cover fetching | 8085 |
| FlareSolverr | Bypasses Cloudflare protection | 8191 |

---

## Hardware Recommendations

### Option 1: Synology NAS (Recommended)
**Model:** DS224+ or DS423+
**Storage:** 2-4 TB drives in RAID 1
**Cost:** ~$300-500 + drives

**Pros:**
- Built for 24/7 operation
- Native Docker support via Container Manager
- Easy web interface
- Expandable storage
- Low power consumption

### Option 2: Mini PC
**Models:** Beelink Mini S12 Pro, Intel NUC, Mac Mini
**Storage:** Internal SSD + external HDD
**Cost:** ~$200-400

**Pros:**
- More processing power
- Can run other services
- Flexible OS choice

### Option 3: Raspberry Pi 5
**Model:** Pi 5 8GB
**Storage:** USB 3.0 external drive
**Cost:** ~$100-150

**Pros:**
- Very low cost
- Minimal power usage
- Silent operation

### Storage Sizing Guide

| Collection Size | Estimated Storage |
|----------------|-------------------|
| 100 manga series | ~50-100 GB |
| 500 manga series | ~250-500 GB |
| 1000+ series | 500 GB - 1 TB |
| With manhwa (more images) | Add 50% more |

**Recommendation:** Start with 2 TB, expand as needed.

---

## Quick Start

### 1. Prepare Your Server

```bash
# Install Docker (Ubuntu/Debian)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install docker-compose-plugin

# Create project directory
mkdir -p ~/manga-server && cd ~/manga-server
```

### 2. Download Configuration

Copy all files from this package to your server, or clone/download them.

### 3. Create Directory Structure

```bash
mkdir -p config/{kavita,komf,kaizoku/{logs,db,redis}}
mkdir -p library/{Manga,Manhwa,Manhua}
```

### 4. Start Services

```bash
docker compose up -d
```

### 5. Initial Configuration

#### Kavita Setup (http://your-server:5000)
1. Create admin account
2. Add libraries:
   - Name: "Manga" → Path: `/library/Manga`
   - Name: "Manhwa" → Path: `/library/Manhwa`
   - Name: "Manhua" → Path: `/library/Manhua`
3. Settings → General → Copy API Key

#### Komf Setup
Edit `config/komf/application.yml`:
```yaml
kavita:
  apiKey: "YOUR_API_KEY_HERE"
```
Then restart: `docker compose restart komf`

#### Kaizoku Setup (http://your-server:3000)
1. Open Kaizoku web UI
2. Go to Settings
3. Set download path: `/data/Manga` (maps to library/Manga)
4. Configure sources (see below)

---

## Using Kaizoku (Download Manager)

Kaizoku provides a web interface to search and download manga from various sources.

### Adding Manga

1. Go to Kaizoku UI → Search
2. Search for a manga title
3. Select source and add to library
4. Kaizoku will download existing chapters

### Setting Up Auto-Download

1. Go to Settings → Jobs
2. Configure check interval (e.g., every 6 hours)
3. New chapters will download automatically

### Available Sources

Kaizoku uses **mangal** which supports many sources including:
- MangaDex (fan translations, legal)
- MangaSee
- MangaPlus (official Shonen Jump)
- Webtoons (official)
- And many more...

To see all sources:
```bash
docker exec -it kaizoku mangal sources list
```

### Adding Custom Sources

```bash
# Install a custom source
docker exec -it kaizoku mangal sources install <source-name>
```

---

## Alternative Download Tools

If you prefer command-line tools or different interfaces:

### HakuNeko (Desktop App)
Cross-platform GUI application with many sources.
- Download: https://hakuneko.download/
- Run on your desktop, save to server via network share

### manga-py (Python CLI)
```bash
pip install manga-py
manga-py --help

# Example: Download from MangaDex
manga-py "https://mangadex.org/title/..." -d /path/to/library/Manga/
```

### gallery-dl (Python CLI)
More general image downloader, works with many sites:
```bash
pip install gallery-dl
gallery-dl "https://mangadex.org/title/..."
```

---

## Automation Script

For custom automation, here's a Python script template:

```python
#!/usr/bin/env python3
"""
manga_sync.py - Automated manga download and organization
"""

import subprocess
import os
from pathlib import Path
import schedule
import time

# Configuration
LIBRARY_PATH = "/path/to/library"
SOURCES = {
    "manga": [
        "https://mangadex.org/title/xxxxx/one-piece",
        "https://mangadex.org/title/xxxxx/chainsaw-man",
    ],
    "manhwa": [
        "https://mangadex.org/title/xxxxx/solo-leveling",
    ],
}

def download_series(url: str, category: str):
    """Download a manga series using gallery-dl or manga-py"""
    output_dir = Path(LIBRARY_PATH) / category.capitalize()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Using gallery-dl (adjust command as needed)
    cmd = [
        "gallery-dl",
        "--dest", str(output_dir),
        "--chapter-range", "1-",  # All chapters
        url
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print(f"✓ Downloaded: {url}")
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed: {url} - {e}")

def sync_all():
    """Sync all configured series"""
    print("Starting manga sync...")
    for category, urls in SOURCES.items():
        for url in urls:
            download_series(url, category)
    print("Sync complete!")
    
    # Trigger Kavita scan
    # curl -X POST "http://kavita:5000/api/Library/scan-all" -H "..."

if __name__ == "__main__":
    # Run once immediately
    sync_all()
    
    # Schedule periodic runs
    schedule.every(6).hours.do(sync_all)
    
    while True:
        schedule.run_pending()
        time.sleep(60)
```

---

## iPhone Setup

### PWA Installation (Recommended)

1. Open Safari on iPhone
2. Navigate to your Kavita URL
3. Tap Share → "Add to Home Screen"
4. Name it and tap Add

### Reading Settings for Manhwa/Manhua

In the Kavita reader (tap gear icon):
- **Reading Direction:** Top to Bottom
- **Scaling:** Width
- **Background:** Black
- **Auto Close Menu:** On

### Offline Reading

The PWA caches recently read content. For true offline:
1. Use Panels app ($) with OPDS
2. Download chapters within the app

---

## Maintenance

### Regular Tasks

```bash
# Update all containers
docker compose pull && docker compose up -d

# Check logs
docker compose logs -f

# Disk usage
du -sh library/*

# Backup config (not library - too large)
tar -czf backup-config.tar.gz config/
```

### Trigger Library Scan

After adding new content manually:
- Kavita UI → Library → Scan Library
- Or Kaizoku will trigger scans automatically

---

## Troubleshooting

### Kaizoku can't find manga
- Try different sources
- Check FlareSolverr is running: `docker logs flaresolverr`
- Some sites block datacenter IPs

### Downloads are slow
- Some sources rate-limit
- Run downloads during off-peak hours
- Consider a VPN if your ISP throttles

### Metadata not appearing
- Check Komf logs: `docker logs komf`
- Verify API key is correct
- Some obscure series may not have metadata

### iPhone can't connect
- Ensure HTTPS is configured (required for PWA)
- Check Cloudflare Tunnel status
- Try accessing from same network first

---

## Legal Considerations

Please be aware:
- Downloading copyrighted content without authorization may violate laws in your jurisdiction
- Some sources like MangaPlus, Webtoons, and parts of MangaDex host officially licensed content
- Consider supporting creators by purchasing official releases
- This setup is intended for personal archival and convenience

---

## File Organization Best Practices

Kavita works best with this structure:

```
library/
├── Manga/
│   ├── Series Name/
│   │   ├── Series Name v01.cbz
│   │   ├── Series Name v02.cbz
│   │   └── ...
│   └── Another Series/
│       └── ...
├── Manhwa/
│   ├── Solo Leveling/
│   │   ├── Chapter 001.cbz
│   │   └── ...
│   └── ...
└── Manhua/
    └── ...
```

Kaizoku will organize downloads automatically.
