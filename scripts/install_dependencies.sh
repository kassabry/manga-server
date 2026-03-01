#!/usr/bin/env bash
# ============================================================================
# install_dependencies.sh - Install all dependencies for manga/light novel server
#
# Supports: Raspberry Pi (armhf/arm64), Ubuntu/Debian x86_64
# Run as: bash scripts/install_dependencies.sh
# ============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${BLUE}==>${NC} ${YELLOW}$1${NC}"; }

# Detect architecture and OS
ARCH=$(uname -m)
OS=$(uname -s)
IS_PI=false
IS_ARM=false

if [[ "$ARCH" == "aarch64" || "$ARCH" == "armv7l" || "$ARCH" == "armv6l" ]]; then
    IS_ARM=true
fi

if [[ -f /proc/device-tree/model ]] && grep -qi "raspberry" /proc/device-tree/model 2>/dev/null; then
    IS_PI=true
fi

echo "============================================"
echo "  Manga Server Dependency Installer"
echo "============================================"
echo ""
log_info "Architecture: $ARCH"
log_info "OS: $OS"
log_info "Raspberry Pi: $IS_PI"
log_info "ARM: $IS_ARM"
echo ""

# ============================================================================
# Step 1: System packages
# ============================================================================
log_step "Step 1/6: Installing system packages..."

sudo apt-get update -qq

# Core tools
sudo apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    git \
    vim \
    htop \
    unzip \
    xvfb \
    xdg-utils

log_info "System packages installed."

# ============================================================================
# Step 2: Install Chromium browser + driver
# ============================================================================
log_step "Step 2/6: Installing Chromium browser..."

# Try modern package names first (Debian Bookworm+), fall back to legacy names
if sudo apt-get install -y --no-install-recommends chromium chromium-driver 2>/dev/null; then
    CHROME_BIN=$(which chromium 2>/dev/null || echo "/usr/bin/chromium")
elif sudo apt-get install -y --no-install-recommends chromium-browser chromium-chromedriver 2>/dev/null; then
    CHROME_BIN=$(which chromium-browser 2>/dev/null || echo "/usr/bin/chromium-browser")
else
    log_warn "Could not install Chromium. You may need to install it manually."
    CHROME_BIN=""
fi

# Verify
if [ -x "$CHROME_BIN" ]; then
    CHROME_VER=$("$CHROME_BIN" --version 2>/dev/null || echo "unknown")
    log_info "Chromium installed: $CHROME_VER"
else
    log_warn "Chromium binary not found at $CHROME_BIN. You may need to install it manually."
fi

# ============================================================================
# Step 3: Python packages
# ============================================================================
log_step "Step 3/6: Installing Python packages..."

# Detect if we need --break-system-packages (Python 3.11+ on Debian/Pi OS)
PIP_FLAGS=""
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.9")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 11 ]]; then
    # Check if running in a venv already
    if [ -z "$VIRTUAL_ENV" ]; then
        PIP_FLAGS="--break-system-packages"
        log_info "Python $PY_VER detected, using --break-system-packages"
    fi
fi

# Core scraping dependencies
pip3 install $PIP_FLAGS --no-cache-dir \
    requests \
    beautifulsoup4 \
    lxml \
    pyyaml

# Selenium + undetected-chromedriver (anti-bot bypass)
pip3 install $PIP_FLAGS --no-cache-dir \
    selenium \
    webdriver-manager \
    undetected-chromedriver

# EPUB creation (light novels)
pip3 install $PIP_FLAGS --no-cache-dir \
    ebooklib

# Image handling (cover processing)
pip3 install $PIP_FLAGS --no-cache-dir \
    Pillow

# Scheduling (optional, for automated runs)
pip3 install $PIP_FLAGS --no-cache-dir \
    schedule

log_info "Python packages installed."

# ============================================================================
# Step 4: Docker (if not already installed)
# ============================================================================
log_step "Step 4/6: Checking Docker..."

if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version 2>/dev/null)
    log_info "Docker already installed: $DOCKER_VER"
else
    log_info "Installing Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    log_info "Docker installed. You may need to log out and back in for group permissions."
fi

# Docker Compose plugin
if docker compose version &>/dev/null; then
    COMPOSE_VER=$(docker compose version 2>/dev/null)
    log_info "Docker Compose already installed: $COMPOSE_VER"
else
    log_info "Installing Docker Compose plugin..."
    sudo apt-get install -y docker-compose-plugin
    log_info "Docker Compose plugin installed."
fi

# ============================================================================
# Step 5: Create directory structure
# ============================================================================
log_step "Step 5/6: Creating directory structure..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Ensure library directories exist
mkdir -p "$PROJECT_DIR/library/Manga"
mkdir -p "$PROJECT_DIR/library/Manhwa"
mkdir -p "$PROJECT_DIR/library/Manhua"
mkdir -p "$PROJECT_DIR/library/LightNovels"
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$PROJECT_DIR/config/kavita"
mkdir -p "$PROJECT_DIR/config/komf"
mkdir -p "$PROJECT_DIR/config/kaizoku/logs"
mkdir -p "$PROJECT_DIR/config/kaizoku/db"
mkdir -p "$PROJECT_DIR/config/kaizoku/redis"

log_info "Directory structure created."

# ============================================================================
# Step 6: Verify installation
# ============================================================================
log_step "Step 6/6: Verifying installation..."

echo ""
echo "============================================"
echo "  Installation Verification"
echo "============================================"

PASS=0
FAIL=0

check() {
    local name="$1"
    local cmd="$2"
    if eval "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}[PASS]${NC} $name"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} $name"
        FAIL=$((FAIL + 1))
    fi
}

check "Python 3"                "python3 --version"
check "pip3"                    "pip3 --version"
check "requests"                "python3 -c 'import requests'"
check "beautifulsoup4"          "python3 -c 'from bs4 import BeautifulSoup'"
check "lxml"                    "python3 -c 'import lxml'"
check "PyYAML"                  "python3 -c 'import yaml'"
check "selenium"                "python3 -c 'from selenium import webdriver'"
check "undetected-chromedriver" "python3 -c 'import undetected_chromedriver'"
check "webdriver-manager"       "python3 -c 'from webdriver_manager.chrome import ChromeDriverManager'"
check "ebooklib"                "python3 -c 'from ebooklib import epub'"
check "Pillow"                  "python3 -c 'from PIL import Image'"
check "Chromium"                "command -v chromium-browser || command -v chromium"
check "Docker"                  "command -v docker"
check "Docker Compose"          "docker compose version"

echo ""
echo "============================================"
echo "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo "============================================"

if [ "$FAIL" -gt 0 ]; then
    log_warn "Some checks failed. Review the output above."
    log_warn "The scrapers may still work with some packages missing."
fi

echo ""
log_info "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Start services:  cd $PROJECT_DIR && docker compose up -d"
echo "  2. Test manhwa:     python3 $PROJECT_DIR/scripts/manhwa_scraper.py --site asura --list-all --limit 3 -o test.yaml"
echo "  3. Test lightnovel: python3 $PROJECT_DIR/scripts/lightnovel_scraper.py --site lightnovelpub --list-all --limit 3 -o test.yaml"
echo ""
