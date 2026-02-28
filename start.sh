#!/bin/bash

# ===========================================
# Manga Server Setup Script
# ===========================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║          Manga Server - Full Setup Script                 ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed${NC}"
    echo "   Install Docker: curl -fsSL https://get.docker.com | sh"
    exit 1
fi
echo -e "${GREEN}✓ Docker found${NC}"

# Check Docker Compose
if ! docker compose version &> /dev/null 2>&1; then
    echo -e "${RED}❌ Docker Compose not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose found${NC}"
echo ""

# Create directories
echo "Creating directory structure..."
mkdir -p config/{kavita,komf,kaizoku/{logs,db,redis}}
mkdir -p library/{Manga,Manhwa,Manhua}
echo -e "${GREEN}✓ Directories created${NC}"
echo ""

# Start services
echo "Starting services (this may take a few minutes on first run)..."
docker compose up -d

echo ""
echo "Waiting for services to initialize..."
sleep 15

# Check service health
echo ""
echo "Checking service status..."
echo ""

check_service() {
    local name=$1
    local port=$2
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port" | grep -q "200\|302\|304"; then
        echo -e "  ${GREEN}✓ $name is running on port $port${NC}"
        return 0
    else
        echo -e "  ${YELLOW}⏳ $name is starting... (port $port)${NC}"
        return 1
    fi
}

check_service "Kavita" 5000 || true
check_service "Kaizoku" 3000 || true

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                    SETUP COMPLETE!                        ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "║                                                           ║"
echo "║  Access Points:                                           ║"
echo "║  • Kavita (Reader):     http://localhost:5000             ║"
echo "║  • Kaizoku (Downloads): http://localhost:3000             ║"
echo "║                                                           ║"
echo "║  Next Steps:                                              ║"
echo "║  1. Open Kavita → Create admin account                    ║"
echo "║  2. Add libraries: /library/Manga, /library/Manhwa, etc   ║"
echo "║  3. Copy API key from Settings → General                  ║"
echo "║  4. Edit config/komf/application.yml with API key         ║"
echo "║  5. Run: docker compose restart komf                      ║"
echo "║  6. Open Kaizoku → Search & add manga to download         ║"
echo "║                                                           ║"
echo "║  For iPhone access, set up Cloudflare Tunnel:             ║"
echo "║  • See SETUP.md for detailed instructions                 ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Show running containers
echo "Running containers:"
docker compose ps
