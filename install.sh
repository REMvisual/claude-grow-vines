#!/usr/bin/env bash
set -euo pipefail

# claude-grow-vines installer
# Usage: curl -fsSL https://raw.githubusercontent.com/REMvisual/claude-grow-vines/main/install.sh | bash
# Pin version: curl -fsSL https://raw.githubusercontent.com/REMvisual/claude-grow-vines/v1.1.0/install.sh | bash -s -- v1.1.0

REPO="REMvisual/claude-grow-vines"
SKILL_NAME="grow-vines"
SKILL_DIR="$HOME/.claude/skills/$SKILL_NAME"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { printf "${GREEN}[+]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[!]${NC} %s\n" "$1"; }
fail() { printf "${RED}[x]${NC} %s\n" "$1"; exit 1; }

VERSION="${1:-main}"
info "Installing $SKILL_NAME ($VERSION)"

command -v curl >/dev/null 2>&1 || fail "curl is required but not installed"
command -v tar >/dev/null 2>&1 || fail "tar is required but not installed"

TMPDIR_DL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_DL"' EXIT

# the skill is ~60 files, so install from the repo tarball rather than per-file raws
info "Downloading repo tarball..."
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$VERSION" -o "$TMPDIR_DL/repo.tgz" 2>/dev/null \
  || curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/tags/$VERSION" -o "$TMPDIR_DL/repo.tgz" \
  || fail "Failed to download $REPO@$VERSION"

tar -xzf "$TMPDIR_DL/repo.tgz" -C "$TMPDIR_DL"
SRC="$(find "$TMPDIR_DL" -maxdepth 1 -type d -name 'claude-grow-vines-*' | head -1)"
[ -n "$SRC" ] || fail "Unexpected tarball layout"

mkdir -p "$HOME/.claude/skills"
rm -rf "$SKILL_DIR"
cp -r "$SRC/skills/$SKILL_NAME" "$SKILL_DIR"
info "Skill installed to $SKILL_DIR"

# one-time bark PBR fetch (ambientCG, CC0) - needs any python3
if command -v python3 >/dev/null 2>&1; then
    info "Fetching bark texture sets (ambientCG, CC0)..."
    python3 "$SKILL_DIR/scripts/fetch_assets.py" || warn "Bark fetch failed - run it later: python3 $SKILL_DIR/scripts/fetch_assets.py"
elif command -v python >/dev/null 2>&1; then
    info "Fetching bark texture sets (ambientCG, CC0)..."
    python "$SKILL_DIR/scripts/fetch_assets.py" || warn "Bark fetch failed - run it later: python $SKILL_DIR/scripts/fetch_assets.py"
else
    warn "python3 not found - run this once before first use:"
    warn "  python3 $SKILL_DIR/scripts/fetch_assets.py"
fi

echo ""
info "Installation complete!"
echo ""
echo "  Usage: ask Claude Code to \"grow vines\" on a mesh, or run headless:"
echo "    PYTHONHASHSEED=0 <blender> --background --factory-startup \\"
echo "      --python \"$SKILL_DIR/scripts/grow_vine.py\" -- <MESH> \"<BRIEF>\" <OUTDIR>"
echo ""
echo "  Optional: install the BagaIvy Blender addon for photoreal leaf cards."
echo "  Without it, a procedural leaf fallback is used automatically."
echo ""
echo "  Uninstall: curl -fsSL https://raw.githubusercontent.com/$REPO/main/uninstall.sh | bash"
echo ""
