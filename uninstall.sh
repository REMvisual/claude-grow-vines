#!/usr/bin/env bash
set -euo pipefail

# claude-grow-vines uninstaller

SKILL_DIR="$HOME/.claude/skills/grow-vines"

GREEN='\033[0;32m'
NC='\033[0m'
info() { printf "${GREEN}[+]${NC} %s\n" "$1"; }

if [ -d "$SKILL_DIR" ]; then
    rm -rf "$SKILL_DIR"
    info "Removed $SKILL_DIR"
else
    info "$SKILL_DIR not found (already removed?)"
fi

info "Uninstall complete. grow-vines is no longer available."
