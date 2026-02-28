# Server Hardware Buying Guide

A guide to choosing the right hardware for your manga server.

## Quick Recommendation

| Your Situation | Recommendation | Budget |
|---------------|----------------|--------|
| Just want it to work | Synology DS224+ | ~$500 |
| On a budget | Raspberry Pi 5 + USB drive | ~$150 |
| Want flexibility | Mini PC (Beelink/NUC) | ~$250 |
| Already have hardware | Use what you have! | $0 |

---

## Option 1: Synology NAS (Recommended)

### Best Model: DS224+
- **Price:** ~$300 (diskless)
- **CPU:** Intel Celeron J4125
- **RAM:** 2GB (expandable to 6GB)
- **Drive Bays:** 2
- **Power Usage:** ~15W

### Why Synology?
1. **Container Manager** - Native Docker support with GUI
2. **DSM OS** - Easy web-based management
3. **Reliability** - Designed for 24/7 operation
4. **RAID Support** - Protect against drive failure
5. **App Ecosystem** - Many pre-built packages

### Recommended Drives
- **WD Red Plus 4TB** (~$100 each) - Best for NAS
- **Seagate IronWolf 4TB** (~$95 each) - Good alternative

### Total Cost: ~$500-600
- DS224+: $300
- 2x 4TB drives: $200
- = Reliable, expandable, low-maintenance

---

## Option 2: Mini PC

### Best Budget: Beelink Mini S12 Pro
- **Price:** ~$200
- **CPU:** Intel N100 (very efficient)
- **RAM:** 16GB
- **Storage:** 500GB SSD (add external for library)
- **Power Usage:** ~10-15W

### Best Performance: Intel NUC 12/13
- **Price:** ~$400-600
- **CPU:** Intel Core i5/i7
- **RAM:** 16-32GB
- **More powerful for other services**

### Storage Options
1. **Internal NVMe** for OS + configs
2. **External USB 3.0 HDD** for library (cheapest)
3. **USB enclosure + 2.5" SSD** for speed
4. **Network mount to existing NAS**

### Pros
- More CPU power for other services (Plex, etc.)
- Run any Linux distro
- Easy to upgrade/repair

### Cons
- Need to manage OS yourself
- External drives less elegant
- No built-in redundancy

---

## Option 3: Raspberry Pi 5

### Setup
- **Raspberry Pi 5 8GB:** ~$80
- **Power Supply:** ~$15
- **SD Card (32GB):** ~$10
- **Case with cooling:** ~$15
- **USB 3.0 HDD 2TB:** ~$60

### Total: ~$180

### Pros
- Lowest cost
- Lowest power (~5W)
- Silent operation
- Great learning experience

### Cons
- Limited performance
- USB storage only
- SD card can wear out (boot from SSD recommended)

### Best For
- Small libraries (<500 series)
- Learning/experimenting
- Ultra-low power requirements

---

## Option 4: Repurposed Hardware

### Old Laptop
- Install Ubuntu Server
- Use internal drive + external for library
- Cost: Free (if you have one)

### Old Desktop
- More expandable
- Can add multiple drives
- Higher power usage

### Mac Mini (Intel or M1)
- Excellent if you have one
- M1 is very power efficient
- Docker works great (with Colima on macOS)

---

## Storage Recommendations

### Capacity Planning

| Content Type | Avg Size | Example |
|-------------|----------|---------|
| Manga volume (CBZ) | 100 MB | One Piece v1 |
| Manhwa chapter | 20 MB | Solo Leveling c1 |
| Light novel (EPUB) | 2 MB | - |

### Collection Estimates

| Collection | Volumes/Chapters | Storage |
|-----------|------------------|---------|
| Casual (50 series) | ~500 volumes | 50 GB |
| Moderate (200 series) | ~2000 volumes | 200 GB |
| Serious (500+ series) | ~5000 volumes | 500 GB |
| With manhwa | Add 50-100% | - |

### Recommendation
- **Start with 2TB** - Room to grow
- **Consider 4TB** if you read manhwa (more images)
- **RAID 1** if data loss would hurt

---

## Power Consumption & Costs

| Device | Idle Power | Annual Cost* |
|--------|-----------|--------------|
| Raspberry Pi 5 | 5W | $5 |
| Mini PC (N100) | 10W | $10 |
| Synology DS224+ | 15W | $15 |
| Old Desktop | 50-100W | $50-100 |

*Assuming $0.12/kWh, 24/7 operation

---

## My Personal Recommendation

### For Most People: Synology DS224+

**Why:**
1. Set it and forget it
2. Automatic Docker updates
3. Built-in backup solutions
4. Expandable storage
5. Great mobile apps
6. 3-year warranty
7. Active community

**Pair with:**
- 2x WD Red Plus 4TB in RAID 1 (mirrored)
- Total: ~$500

### For Tinkerers: Mini PC + External Drive

**Why:**
1. More control
2. Better for multiple services
3. Can run any Linux
4. Upgradeable

**Pair with:**
- Beelink Mini S12 Pro: $200
- 4TB External HDD: $100
- Total: ~$300

---

## Where to Buy

### NAS
- Amazon
- B&H Photo
- Newegg
- Synology authorized resellers

### Mini PCs
- Amazon (Beelink, Minisforum)
- Intel (NUCs)
- eBay (used/refurbished)

### Drives
- Amazon
- Best Buy
- Newegg
- /r/buildapcsales for deals

---

## Final Notes

1. **Don't overthink it** - Any modern hardware will work
2. **Start small** - You can always upgrade later
3. **Backup matters** - RAID is not backup, consider cloud backup for configs
4. **Power matters** - 24/7 devices add up over time
5. **Noise matters** - NAS/Pi are silent, desktops may not be
