# Complete Raspberry Pi Manga Server Setup Guide

A step-by-step guide to building a self-hosted manga server on a Raspberry Pi with remote access, using **ORVault** as the reading front-end.

---

## Where Each Step Is Done

Before we begin, here's a quick reference for where you'll be working:

| Part | Where You Do It |
|------|-----------------|
| **Part 1-2**: Buy hardware, flash SD card | Your computer |
| **Part 3**: Find Pi's IP, SSH in | Your computer (terminal) |
| **Part 4-7**: System setup, mount drive, Docker, create files | **SSH into Pi** |
| **Part 8**: Configure ORVault | Web browser → `http://PI_IP:3001` |
| **Part 9**: Configure Kaizoku (optional) | Web browser → `http://PI_IP:3000` |
| **Part 10**: Cloudflare Tunnel | Split - see below |
| **Part 11**: iPhone setup | Your iPhone |
| **Part 12**: Custom sources | **SSH into Pi** |
| **Part 13**: Add users | Web browser (ORVault UI) |
| **Part 14**: Maintenance | **SSH into Pi** |

**Part 10 Breakdown:**
| Step | Where |
|------|-------|
| Create Cloudflare account | Web browser (any device) |
| Create tunnel, get token | Cloudflare dashboard (browser) |
| Edit docker-compose.yml | **SSH into Pi** |
| Configure public hostname | Cloudflare dashboard (browser) |

---

## Table of Contents

