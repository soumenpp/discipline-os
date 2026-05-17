#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Discipline OS — Setup Script
# Run this ONCE after cloning from GitHub to get the server up
# ─────────────────────────────────────────────────────────────

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✅]${NC} $1"; }
warn()  { echo -e "${YELLOW}[⚠️]${NC} $1"; }
err()   { echo -e "${RED}[❌]${NC} $1"; exit 1; }
step()  { echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; }

# ── Ensure running as root ──────────────────────────────────
if [[ $EUID -ne 0 ]]; then err "Please run as root (sudo)."; fi

# ── 1. Detect project root ─────────────────────────────────
# Works both when run directly and when piped via curl
if [[ -n "${BASH_SOURCE:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    # Piped mode — clone the repo
    REPO_URL="https://github.com/soumenpp/discipline-os.git"
    TARGET_DIR="/root/discipline-os"
    info "Fresh install — cloning from $REPO_URL"
    git clone --depth=1 "$REPO_URL" "$TARGET_DIR" 2>/dev/null || {
        warn "$TARGET_DIR already exists — using it"
    }
    PROJECT_DIR="$TARGET_DIR"
fi
cd "$PROJECT_DIR"
info "Project: $PROJECT_DIR"

# ── 2. Install system dependencies ──────────────────────────
step "System Dependencies"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl git
info "System packages installed"

# ── 3. Create virtual environment ──────────────────────────
step "Python Virtual Environment"
if [[ -d venv ]]; then
    warn "venv/ already exists — skipping"
else
    python3 -m venv venv
    info "Created virtual environment"
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
info "Python dependencies installed"

# ── 4. Create .env from template (won't overwrite) ─────────
step "Environment Configuration"
if [[ -f .env ]]; then
    warn ".env already exists — keeping your existing config"
else
    cat > .env << 'ENVEOF'
# ── Discipline OS — Environment Variables ──
# Fill in your values below, then remove the placeholder errors.

SECRET_KEY=change-me-to-a-random-64-hex-string
DB_PATH=./discipline.db
PORT=5321
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
TG_TOKEN=your-telegram-bot-token-here
ENVEOF
    info "Created .env — EDIT IT with your actual tokens!"
    info "  nano .env"
fi

# ── 5. Create systemd service ───────────────────────────────
step "Systemd Service"
SERVICE_FILE="/etc/systemd/system/discipline-os.service"

if [[ -f "$SERVICE_FILE" ]]; then
    warn "Service already exists at $SERVICE_FILE — skipping"
else
    cat > "$SERVICE_FILE" << SERVEOF
[Unit]
Description=Discipline OS v3
After=network.target

[Service]
User=root
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/venv/bin/python main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVEOF
    systemctl daemon-reload
    info "Created systemd service at $SERVICE_FILE"
fi

# ── 6. Start the service ────────────────────────────────────
step "Start Discipline OS"
systemctl enable discipline-os.service
systemctl restart discipline-os.service
sleep 2

if systemctl is-active --quiet discipline-os.service; then
    info "Discipline OS is RUNNING! 🎉"
    systemctl status discipline-os.service --no-pager | head -5
else
    err "Service failed to start — check: journalctl -u discipline-os -n 20"
fi

# ── 7. Done ─────────────────────────────────────────────────
step "Done"
echo ""
PUBLIC_IP=$(curl -4 -s ifconfig.me 2>/dev/null || echo "<YOUR_VPS_IP>")
echo -e "  ${BOLD}Dashboard:${NC}     http://$PUBLIC_IP:${PORT:-5321}"
echo -e "  ${BOLD}Check status:${NC}  systemctl status discipline-os"
echo -e "  ${BOLD}View logs:${NC}     journalctl -u discipline-os -f"
echo ""
echo -e "${GREEN}Enjoy! 🧠${NC}"
