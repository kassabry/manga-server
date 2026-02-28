# Quick Reference Card

## URLs (replace localhost with your server IP)

| Service | URL | Purpose |
|---------|-----|---------|
| Kavita | http://localhost:5000 | Read manga |
| Kaizoku | http://localhost:3000 | Download manager |
| Komf | http://localhost:8085 | Metadata (API only) |

## Common Commands

```bash
# Start everything
docker compose up -d

# Stop everything  
docker compose down

# View logs
docker compose logs -f
docker compose logs -f kavita    # Just Kavita

# Update containers
docker compose pull
docker compose up -d

# Restart a service
docker compose restart kavita
docker compose restart komf

# Check status
docker compose ps

# Enter a container
docker exec -it kavita /bin/bash
docker exec -it kaizoku /bin/sh
```

## File Locations

```
manga-server/
├── config/
│   ├── kavita/      # Kavita database & settings
│   ├── komf/        # Metadata config
│   └── kaizoku/     # Download manager data
└── library/
    ├── Manga/       # Japanese manga
    ├── Manhwa/      # Korean comics
    └── Manhua/      # Chinese comics
```

## Kavita Library Paths (inside container)

When adding libraries in Kavita, use these paths:
- `/library/Manga`
- `/library/Manhwa`
- `/library/Manhua`

## Kaizoku Download Paths

Set download location to: `/data/Manga` (or Manhwa/Manhua)

## iPhone Setup

1. Open Safari → your Kavita URL
2. Tap Share (box with arrow)
3. Tap "Add to Home Screen"
4. Done! Works like an app

## Backup

```bash
# Backup configs (small, important)
tar -czf backup-$(date +%Y%m%d).tar.gz config/

# Library is just files - backup separately if needed
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't connect | Check `docker compose ps`, ensure ports aren't blocked |
| No covers | Restart komf after adding API key |
| Downloads fail | Check kaizoku logs, try different source |
| iPhone won't load | Need HTTPS - set up Cloudflare Tunnel |

## Getting Help

- Kavita Discord: https://discord.gg/kavita
- Kaizoku GitHub: https://github.com/oae/kaizoku
- Komf GitHub: https://github.com/Snd-R/komf
