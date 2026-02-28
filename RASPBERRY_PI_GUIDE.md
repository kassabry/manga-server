# Raspberry Pi Manga Server - Complete Setup Guide

A step-by-step guide to building a manga server on a Raspberry Pi 5 with a 1TB external drive.

---

## Part 1: Hardware Shopping List

### Required Items

| Item | Recommended | Price | Where to Buy |
|------|-------------|-------|--------------|
| Raspberry Pi 5 (8GB) | 8GB model | ~$80 | [RPi Official](https://www.raspberrypi.com/products/raspberry-pi-5/), Amazon, Adafruit, Microcenter |
| USB-C Power Supply | Official 27W PSU | ~$12 | Same as above |
| MicroSD Card | Samsung EVO 32GB+ | ~$10 | Amazon |
| Case with Cooling | Official Active Cooler case | ~$15-25 | Amazon, Adafruit |
| 1TB External HDD/SSD | Any USB 3.0 drive | ~$50-80 | Amazon, Best Buy |
| Ethernet Cable (optional) | Cat6 | ~$5 | Amazon |

**Total: ~$170-210**

### My Specific Recommendations

- **Pi:** Raspberry Pi 5 8GB (the 4GB works but 8GB is better for Docker)
- **Power:** Official Raspberry Pi 27W USB-C Power Supply (don't cheap out here)
- **Storage:** Samsung T7 1TB SSD (~$80) or WD Elements 1TB HDD (~$50)
- **Case:** Argon NEO 5 or Official Active Cooler Case
- **SD Card:** Samsung EVO Select 64GB (~$10)

---

## Part 2: Flash the Operating System

### Step 2.1: Download Raspberry Pi Imager

On your computer (Mac/Windows/Linux):

1. Go to: https://www.raspberrypi.com/software/
2. Download "Raspberry Pi Imager" for your OS
3. Install and open it

### Step 2.2: Flash the SD Card

1. Insert your MicroSD card into your computer

2. In Raspberry Pi Imager:
   - **Choose Device:** Raspberry Pi 5
   - **Choose OS:** Raspberry Pi OS (64-bit) - under "Raspberry Pi OS (other)" select **Raspberry Pi OS Lite (64-bit)**
     - We use "Lite" because we don't need a desktop GUI
   - **Choose Storage:** Select your SD card

3. Click the **gear icon** (⚙️) or "Edit Settings" to configure:

   **General tab:**
   ```
   ☑ Set hostname: manga-server
   ☑ Set username and password:
     Username: pi
     Password: [choose a strong password]
   ☑ Configure wireless LAN (if using WiFi):
     SSID: [your WiFi name]
     Password: [your WiFi password]
     Country: US (or your country)
   ☑ Set locale settings:
     Time zone: America/Chicago (or your timezone)
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
2. Connect the external drive to a blue USB 3.0 port
3. Connect Ethernet cable (recommended) or use WiFi
4. Connect power - it will boot automatically

5. Wait 2-3 minutes for first boot to complete

---

## Part 3: Connect to Your Pi

### Step 3.1: Find Your Pi's IP Address

**Option A: Check your router**
- Log into your router's admin page (usually 192.168.1.1)
- Look for a device named "manga-server"

**Option B: Use terminal/command prompt**

On Mac/Linux:
```bash
ping manga-server.local
```

On Windows (PowerShell):
```powershell
ping manga-server.local
```

Note the IP address (something like 192.168.1.XXX)

### Step 3.2: SSH Into Your Pi

**On Mac/Linux (Terminal):**
```bash
ssh pi@manga-server.local
```
Or:
```bash
ssh pi@192.168.1.XXX
```

**On Windows:**
- Use PowerShell: `ssh pi@manga-server.local`
- Or download [PuTTY](https://www.putty.org/)

When prompted:
- Type `yes` to accept the fingerprint
- Enter the password you set earlier

You should see:
```
pi@manga-server:~ $
```

🎉 **You're now connected to your Pi!**

---

## Part 4: Initial System Setup

Run these commands one at a time:

### Step 4.1: Update the System

```bash
sudo apt update && sudo apt upgrade -y
```
This takes 5-10 minutes. Say "yes" to any prompts.

### Step 4.2: Install Essential Tools

```bash
sudo apt install -y vim htop curl wget git
```

### Step 4.3: Set a Static IP (Recommended)

This ensures your Pi always has the same IP address.

```bash
sudo nmtui
```

1. Select "Edit a connection"
2. Select your connection (Wired or WiFi)
3. Navigate to "IPv4 CONFIGURATION" → change "Automatic" to "Manual"
4. Add addresses:
   - Address: `192.168.1.100/24` (or another unused IP on your network)
   - Gateway: `192.168.1.1` (your router's IP)
   - DNS: `8.8.8.8, 8.8.4.4`
5. OK → Back → Quit

Reboot to apply:
```bash
sudo reboot
```

Wait a minute, then reconnect:
```bash
ssh pi@192.168.1.100
```

---

## Part 5: Mount the External Drive

### Step 5.1: Identify the Drive

```bash
lsblk
```

You should see something like:
```
NAME        MAJ:MIN RM   SIZE RO TYPE MOUNTPOINTS
sda           8:0    0 931.5G  0 disk 
└─sda1        8:1    0 931.5G  0 part 
mmcblk0     179:0    0  59.5G  0 disk 
├─mmcblk0p1 179:1    0   512M  0 part /boot/firmware
└─mmcblk0p2 179:2    0    59G  0 part /
```

Your external drive is likely `sda` (or `sda1` for the partition).

### Step 5.2: Format the Drive (if needed)

⚠️ **WARNING: This erases everything on the drive!**

Skip this if your drive is already formatted as ext4 or exFAT.

```bash
# Create a new partition table and partition
sudo parted /dev/sda --script mklabel gpt
sudo parted /dev/sda --script mkpart primary ext4 0% 100%

# Format as ext4 (best for Linux)
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

Output looks like:
```
/dev/sda1: LABEL="manga-storage" UUID="abc12345-6789-..." TYPE="ext4"
```

Copy the UUID value (the part in quotes after UUID=).

### Step 5.5: Configure Automatic Mounting

```bash
sudo nano /etc/fstab
```

Add this line at the bottom (replace YOUR-UUID with your actual UUID):
```
UUID=YOUR-UUID-HERE /mnt/manga-storage ext4 defaults,nofail 0 2
```

Save: `Ctrl+O`, `Enter`, `Ctrl+X`

### Step 5.6: Mount and Verify

```bash
sudo mount -a
df -h | grep manga
```

You should see:
```
/dev/sda1       916G   28K  870G   1% /mnt/manga-storage
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

### Step 6.2: Add Your User to Docker Group

```bash
sudo usermod -aG docker pi
```

### Step 6.3: Log Out and Back In

```bash
exit
```

Then reconnect:
```bash
ssh pi@192.168.1.100
```

### Step 6.4: Verify Docker Works

```bash
docker --version
docker run hello-world
```

You should see a "Hello from Docker!" message.

### Step 6.5: Install Docker Compose

```bash
sudo apt install -y docker-compose-plugin
docker compose version
```

---

## Part 7: Set Up the Manga Server

### Step 7.1: Create Project Directory

```bash
mkdir -p /mnt/manga-storage/manga-server
cd /mnt/manga-storage/manga-server
```

### Step 7.2: Create Directory Structure

```bash
mkdir -p config/{kavita,komf,kaizoku/{logs,db,redis}}
mkdir -p library/{Manga,Manhwa,Manhua}
```

### Step 7.3: Create Docker Compose File

```bash
nano docker-compose.yml
```

Paste this entire content:

```yaml
version: '3.9'

services:
  # Kavita - Reading Server
  kavita:
    image: jvmilazz0/kavita:latest
    container_name: kavita
    volumes:
      - ./config/kavita:/kavita/config
      - ./library:/library
    environment:
      - TZ=America/Chicago
    ports:
      - "5000:5000"
    restart: unless-stopped
    networks:
      - manga-network

  # Komf - Metadata Fetcher
  komf:
    image: sndxr/komf:latest
    container_name: komf
    volumes:
      - ./config/komf:/config
    environment:
      - TZ=America/Chicago
    depends_on:
      - kavita
    restart: unless-stopped
    networks:
      - manga-network

  # Kaizoku - Download Manager
  kaizoku:
    image: ghcr.io/oae/kaizoku:latest
    container_name: kaizoku
    environment:
      - DATABASE_URL=postgresql://kaizoku:kaizoku@kaizoku-db:5432/kaizoku
      - KAIZOKU_PORT=3000
      - REDIS_HOST=kaizoku-redis
      - REDIS_PORT=6379
      - PUID=1000
      - PGID=1000
      - TZ=America/Chicago
    volumes:
      - ./library:/data
      - ./config/kaizoku:/config
      - ./config/kaizoku/logs:/logs
    depends_on:
      - kaizoku-db
      - kaizoku-redis
    ports:
      - "3000:3000"
    restart: unless-stopped
    networks:
      - manga-network

  kaizoku-db:
    image: postgres:15-alpine
    container_name: kaizoku-db
    environment:
      - POSTGRES_USER=kaizoku
      - POSTGRES_PASSWORD=kaizoku
      - POSTGRES_DB=kaizoku
    volumes:
      - ./config/kaizoku/db:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - manga-network

  kaizoku-redis:
    image: redis:7-alpine
    container_name: kaizoku-redis
    volumes:
      - ./config/kaizoku/redis:/data
    restart: unless-stopped
    networks:
      - manga-network

  # FlareSolverr - Cloudflare Bypass
  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    container_name: flaresolverr
    environment:
      - LOG_LEVEL=info
      - TZ=America/Chicago
    ports:
      - "8191:8191"
    restart: unless-stopped
    networks:
      - manga-network

networks:
  manga-network:
    driver: bridge
```

Save: `Ctrl+O`, `Enter`, `Ctrl+X`

### Step 7.4: Create Komf Configuration

```bash
nano config/komf/application.yml
```

Paste:

```yaml
kavita:
  baseUri: "http://kavita:5000"
  apiKey: "YOUR_API_KEY_HERE"

metadataProviders:
  defaultProviders:
    mangaUpdates:
      priority: 10
      enabled: true
    aniList:
      priority: 20
      enabled: true
    mal:
      priority: 30
      enabled: true
    mangaDex:
      priority: 40
      enabled: true
      coverLanguages:
        - "en"
        - "ja"
        - "ko"
        - "zh"

kavita:
  eventListener:
    enabled: true
    libraries: []
    
  metadataUpdate:
    default:
      title: true
      summary: true
      readingDirection: true
      ageRating: true
      genres: true
      tags: true
      covers:
        updateCovers: true
        ifNoCovers: true

server:
  port: 8085

logLevel: INFO
```

Save: `Ctrl+O`, `Enter`, `Ctrl+X`

### Step 7.5: Start the Services

```bash
docker compose up -d
```

First run downloads images (~10-15 minutes on Pi).

Watch the progress:
```bash
docker compose logs -f
```

Press `Ctrl+C` to stop watching logs.

### Step 7.6: Check Everything is Running

```bash
docker compose ps
```

All services should show "Up":
```
NAME              STATUS
kavita            Up
komf              Up
kaizoku           Up
kaizoku-db        Up
kaizoku-redis     Up
flaresolverr      Up
```

---

## Part 8: Configure Kavita

### Step 8.1: Access Kavita

On your computer, open a browser and go to:
```
http://192.168.1.100:5000
```

(Replace with your Pi's actual IP)

### Step 8.2: Create Admin Account

1. Create your admin username and password
2. Click "Submit"

### Step 8.3: Add Libraries

1. Click the **gear icon** (⚙️) → **Libraries**
2. Click **Add Library**

Add these three libraries:

**Library 1:**
- Name: `Manga`
- Type: `Manga`
- Folders: Click "Add Folder" → type `/library/Manga` → click checkmark

**Library 2:**
- Name: `Manhwa`
- Type: `Manga`
- Folders: `/library/Manhwa`

**Library 3:**
- Name: `Manhua`
- Type: `Manga`
- Folders: `/library/Manhua`

### Step 8.4: Get API Key for Komf

1. Go to **Settings** (gear icon) → **General**
2. Find "API Key" and click the **eye icon** to reveal it
3. **Copy this key**

### Step 8.5: Update Komf Configuration

Back in your SSH terminal:

```bash
cd /mnt/manga-storage/manga-server
nano config/komf/application.yml
```

Replace `YOUR_API_KEY_HERE` with your actual API key.

Save and restart Komf:
```bash
docker compose restart komf
```

---

## Part 9: Configure Kaizoku (Downloads)

### Step 9.1: Access Kaizoku

Open in browser:
```
http://192.168.1.100:3000
```

### Step 9.2: Initial Setup

1. On first access, Kaizoku will initialize
2. Wait for it to complete

### Step 9.3: Add Your First Manga

1. Click **"Add Series"** or the **+** button
2. Search for a manga (e.g., "One Punch Man")
3. Select a source (MangaDex is most reliable)
4. Click to add it
5. Kaizoku will start downloading chapters

### Step 9.4: Configure Auto-Downloads

1. Go to **Settings** (or the series settings)
2. Set check interval (e.g., every 6 hours)
3. New chapters will download automatically

---

## Part 10: Set Up iPhone Access (Cloudflare Tunnel)

This lets you access your manga from anywhere without opening router ports.

### Step 10.1: Create Cloudflare Account

1. Go to https://dash.cloudflare.com/sign-up
2. Create a free account

### Step 10.2: Add a Domain (or get a free one)

**Option A: Use your own domain**
- Add it to Cloudflare and update nameservers

**Option B: Use Cloudflare's free tunnel subdomain**
- You'll get a random URL like `https://random-words.trycloudflare.com`

### Step 10.3: Create a Tunnel

1. Go to https://one.dash.cloudflare.com/
2. Click **Networks** → **Tunnels**
3. Click **Create a tunnel**
4. Name it: `manga-server`
5. Click **Save tunnel**

### Step 10.4: Get Your Tunnel Token

On the next screen, you'll see installation instructions. Find the command that looks like:
```
cloudflared service install <LONG_TOKEN_HERE>
```

Copy just the token part (the long string after "install").

### Step 10.5: Add Cloudflared to Docker Compose

On your Pi:

```bash
cd /mnt/manga-storage/manga-server
nano docker-compose.yml
```

Add this service at the bottom (before `networks:`):

```yaml
  # Cloudflare Tunnel - Remote Access
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN=YOUR_TOKEN_HERE
    depends_on:
      - kavita
    restart: unless-stopped
    networks:
      - manga-network
```

Replace `YOUR_TOKEN_HERE` with your actual tunnel token.

Save and restart:
```bash
docker compose up -d
```

### Step 10.6: Configure Public Hostname

Back in Cloudflare dashboard:

1. Click **Next** after the tunnel is connected
2. Add a **Public Hostname**:
   - Subdomain: `manga` (or whatever you want)
   - Domain: Select your domain
   - Service Type: `HTTP`
   - URL: `kavita:5000`
3. Click **Save**

### Step 10.7: Test Remote Access

Open in any browser:
```
https://manga.yourdomain.com
```

You should see your Kavita login page! 🎉

---

## Part 11: Set Up iPhone

### Step 11.1: Install as PWA

1. Open **Safari** on your iPhone
2. Go to `https://manga.yourdomain.com`
3. Log in to Kavita
4. Tap the **Share** button (square with arrow)
5. Scroll down and tap **"Add to Home Screen"**
6. Name it "Manga" and tap **Add**

### Step 11.2: Configure Reading Settings

1. Open a manga and start reading
2. Tap the **gear icon** in the reader
3. Set these for manhwa/manhua:
   - **Reading Direction:** Top to Bottom
   - **Scaling Option:** Width
   - **Background Color:** Black
   - **Auto Close Menu:** On

---

## Part 12: Maintenance & Tips

### Daily Operations

Your server is now fully automated:
- Kaizoku checks for new chapters periodically
- Komf fetches metadata automatically
- Everything syncs to your iPhone

### Useful Commands

```bash
# SSH into your Pi
ssh pi@192.168.1.100

# Go to project directory
cd /mnt/manga-storage/manga-server

# View running containers
docker compose ps

# View logs (all services)
docker compose logs -f

# View specific service logs
docker compose logs -f kavita
docker compose logs -f kaizoku

# Restart everything
docker compose restart

# Update all containers
docker compose pull
docker compose up -d

# Check disk space
df -h

# Check system resources
htop
```

### Backup Your Data

```bash
# Backup configs (small, important)
cd /mnt/manga-storage
tar -czf backup-$(date +%Y%m%d).tar.gz manga-server/config/

# Copy to your computer (run on your computer, not Pi)
scp pi@192.168.1.100:/mnt/manga-storage/backup-*.tar.gz ~/Downloads/
```

### If Something Breaks

```bash
# Check what's wrong
docker compose ps
docker compose logs kavita

# Restart a specific service
docker compose restart kavita

# Nuclear option: recreate everything
docker compose down
docker compose up -d
```

### Free Up Space

```bash
# Remove old Docker images
docker system prune -a

# Check what's using space
du -sh /mnt/manga-storage/manga-server/library/*
```

---

## Part 13: Quick Reference Card

### URLs (Local Network)

| Service | URL |
|---------|-----|
| Kavita (Reader) | http://192.168.1.100:5000 |
| Kaizoku (Downloads) | http://192.168.1.100:3000 |

### URLs (Remote via Cloudflare)

| Service | URL |
|---------|-----|
| Kavita | https://manga.yourdomain.com |

### File Locations on Pi

```
/mnt/manga-storage/manga-server/
├── config/           # All configuration
├── library/
│   ├── Manga/        # Japanese manga
│   ├── Manhwa/       # Korean comics
│   └── Manhua/       # Chinese comics
└── docker-compose.yml
```

### Kavita Library Paths (inside container)

- `/library/Manga`
- `/library/Manhwa`
- `/library/Manhua`

---

## Troubleshooting

### "Can't connect to Pi"
- Check Pi is powered on (red LED)
- Check network cable/WiFi
- Try `ping manga-server.local`
- Check router for Pi's IP

### "Docker containers won't start"
- Check logs: `docker compose logs`
- Check disk space: `df -h`
- Restart Docker: `sudo systemctl restart docker`

### "Kaizoku downloads fail"
- Some sources block datacenter IPs
- Try different sources in Kaizoku
- Check FlareSolverr is running

### "iPhone can't connect remotely"
- Verify Cloudflare tunnel is running: `docker compose logs cloudflared`
- Check tunnel status in Cloudflare dashboard
- Make sure you're using HTTPS

### "Pi is slow/freezing"
- Check temperature: `vcgencmd measure_temp`
- Check memory: `free -h`
- Consider reducing services or upgrading to Pi 5 8GB

---

---

## Part 14: Adding Custom Manhwa Sources (Asura, Flame, Drake)

If you want to download from specific sites like asuracomic.net, flamecomics.xyz, or drakecomic.org:

### Option A: Use the Custom Docker Compose

Instead of the regular docker-compose.yml, use the one with custom sources:

```bash
cd /mnt/manga-storage/manga-server

# Stop current services
docker compose down

# Start with custom sources support
docker compose -f docker-compose-custom-sources.yml up -d
```

### Option B: Add Custom Lua Scrapers to Kaizoku

```bash
# Copy the pre-made scrapers
cp config/scrapers/*.lua config/kaizoku/.config/mangal/sources/

# Restart Kaizoku
docker compose restart kaizoku
```

### Option C: Use the Python Downloader Directly

```bash
# Install dependencies
pip install requests beautifulsoup4 selenium webdriver-manager pyyaml --break-system-packages
sudo apt install -y chromium-browser chromium-chromedriver

# Edit your series list
nano config/sources.yaml

# Run the downloader
python scripts/manhwa_downloader.py --config config/sources.yaml --output library/Manhwa
```

### Configure Your Series

Edit `config/sources.yaml` to add your manhwa:

```yaml
series:
  - url: "https://asuracomic.net/series/your-series-name"
    category: Manhwa
    enabled: true
    
  - url: "https://flamecomics.xyz/series/another-series/"
    category: Manhwa
    enabled: true
```

### Set Up Automatic Downloads

```bash
# Add to crontab
crontab -e

# Check for new chapters every 6 hours
0 */6 * * * cd /mnt/manga-storage/manga-server && python scripts/manhwa_downloader.py --config config/sources.yaml >> logs/downloader.log 2>&1
```

For more details, see **CUSTOM_SOURCES.md**.

---

## You're Done! 🎉

You now have:
- ✅ A Raspberry Pi manga server
- ✅ Automatic manga downloads
- ✅ Custom source support (Asura, Flame, Drake, etc.)
- ✅ Automatic metadata fetching
- ✅ iPhone access from anywhere
- ✅ A comick.dev-like reading experience

Enjoy your reading!
