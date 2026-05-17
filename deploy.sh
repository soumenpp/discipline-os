#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Discipline OS — Deploy Script
# Run this to push updates to GitHub
# ─────────────────────────────────────────────────────────────

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✅]${NC} $1"; }
warn()  { echo -e "${YELLOW}[⚠️]${NC} $1"; }
err()   { echo -e "${RED}[❌]${NC} $1"; }
cmd()   { echo -e "${CYAN}$ $1${NC}"; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo -e "${BOLD}━━━ Discipline OS — Deploy to GitHub ━━━${NC}\n"

# ── Check git repo ─────────────────────────────────────────
if [[ ! -d .git ]]; then
    warn "No git repo found."
    read -rp "🔗 Enter your GitHub repo URL (e.g., git@github.com:user/discipline-os.git): " REPO_URL
    if [[ -z "$REPO_URL" ]]; then
        err "No URL provided — aborting"
    fi
    cmd "git init && git remote add origin $REPO_URL"
    git init
    git remote add origin "$REPO_URL"
    info "Git repo initialized"
fi

# ── Check remote exists ────────────────────────────────────
if ! git remote get-url origin &>/dev/null; then
    read -rp "🔗 Enter your GitHub repo URL: " REPO_URL
    git remote add origin "$REPO_URL"
fi
info "Remote origin: $(git remote get-url origin)"

# ── Ensure .gitignore exists ────────────────────────────────
if [[ ! -f .gitignore ]]; then
    err ".gitignore missing — create one first!"
fi

# ── Commit ──────────────────────────────────────────────────
echo ""
read -rp "✏️  Commit message: " COMMIT_MSG
if [[ -z "$COMMIT_MSG" ]]; then
    COMMIT_MSG="Update $(date '+%Y-%m-%d %H:%M')"
fi

cmd "git add -A"
git add -A

# Show staged files
STAGED=$(git diff --cached --stat)
if [[ -z "$STAGED" ]]; then
    warn "Nothing to commit — everything is up to date."
    exit 0
fi
echo ""
echo "$STAGED"

cmd "git commit -m \"$COMMIT_MSG\""
git commit -m "$COMMIT_MSG"

# ── Push ────────────────────────────────────────────────────
echo ""
info "Pushing to GitHub..."
cmd "git push -u origin main"
if git push -u origin main; then
    info "✅ Deployed successfully!"
else
    warn "Push failed — trying 'master' branch instead..."
    git branch -m main master 2>/dev/null || true
    cmd "git push -u origin master"
    git push -u origin master || err "Push failed — check your SSH keys and repo access"
fi

echo ""
echo -e "${GREEN}🎉 Done!${NC}"