1. [Hardware Shopping List](#part-1-hardware-shopping-list)
2. [Flash the Operating System](#part-2-flash-the-operating-system)
3. [Connect to Your Pi](#part-3-connect-to-your-pi)
4. [Initial System Setup](#part-4-initial-system-setup)
5. [Mount the External Drive](#part-5-mount-the-external-drive)
6. [Install Docker](#part-6-install-docker)
7. [Set Up the Manga Server](#part-7-set-up-the-manga-server)
8. [Configure ORVault (Reader)](#part-8-configure-orvault-reader)
9. [Configure Kaizoku (Downloads — Optional)](#part-9-configure-kaizoku-downloads--optional)
10. [Set Up Remote Access (Cloudflare Tunnel)](#part-10-set-up-remote-access-cloudflare-tunnel)
11. [Set Up iPhone](#part-11-set-up-iphone)
12. [Adding Custom Sources (Asura, Flame, ManhuaTo, Webtoon)](#part-12-adding-custom-sources)
13. [Multi-User Setup](#part-13-multi-user-setup)
14. [Maintenance & Troubleshooting](#part-14-maintenance--troubleshooting)

---

## Part 1: Hardware Shopping List

### Required Items

| Item | Recommended | Price | Where to Buy |
|------|-------------|-------|--------------|
| Raspberry Pi 5 (8GB) | 8GB model | ~$80 | RPi Official, Amazon, Microcenter |
| USB-C Power Supply | Official 27W PSU | ~$12 | Same as above |
| MicroSD Card | Samsung EVO 32GB+ | ~$10 | Amazon |
| Case with Cooling | Official Active Cooler case | ~$15-25 | Amazon, Adafruit |
| 1TB External HDD/SSD | Any USB 3.0 drive | ~$50-80 | Amazon, Best Buy |
| Ethernet Cable | Cat6 | ~$5 | Amazon |

**Total: ~$170-210**

### My Specific Recommendations

- **Pi:** Raspberry Pi 5 8GB (4GB works but 8GB is better for Docker)
- **Power:** Official Raspberry Pi 27W USB-C Power Supply (don't cheap out!)
- **Storage:** Samsung T7 1TB SSD (~$80) or WD Elements 1TB HDD (~$50)
- **Case:** Argon NEO 5 or Official Active Cooler Case
- **SD Card:** Samsung EVO Select 64GB (~$10)

### SSD vs HDD?

| Factor | HDD | SSD |
|--------|-----|-----|
| Library scanning | Slow (minutes) | Fast (seconds) |
| Page load time | Slight delay | Instant |
| Power consumption | 5-10W | 0.5-2W |
| Noise | Audible | Silent |
| Cost per TB | ~$15-20 | ~$50-80 |

**Recommendation:** HDD is fine for manga storage. The files stream sequentially and HDDs handle this well.

---

## Part 2: Flash the Operating System

### Step 2.1: Download Raspberry Pi Imager

1. Go to: https://www.raspberrypi.com/software/
2. Download "Raspberry Pi Imager" for your OS (Mac/Windows/Linux)
3. Install and open it

### Step 2.2: Flash the SD Card

1. Insert your MicroSD card into your computer

2. In Raspberry Pi Imager:
   - **Choose Device:** Raspberry Pi 5
   - **Choose OS:** Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**
   - **Choose Storage:** Select your SD card

3. Click the **gear icon** (⚙️) or "Edit Settings":

   **General tab:**
   ```
   ☑ Set hostname: manga-server
   ☑ Set username and password:
     Username: pi
     Password: [choose a strong password]
   ☑ Configure wireless LAN (if using WiFi):
     SSID: [your WiFi name]
     Password: [your WiFi password]
     Country: US
   ☑ Set locale settings:
     Time zone: [your timezone]
     Keyboard layout: us
   ```

   **Services tab:**
   ```
   ☑ Enable SSH
     ○ Use password authentication
   ```

4. Click **Save**, then **Write**
5. Wait for it to finish (~5-10 minutes)

### Step 2.3: First Boot

1. Insert the SD card into your Raspberry Pi
2. Connect the external drive to a **blue USB 3.0 port**
3. Connect Ethernet cable (recommended) or use WiFi
4. Connect power - it will boot automatically
5. Wait 2-3 minutes for first boot to complete

---

## Part 3: Connect to Your Pi

### Step 3.1: Find Your Pi's IP Address

**Option A: Check your router**
- Log into your router's admin page (usually 10.14.7.249)
- Look for a device named "manga-server"

**Option B: Use terminal**

```bash
# Mac/Linux
ping manga-server.local

# Windows PowerShell
ping manga-server.local
```

Note the IP address (e.g., 10.14.7.XXX)

### Step 3.2: SSH Into Your Pi

```bash
ssh pi@manga-server.local
```
Or:
```bash
ssh pi@10.14.7.XXX
```

When prompted:
- Type `yes` to accept the fingerprint
- Enter your password

You should see:
```
pi@manga-server:~ $
```

🎉 **You're connected!**

---

## Part 4: Initial System Setup

### Step 4.1: Update the System

```bash
sudo apt update && sudo apt upgrade -y
```

### Step 4.2: Install Essential Tools

```bash
sudo apt install -y vim htop curl wget git
```

### Step 4.3: Set a Static IP (Recommended)

```bash
sudo nmtui
```

1. Select "Edit a connection"
2. Select your connection (Wired or WiFi)
3. Change IPv4 to "Manual"
4. Add:
   - Address: `10.14.7.100/24`
   - Gateway: `10.14.7.249`
   - DNS: `8.8.8.8, 8.8.4.4`
5. OK → Back → Quit

Reboot:
```bash
sudo reboot
```

Reconnect:
```bash
ssh pi@10.14.7.100
```

---

## Part 5: Mount the External Drive

### Step 5.1: Identify the Drive

```bash
lsblk
```

Your external drive is likely `sda` or `sda1`.

### Step 5.2: Format the Drive (if needed)

⚠️ **WARNING: This erases everything!**

```bash
sudo parted /dev/sda --script mklabel gpt
sudo parted /dev/sda --script mkpart primary ext4 0% 100%
sudo mkfs.ext4 -L manga-storage /dev/sda1
```

### Step 5.3: Create Mount Point

```bash
sudo mkdir -p /mnt/manga-storage
```

### Step 5.4: Get the Drive's UUID

```bash
sudo blkid /dev/sda1
```

Copy the UUID value.

### Step 5.5: Configure Automatic Mounting

```bash
sudo nano /etc/fstab
```

Add this line (replace YOUR-UUID):
```
UUID=YOUR-UUID-HERE /mnt/manga-storage ext4 defaults,nofail 0 2
```

Save: `Ctrl+O`, `Enter`, `Ctrl+X`

### Step 5.6: Mount and Verify

```bash
sudo mount -a
df -h | grep manga
```

### Step 5.7: Set Permissions

```bash
sudo chown -R pi:pi /mnt/manga-storage
```

---

## Part 6: Install Docker

### Step 6.1: Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
```

### Step 6.2: Add User to Docker Group

```bash
sudo usermod -aG docker pi
```

### Step 6.3: Log Out and Back In

```bash
exit
```

Then:
```bash
ssh pi@10.14.7.100
```

### Step 6.4: Verify Docker Works

```bash
docker --version
docker run hello-world
```

### Step 6.5: Install Docker Compose

```bash
sudo apt install -y docker-compose-plugin
docker compose version
```

---

## Part 7: Set Up the Manga Server

### Step 7.1: Clone/Copy the Project

The manga server project includes ORVault (the custom reader front-end), Python scrapers, and Docker configuration.

**Option A: Clone from a repository (if you have one set up)**
```bash
cd /mnt/manga-storage
git clone <your-repo-url> manga-server
cd manga-server
```

**Option B: Copy from your computer**
```bash
# On your computer, copy the project to the Pi
scp -r /path/to/manga-server-full pi@10.14.7.100:/mnt/manga-storage/manga-server
```

### Step 7.2: Ensure Directory Structure

```bash
cd /mnt/manga-storage/manga-server
mkdir -p library/{Manga,Manhwa,Manhua,LightNovels}
mkdir -p mangashelf/data
mkdir -p mangashelf/public/covers
mkdir -p logs scripts
```

### Step 7.3: Docker Compose File

The project includes `docker-compose-custom-sources.yml`. This is the main compose file with all services. You can either rename it or reference it directly:

```bash
# Option A: Rename to default
cp docker-compose-custom-sources.yml docker-compose.yml

# Option B: Use -f flag with all docker commands
docker compose -f docker-compose-custom-sources.yml up -d
```

The compose file includes the following services:

| Service | Purpose | Port |
|---------|---------|------|
| **vpn** | VPN tunnel (Gluetun) — routes scraper traffic so your IP is hidden | 8191 (for FlareSolverr) |
| **orvault** | ORVault reading front-end (Next.js) | 3001 → 3000 |
| **manhwa-downloader** | Custom Python scraper (routed through VPN) | — |
| **flaresolverr** | Cloudflare bypass for scrapers (routed through VPN) | — |
| **cloudflared** | Cloudflare tunnel for remote access | — |
| kavita (optional) | Legacy reading server (commented out) | 5000 |
| komf (optional) | Metadata fetcher for Kavita (commented out) | — |
| kaizoku (optional) | Download manager / MangaDex (commented out) | 3000 |

The `manhwa-downloader` and `flaresolverr` both use `network_mode: "service:vpn"`, which means all their network traffic goes through the VPN container. Your real IP is never exposed to scraping target sites.

> **Note:** Kavita, Komf, and Kaizoku are commented out by default. ORVault replaces Kavita as the primary reader. Uncomment them in the compose file if you still need them.

### Step 7.4: Configure Environment Variables

Before starting, update the environment variables in your compose file:

1. **VPN credentials** — In the `vpn` service, configure your VPN provider. The compose file includes commented config blocks for Mullvad, ProtonVPN, Surfshark, and NordVPN. Uncomment the one you use and fill in your credentials. See [Gluetun provider docs](https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers) for full details.

2. **NEXTAUTH_SECRET** — Change to a random secret string:
   ```bash
   openssl rand -base64 32
   ```
   Copy the output and replace `change-me-to-a-random-secret-in-production` in the compose file.

3. **NEXTAUTH_URL** — Set to your public domain (e.g., `https://manga.yourdomain.com`) or your Pi's local URL (e.g., `http://10.14.7.100:3001`).

4. **TUNNEL_TOKEN** — Replace with your Cloudflare tunnel token (see Part 10).

### Step 7.5: Build and Start

```bash
cd /mnt/manga-storage/manga-server
docker compose build orvault
docker compose up -d
```

The first build takes several minutes on a Raspberry Pi (compiling Next.js). Subsequent starts are fast.

### Step 7.6: Verify Everything is Running

```bash
docker compose ps
```

All services should show "Up". ORVault should be accessible at `http://10.14.7.100:3001`.

### Step 7.7: Verify VPN is Working

Confirm the VPN container is healthy and your scraper traffic is using the VPN IP:

```bash
# Check VPN container logs for successful connection
docker compose logs vpn | tail -20

# Verify the VPN IP (should NOT be your real IP)
docker exec vpn wget -qO- https://ipinfo.io/ip
```

If the VPN shows a different IP than your home IP, scraper traffic is properly anonymized.

---

## Part 8: Configure ORVault (Reader)

ORVault is a custom manga/manhwa reading front-end built with Next.js. It scans your library folder for CBZ files, reads their ComicInfo.xml metadata, and provides a web-based reader with progress tracking.

### Step 8.1: Access ORVault

Open in browser:
```
http://10.14.7.100:3001
```

### Step 8.2: Create Admin Account (First-Time Setup)

On the first visit, ORVault redirects to the setup page:

1. Enter a **username** and **password** (min 6 characters)
2. Click **Create Account**
3. You'll be redirected to the login page
4. Log in with your new credentials

This creates the admin account with full access to the admin panel.

### Step 8.3: Run Initial Library Scan

1. Click **Admin** in the navigation bar (or go to `/admin`)
2. Click **Scan Library** to trigger a manual scan
3. Wait for the scan to complete — it will find all CBZ files in `/library` and import series, chapters, and metadata

The scanner automatically:
- Creates series from folder names
- Imports chapters from CBZ files (reading chapter number from filename pattern `Title - Chapter X.cbz`)
- Extracts metadata from ComicInfo.xml (title, author, artist, genres, rating, description, cover)
- Generates cover thumbnails

### Step 8.4: Configure Auto-Scan

In the Admin panel:
1. Find the **Auto Scan Interval** dropdown
2. Select your preferred interval (5 min, 15 min, 30 min, 1 hr, 2 hr, 6 hr, or Disabled)
3. The setting is saved immediately and persists across restarts

This automatically rescans the library at the chosen interval to pick up new downloads.

### Step 8.5: Explore the Interface

**Homepage** — Shows three sections (when logged in):
- **New from Followed**: New chapters from series you follow (hidden once you've read them)
- **Continue Reading**: Series you're actively reading with progress info
- **Recently Updated**: All series sorted by latest chapter added, showing chapter number and time

**Browse** — Full library with search, genre filters, type filters, and sort options (A-Z, Z-A, recently updated, oldest)

**My List** — Personal tracking with tabs:
- **All**: Every series you've added to your list
- **Following**: Series you follow for update notifications
- **In Progress**: Series with active reading progress (auto-populated)
- **Reading / Plan to Read / Completed / On Hold / Dropped**: Manual status categories

**Reader** — Full-featured manga reader with:
- Single page, double page, double (manga R-to-L), and longstrip/webtoon modes
- Width/height/original scaling
- LTR/RTL reading direction
- Brightness control, background color options
- Swipe navigation, auto-hide toolbar
- Keyboard shortcuts (arrow keys, A/D, F for fit, M for menu, Esc for toolbar)
- Progress tracking (auto-saves every 2 seconds and on navigation/page close)
- Chapter picker dropdown for quick navigation
- Scroll-based chapter traversal in longstrip mode

**Settings** — Appearance (themes, custom colors, items per row), reader defaults, account management

### Step 8.6: Follow Series

To get "New from Followed" notifications:
1. Go to a series page
2. Click the **Follow** button
3. New chapters for followed series will appear on your homepage

---

## Part 9: Configure Kaizoku (Downloads — Optional)

Kaizoku is a download manager for manga from supported sources like MangaDex. It's optional if you're using the custom Python scrapers exclusively.

### Step 9.1: Access Kaizoku

```
http://10.14.7.100:3000
```

### Step 9.2: Add Your First Manga

1. Click **"Add Series"** or **+**
2. Search for a manga (e.g., "One Punch Man")
3. Select a source (MangaDex is most reliable)
4. Click to add it
5. Downloads start automatically

### Step 9.3: Configure Auto-Downloads

In Settings, set check interval (e.g., every 6 hours).

### Step 9.4: Run Database Migration (First Startup Only)

On the very first startup, Kaizoku needs its database schema initialized:

```bash
docker exec kaizoku npx prisma migrate deploy
```

If you see "All migrations have been successfully applied", you're good. If the container isn't ready yet, wait 30 seconds and try again.

> **Note:** You only need to run this once. After the initial migration, Kaizoku handles database updates automatically.

---

## Part 10: Set Up Remote Access (Cloudflare Tunnel)

### Step 10.1: Create Cloudflare Account

1. Go to https://dash.cloudflare.com/sign-up
2. Create a free account
3. Add your domain (or use their free tunnel subdomain)

### Step 10.2: Create a Tunnel

1. Go to https://one.dash.cloudflare.com/
2. Click **Networks** → **Tunnels** → **Create a tunnel**
3. Name it: `manga-server`
4. Copy the tunnel token

### Step 10.3: Add Token to Docker Compose

Edit your compose file and replace `YOUR_TOKEN_HERE` in the `cloudflared` service with your actual tunnel token.

Restart:
```bash
docker compose up -d
```

### Step 10.4: Configure Public Hostname

In Cloudflare dashboard:
1. Add a **Public Hostname**:
   - Subdomain: `manga`
   - Domain: your domain
   - Service Type: `HTTP`
   - URL: `orvault:3000`
2. Save

> **Important:** The URL is `orvault:3000` (the internal Docker container name and port), NOT the external port 3001. Docker services communicate on the internal network.

### Step 10.5: Update NEXTAUTH_URL

In your compose file, set the `NEXTAUTH_URL` environment variable for the orvault service to your public domain:
```yaml
- NEXTAUTH_URL=https://manga.yourdomain.com
```

Then restart ORVault:
```bash
docker compose up -d orvault
```

### Step 10.6: Test

Open: `https://manga.yourdomain.com`

> **Important notes about Cloudflare Tunnel:**
> - The **Service Type** in Cloudflare's public hostname config should be **HTTP** (not HTTPS), because traffic between the tunnel and ORVault is internal Docker network traffic (unencrypted is fine).
> - External access is always **HTTPS** — Cloudflare handles TLS termination automatically. Users always connect via `https://manga.yourdomain.com`.
> - If you see `connIndex=3` QUIC connection errors in the cloudflared logs, these are **cosmetic and harmless**. Cloudflared opens 4 QUIC connections (index 0-3) and sometimes one fails. The tunnel works fine with 3 out of 4 connections.

---

## Part 11: Set Up iPhone

### Install as PWA

1. Open **Safari** on iPhone
2. Go to `https://manga.yourdomain.com`
3. Log in
4. Tap **Share** → **Add to Home Screen**
5. Name it "ORVault" (or whatever you prefer)

Now you have an app-like experience!

> **Tip:** Installing as a PWA (Add to Home Screen) gives you fullscreen mode, push-like behavior, and proper viewport sizing. The PWA runs in its own window with correct viewport settings, so everything displays at the right size.

---

## Part 12: Adding Custom Sources

For sites like Asura Scans, Flame Comics, ManhuaTo, and Webtoon that Kaizoku doesn't support natively.

### Step 12.1: Install Dependencies

**Option A: Use the install script (recommended)**

```bash
cd /mnt/manga-storage/manga-server
bash scripts/install_dependencies.sh
```

This automatically installs all system packages, Python dependencies, and Docker. It detects your architecture (Raspberry Pi, x86_64) and handles everything.

**Option B: Manual installation**

```bash
sudo apt install -y python3-pip chromium-browser chromium-chromedriver
pip install -r requirements.txt --break-system-packages
```

Or install packages individually:
```bash
pip install requests beautifulsoup4 lxml selenium webdriver-manager pyyaml --break-system-packages
pip install undetected-chromedriver --break-system-packages   # Anti-bot bypass (required for Asura, Drake)
pip install ebooklib --break-system-packages                  # EPUB creation (required for light novels)
pip install Pillow --break-system-packages                    # Image processing
```

### Step 12.2: Create the Scraper Script

```bash
cd /mnt/manga-storage/manga-server
nano scripts/manhwa_scraper.py
```

**Note:** The full script is included in the project. It's ~3100+ lines. Key features:
- Supports: Asura Scans, Flame Comics, Drake Comics, ManhuaTo, Webtoon
- Full site scraping or individual series download
- Advanced filtering (genres, status, rating, chapter count)
- Resume interrupted downloads with progress tracking
- CBZ creation with embedded ComicInfo.xml metadata (ORVault-compatible)
- Anti-bot bypass via undetected-chromedriver (for Cloudflare-protected sites)
- `--limit` flag to cap results during testing

### Step 12.3: Create Sources Config

```bash
nano config/sources.yaml
```

```yaml
series:
  # Asura Scans
  - title: "Solo Leveling"
    url: "https://asuracomic.net/series/solo-leveling"
    source: asura
    enabled: true

  # ManhuaTo
  - title: "The Beginning After The End"
    url: "https://manhuato.com/manhua/the-beginning-after-the-end"
    source: manhuato
    enabled: true

  # Webtoon (free chapters only)
  - title: "Tower of God"
    url: "https://www.webtoons.com/en/fantasy/tower-of-god/list?title_no=95"
    source: webtoon
    enabled: true
```

### Step 12.4: Run the Scraper

```bash
cd /mnt/manga-storage/manga-server

# List all series from a site
python3 scripts/manhwa_scraper.py --site asura --list-all -o asura_series.yaml

# Download from your config
python3 scripts/manhwa_scraper.py --config config/sources.yaml -o library/Manhwa

# Download all from a site (warning: lots of data!)
python3 scripts/manhwa_scraper.py --site manhuato --download-all -o library/Manhwa
```

### Step 12.5: Keyword Filtering (OR vs AND)

You can filter by genres or title keywords. There are two modes:

**OR Logic (`--filter`)** - Matches series with ANY of the terms:
```bash
# Series that are action OR fantasy OR drama
python3 scripts/manhwa_scraper.py --site asura --list-all --filter "action,fantasy,drama" -o filtered.yaml
```

**AND Logic (`--filter-all`)** - Matches series with ALL of the terms:
```bash
# Series that are BOTH action AND fantasy
python3 scripts/manhwa_scraper.py --site asura --list-all --filter-all "action,fantasy" -o action_fantasy.yaml
```

**Combine both:**
```bash
# Must be fantasy (AND), can be action or adventure (OR)
python3 scripts/manhwa_scraper.py --site asura --list-all --filter "action,adventure" --filter-all "fantasy" -o filtered.yaml
```

| Flag | Logic | Example | Matches |
|------|-------|---------|---------|
| `--filter "a,b,c"` | OR | `--filter "action,romance"` | Action OR Romance |
| `--filter-all "a,b"` | AND | `--filter-all "action,fantasy"` | Action AND Fantasy |

### Step 12.6: Chapter Count Filtering

You can filter series by how many chapters they have. This is useful for finding established series.

```bash
# List all series WITH chapter counts (slower but more useful)
python3 scripts/manhwa_scraper.py --site asura --list-all --with-chapters -o asura_series.yaml

# Only list series with 50+ chapters
python3 scripts/manhwa_scraper.py --site asura --list-all --min-chapters 50 -o popular.yaml

# Only download series with 100+ chapters
python3 scripts/manhwa_scraper.py --site asura --download-all --min-chapters 100 -o library/Manhwa

# Series with 20-100 chapters (mid-length, not too short or long)
python3 scripts/manhwa_scraper.py --site asura --list-all --min-chapters 20 --max-chapters 100 -o mid_series.yaml

# Combine keyword AND chapter filters: action+fantasy manhwa with 50+ chapters
python3 scripts/manhwa_scraper.py --site asura --download-all --filter-all "action,fantasy" --min-chapters 50 -o library/
```

**Chapter count options:**

| Flag | What It Does |
|------|--------------|
| `--with-chapters` | Fetch chapter counts and status (slower but enables filtering) |
| `--min-chapters N` | Only include series with N or more chapters |
| `--max-chapters N` | Only include series with N or fewer chapters |

**Note:** Fetching chapter counts requires visiting each series page, so it's slower (~1-2 sec per series). For 200 series, expect 5-10 minutes.

### Step 12.6b: Status Filtering

You can filter series by their publication status (Ongoing, Completed, Hiatus, Dropped).

```bash
# List only completed series
python3 scripts/manhwa_scraper.py --site asura --list-all --status completed -o completed.yaml

# List only ongoing series
python3 scripts/manhwa_scraper.py --site asura --list-all --status ongoing -o ongoing.yaml

# Download completed action series
python3 scripts/manhwa_scraper.py --site asura --download-all --filter "action" --status completed -o library/

# Multiple statuses: completed or hiatus
python3 scripts/manhwa_scraper.py --site asura --list-all --status "completed,hiatus" -o finished.yaml

# The ultimate filter: Completed fantasy series with 100+ chapters
python3 scripts/manhwa_scraper.py --site asura --download-all --filter-all "fantasy" --status completed --min-chapters 100 -o library/
```

**Available statuses:**
- `ongoing` - Series still being updated
- `completed` - Series finished
- `hiatus` - Series on break
- `dropped` - Series cancelled

**Note:** Using `--status` automatically fetches series details (same as `--with-chapters`).

The YAML output includes a status breakdown:
```yaml
generated: '2026-02-02T20:00:00'
total_series: 150
total_chapters: 8500
status_breakdown:
  Ongoing: 85
  Completed: 45
  Hiatus: 15
  Unknown: 5
series:
  - title: "Solo Leveling"
    status: Completed
    chapters: 200
    ...
```

### Step 12.6c: Rating Filtering

You can filter series by their community rating (on a 5-point scale).

```bash
# List only highly-rated series (4.0+ out of 5)
python3 scripts/manhwa_scraper.py --site asura --list-all --min-rating 4.0 -o highly_rated.yaml

# Completed series with 4.5+ rating and 100+ chapters (quality binge!)
python3 scripts/manhwa_scraper.py --site asura --list-all --status completed --min-rating 4.5 --min-chapters 100 -o best_completed.yaml

# Download only top-rated fantasy series
python3 scripts/manhwa_scraper.py --site asura --download-all --filter "fantasy" --min-rating 4.0 -o library/
```

**Note:** Using `--min-rating` automatically fetches series details (same as `--with-chapters`).

The YAML output includes rating stats:
```yaml
generated: '2026-02-02T20:00:00'
total_series: 150
series_with_ratings: 142
average_rating: 4.23
series:
  - title: "Solo Leveling"
    rating: 4.8
    status: Completed
    chapters: 200
    author: "Chugong"
    artist: "DUBU"
    description: "In a world where hunters must..."
    ...
```

### Metadata in ORVault

When you download series, the scraper embeds full metadata in each CBZ file as `ComicInfo.xml`. ORVault's library scanner automatically reads these fields during import:

| ComicInfo.xml Field | What ORVault Uses It For |
|---------------------|--------------------------|
| `Series` | Series title |
| `Number` | Chapter number (sorting, display) |
| `Title` | Chapter title |
| `Genre` | Genre tags (browse filters) |
| `Tags` | Additional tags |
| `Summary` | Series description on detail page |
| `CommunityRating` | Star rating display |
| `Writer` | Author name |
| `Penciller` | Artist name |
| `Publisher` | Source site label (e.g., "Asura Scans") |
| `Web` | Source URL (multi-source tracking) |
| `LanguageISO` | Language code (`en`) |
| `Format` | "Web Comic" |
| `AgeRating` | Content rating |
| `Notes` | Source attribution + publication status |

**Cover Images:** The scraper automatically handles cover art:
- Extracts cover/thumbnail images from the source site
- Embeds the cover inside each CBZ file as `!000_cover.jpg` (the `!` prefix ensures it sorts first)
- Downloads a `cover.jpg` to the series folder as a fallback

**Multi-Source Support:** ORVault tracks the source of each chapter via the `Web` field in ComicInfo.xml. On the series detail page, you can see source badges and filter chapters by source when chapters come from different sites.

### Step 12.7: Scrape ALL Sites at Once

Use `--site all` to scrape from all supported sites in one command. This automatically adds the `[Source]` prefix to keep series organized.

```bash
# List series from ALL sites
python3 scripts/manhwa_scraper.py --site all --list-all -o all_series.yaml

# List series with 50+ chapters from ALL sites
python3 scripts/manhwa_scraper.py --site all --list-all --min-chapters 50 -o popular_all.yaml

# Download from ALL sites (warning: this is a LOT of data!)
python3 scripts/manhwa_scraper.py --site all --download-all -o library/

# Download action series with 100+ chapters from ALL sites
python3 scripts/manhwa_scraper.py --site all --download-all --filter "action" --min-chapters 100 -o library/
```

This will create folders like:
```
library/
├── [Asura] Solo Leveling/
├── [Flame] Solo Leveling/
├── [Manhuato] Solo Leveling/
├── [Webtoon] Solo Leveling/
└── ...
```

**Sites included in `--site all`:**
- Asura Scans
- Flame Comics
- Drake Comics
- ManhuaTo
- Webtoon (ORIGINALS only, not CANVAS)

### Step 12.8: Multi-Source Comparison (Single Series)

Use `--source-prefix` to compare same series from different sites:

```bash
python3 scripts/manhwa_scraper.py --site asura --filter "solo leveling" --source-prefix -o library/
python3 scripts/manhwa_scraper.py --site webtoon --filter "solo leveling" --source-prefix -o library/
```

Creates separate folders:
```
library/
├── [Asura] Solo Leveling/
└── [Webtoon] Solo Leveling/
```

### Step 12.9: Set Up Automatic Downloads

You can automate daily scraping using cron:

```bash
crontab -e
```

Add:
```
# Manhwa scraper - runs every 6 hours
0 */6 * * * cd /mnt/manga-storage/manga-server && python3 scripts/manhwa_scraper.py --config config/sources.yaml -o library/Manhwa >> logs/scraper.log 2>&1

# Light novel scraper - runs daily at 3 AM (optional)
0 3 * * * cd /mnt/manga-storage/manga-server && xvfb-run python3 scripts/lightnovel_scraper.py --config config/novels.yaml -o library/LightNovels >> logs/lightnovel.log 2>&1
```

> **Note:** Light novel scrapers require `xvfb-run` on headless systems (Raspberry Pi) since they need a virtual display for the non-headless browser mode.

### Supported Sites

| Site | Flag | Notes |
|------|------|-------|
| Asura Scans | `--site asura` | Uses undetected-chromedriver for anti-bot bypass |
| Flame Comics | `--site flame` | Stable |
| Drake Comics | `--site drake` | Requires non-headless mode (Cloudflare), opens visible browser |
| ManhuaTo | `--site manhuato` | Large library, stable |
| Webtoon | `--site webtoon` | Official source, free chapters only |
| Webtoon Canvas | `--site webtoon --canvas` | User-created content |

### Limiting Results (Testing)

Use `--limit N` to cap the number of series processed. Useful for testing on slow hardware like Raspberry Pi:

```bash
# Test with just 3 series
python3 scripts/manhwa_scraper.py --site asura --list-all --limit 3 -o test.yaml

# Download only the first 5 matching series
python3 scripts/manhwa_scraper.py --site asura --download-all --filter "action" --limit 5 -o library/Manhwa

# Light novels too
python3 scripts/lightnovel_scraper.py --site lightnovelpub --list-all --limit 3 -o test_novels.yaml
```

### Step 12.10: Light Novel Support

ORVault currently focuses on CBZ manga files. For light novels, you can still use Kavita alongside ORVault if desired (they can share the same library folder). The scraper package includes a dedicated light novel scraper that outputs EPUB files.

#### Install Additional Dependency

```bash
pip3 install ebooklib --break-system-packages
```

#### Light Novel Scraper Usage

```bash
cd /mnt/manga-storage/manga-server

# List all novels from a site
python3 scripts/lightnovel_scraper.py --site lightnovelpub --list-all -o novels.yaml

# List with full details (chapters, rating, author)
python3 scripts/lightnovel_scraper.py --site lightnovelpub --list-all --with-details -o novels.yaml

# Download completed fantasy novels with 100+ chapters
python3 scripts/lightnovel_scraper.py --site lightnovelpub --download-all \
  --filter "fantasy" --status completed --min-chapters 100 \
  -o library/LightNovels

# Download highly-rated novels (4.0+)
python3 scripts/lightnovel_scraper.py --site lightnovelpub --download-all \
  --min-rating 4.0 -o library/LightNovels

# Download from all supported sites
python3 scripts/lightnovel_scraper.py --site all --download-all \
  --min-rating 4.5 --status completed \
  -o library/LightNovels

# Download from a curated YAML list
python3 scripts/lightnovel_scraper.py --config my_novels.yaml -o library/LightNovels
```

#### Supported Light Novel Sites

| Site | Flag | Notes |
|------|------|-------|
| LightNovelPub | `--site lightnovelpub` | Large library, requires non-headless mode (opens visible browser) |
| NovelBin | `--site novelbin` | Many translations, requires non-headless mode (Cloudflare) |

> **Note:** Both light novel sites require a visible browser window (non-headless) due to anti-bot protections. The scrapers handle this automatically - they override headless mode when needed. On a headless Raspberry Pi, you'll need `xvfb` installed (the install script handles this): `xvfb-run python3 scripts/lightnovel_scraper.py ...`

#### Output Format

The scraper creates EPUB files with full metadata:
- Title, author
- Cover image
- Genres
- Rating (calibre:rating metadata)
- Description

Each novel becomes an EPUB file inside a series folder, with `Vol. X` in the filename:
```
library/LightNovels/
├── Solo Leveling/
│   └── Solo Leveling Vol. 1.epub
├── The Beginning After The End/
│   └── The Beginning After The End Vol. 1.epub
├── Omniscient Reader's Viewpoint/
│   └── Omniscient Reader's Viewpoint Vol. 1.epub
└── ...
```

---

## Part 13: Multi-User Setup

### Add Users in ORVault

ORVault uses an invite code system for registration:

1. Log in as admin
2. Go to **Admin** → **User Management** (or `/admin/users`)
3. Click **Generate Invite Code**
4. Share the invite code with the person you want to add
5. They go to the **Register** page (`/register`), enter the invite code, and create their username and password

Each user gets their own:
- Reading progress (per-chapter, auto-saved)
- Series list with status tracking (Reading, Plan to Read, Completed, etc.)
- Follow list with new chapter notifications
- Reader preferences (layout, fit, direction, theme)
- Theme and display settings (synced across devices)

### User Roles

| Role | Access |
|------|--------|
| **admin** | Full access: library scanning, auto-scan config, user management, invite codes |
| **user** | Reading, progress tracking, personal list management, settings |

> **Note:** Login is case-insensitive — "Ryan", "ryan", and "RYAN" all match the same account.

---

## Part 14: Maintenance & Troubleshooting

### Daily Operations

Your server is automated:
- ORVault auto-scans the library at your configured interval (Admin → Auto Scan Interval)
- Custom scraper runs every 6 hours (if configured via cron or Docker manhwa-downloader), routed through VPN
- New chapters appear automatically in "New from Followed" and "Recently Updated"
- VPN keeps scraper traffic anonymous — your real IP is never exposed to target sites

### Useful Commands

```bash
# SSH into Pi
ssh pi@10.14.7.100

# Go to project
cd /mnt/manga-storage/manga-server

# View running containers
docker compose ps

# View logs
docker compose logs -f
docker compose logs -f orvault
docker compose logs -f vpn

# Restart everything
docker compose restart

# Restart just ORVault
docker compose restart orvault

# Rebuild ORVault after code changes
docker compose build orvault && docker compose up -d orvault

# Update containers (pulls latest images)
docker compose pull
docker compose up -d

# Check VPN status and IP
docker exec vpn wget -qO- https://ipinfo.io/ip

# Check disk space
df -h

# Check resources
htop
```

### Backup

```bash
# Backup ORVault database and configs
cd /mnt/manga-storage
tar -czf backup-$(date +%Y%m%d).tar.gz \
  manga-server/mangashelf/data/ \
  manga-server/mangashelf/public/covers/ \
  manga-server/config/

# Copy to your computer (run on your computer)
scp pi@10.14.7.100:/mnt/manga-storage/backup-*.tar.gz ~/Downloads/
```

> **Important:** The ORVault database (`mangashelf/data/mangashelf.db`) contains all user accounts, reading progress, preferences, and library metadata. Always back it up!

### Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't connect to Pi | Check power LED, network cable, try `ping manga-server.local` |
| Containers won't start | `docker compose logs`, check disk space with `df -h` |
| ORVault shows blank page | `docker compose logs orvault`, check NEXTAUTH_URL matches your access URL |
| Login doesn't work | Login is case-insensitive; check `docker compose logs orvault` for auth errors |
| Library scan finds 0 series | Check LIBRARY_PATH env var, verify CBZ files exist in library folders |
| Auto-scan interval resets | This was fixed — interval is now read from DB. Rebuild: `docker compose build orvault` |
| Reader doesn't save progress | Check browser console for errors; progress saves on 2s debounce and on page close |
| Downloads fail | Try different source, check FlareSolverr is running via `docker compose logs flaresolverr` |
| VPN won't connect | Check `docker compose logs vpn`; verify credentials match your provider. See [Gluetun wiki](https://github.com/qdm12/gluetun-wiki) |
| VPN connected but scraper hangs | Some VPN servers block scraping ports. Try a different `SERVER_COUNTRIES` value |
| Scraper uses real IP despite VPN | Verify with `docker exec vpn wget -qO- https://ipinfo.io/ip`. Ensure manhwa-downloader has `network_mode: "service:vpn"` |
| `/dev/net/tun` error on VPN start | Run `sudo modprobe tun` on the Pi host, or add `tun` to `/etc/modules` for persistence |
| FlareSolverr unreachable | With VPN routing, the downloader reaches FlareSolverr at `localhost:8191` (not `flaresolverr:8191`). Check `FLARESOLVERR_URL` env var |
| Remote access broken | `docker compose logs cloudflared`, check Cloudflare dashboard |
| Pi is slow | Check temp: `vcgencmd measure_temp`, memory: `free -h` |
| Scraper Cloudflare error | Drake/Asura need non-headless mode; on Pi use `xvfb-run` |
| Light novel EPUB empty | Both sites need non-headless mode; use `xvfb-run python3 ...` |
| Chrome version mismatch | Run `chromium-browser --version` and check chromedriver matches |
| Missing Python packages | Run `bash scripts/install_dependencies.sh` to reinstall |
| ORVault build fails on Pi | Ensure 8GB RAM or add swap: `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile` |

### Free Up Space

```bash
docker system prune -a
du -sh /mnt/manga-storage/manga-server/library/*
```

---

## Quick Reference

### URLs (Local)

| Service | URL |
|---------|-----|
| ORVault (Reader) | http://10.14.7.100:3001 |
| Kaizoku (Downloads, optional) | http://10.14.7.100:3000 |

### URLs (Remote)

| Service | URL |
|---------|-----|
| ORVault | https://manga.dirtyhousereading.com |

### File Locations

```
/mnt/manga-storage/manga-server/
├── mangashelf/                        # ORVault source code
│   ├── src/                           # Next.js app source
│   ├── prisma/                        # Database schema
│   ├── data/                          # SQLite database (mangashelf.db)
│   ├── public/covers/                 # Extracted cover images
│   ├── Dockerfile                     # Docker build for ORVault
│   ├── package.json
│   └── .env                           # Environment variables
├── config/
│   ├── sources.yaml                   # Custom scraper config
│   ├── kavita/ (optional)
│   ├── komf/ (optional)
│   │   └── application.yml
│   └── kaizoku/ (optional)
│       ├── db/
│       ├── logs/
│       └── redis/
├── library/
│   ├── Manga/
│   ├── Manhwa/
│   ├── Manhua/
│   └── LightNovels/
├── scripts/
│   ├── manhwa_scraper.py              # Manhwa/manhua CBZ scraper (5 sites)
│   ├── lightnovel_scraper.py          # Light novel EPUB scraper (2 sites)
│   ├── manhwa_downloader.py           # Config-based batch downloader
│   └── install_dependencies.sh        # Dependency installer for Pi
├── logs/
├── requirements.txt
├── docker-compose-custom-sources.yml  # Main Docker compose file
└── Dockerfile.downloader              # Docker build for scraper service
```

### Scraper Quick Commands

```bash
# List all series from a site
python3 scripts/manhwa_scraper.py --site asura --list-all -o series.yaml

# List with chapter counts, status, and rating
python3 scripts/manhwa_scraper.py --site asura --list-all --with-chapters -o series.yaml

# Filter: action OR fantasy (matches either)
python3 scripts/manhwa_scraper.py --site asura --list-all --filter "action,fantasy" -o filtered.yaml

# Filter: action AND fantasy (must match both)
python3 scripts/manhwa_scraper.py --site asura --list-all --filter-all "action,fantasy" -o both.yaml

# Only series with 50+ chapters
python3 scripts/manhwa_scraper.py --site asura --list-all --min-chapters 50 -o popular.yaml

# Only completed series
python3 scripts/manhwa_scraper.py --site asura --list-all --status completed -o completed.yaml

# Only highly-rated series (4.0+)
python3 scripts/manhwa_scraper.py --site asura --list-all --min-rating 4.0 -o best.yaml

# The ultimate filter: Completed fantasy with 100+ chapters and 4.5+ rating
python3 scripts/manhwa_scraper.py --site asura --download-all --filter-all "fantasy" --status completed --min-chapters 100 --min-rating 4.5 -o library/

# SCRAPE ALL SITES AT ONCE
python3 scripts/manhwa_scraper.py --site all --list-all -o all_series.yaml
python3 scripts/manhwa_scraper.py --site all --download-all --status completed --min-rating 4.0 -o library/

# Compare sources (single series)
python3 scripts/manhwa_scraper.py --site asura --filter "solo leveling" --source-prefix -o library/
python3 scripts/manhwa_scraper.py --site webtoon --filter "solo leveling" --source-prefix -o library/
```

### Light Novel Quick Commands

```bash
# List all novels from a site
python3 scripts/lightnovel_scraper.py --site lightnovelpub --list-all -o novels.yaml

# List with full details
python3 scripts/lightnovel_scraper.py --site lightnovelpub --list-all --with-details -o novels.yaml

# Download completed fantasy novels with 100+ chapters
python3 scripts/lightnovel_scraper.py --site lightnovelpub --download-all \
  --filter "fantasy" --status completed --min-chapters 100 -o library/LightNovels

# Download highly-rated novels
python3 scripts/lightnovel_scraper.py --site all --download-all --min-rating 4.5 -o library/LightNovels
```

---

## You're Done!

You now have:
- Raspberry Pi manga server with Docker
- **ORVault** custom reading front-end with progress tracking, multi-user support, and a full-featured reader
- Automatic library scanning with configurable intervals
- Automatic downloads (custom scrapers via cron or Docker manhwa-downloader service)
- 5 manhwa/manhua sources (Asura, Flame, Drake, ManhuaTo, Webtoon) with CBZ output
- 2 light novel sources (LightNovelPub, NovelBin) with EPUB output
- Full metadata in every file (ComicInfo.xml for CBZ) — ORVault displays titles, authors, genres, ratings, covers, and descriptions
- Advanced filtering (genre, status, rating, chapter count)
- Remote access from anywhere (Cloudflare Tunnel)
- Multi-user support with invite codes and per-user reading progress
- iPhone/Android app-like experience via PWA
- Customizable themes, reader settings synced across devices
- One-command dependency setup (`bash scripts/install_dependencies.sh`)

Enjoy your reading!
