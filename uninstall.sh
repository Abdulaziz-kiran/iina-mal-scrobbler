#!/usr/bin/env bash
#
# iina-mal-scrobbler uninstaller for macOS
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Uninstalling iina-mal-scrobbler ===${NC}\n"

INSTALL_DIR="$HOME/.local/share/mal-scrobbler"
LAUNCHER_PATH="$HOME/.local/bin/mal-scrobbler"
LUA_SCRIPT="$HOME/.config/mpv/scripts/mal_scrobbler.lua"
CONFIG_DIR="$HOME/.config/mal-scrobbler"

# 1. Remove installed core files
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo -e "${GREEN}[✓] Removed $INSTALL_DIR${NC}"
fi

# 2. Remove CLI launcher
if [ -f "$LAUNCHER_PATH" ]; then
    rm -f "$LAUNCHER_PATH"
    echo -e "${GREEN}[✓] Removed $LAUNCHER_PATH${NC}"
fi

# 3. Remove Lua script
if [ -f "$LUA_SCRIPT" ]; then
    rm -f "$LUA_SCRIPT"
    echo -e "${GREEN}[✓] Removed $LUA_SCRIPT${NC}"
fi

# 4. Remove macOS Keychain tokens
echo "Removing tokens from macOS Keychain..."
security delete-generic-password -s "com.iina-mal-scrobbler" -a "access_token" 2>/dev/null || true
security delete-generic-password -s "com.iina-mal-scrobbler" -a "refresh_token" 2>/dev/null || true
echo -e "${GREEN}[✓] Keychain tokens removed${NC}"

# 5. Check if user wants to purge configuration & history
if [ "${1:-}" = "--purge" ]; then
    rm -rf "$CONFIG_DIR"
    echo -e "${GREEN}[✓] Purged configuration and database ($CONFIG_DIR)${NC}"
else
    echo -e "${YELLOW}[NOTE] Configuration and history preserved in $CONFIG_DIR.${NC}"
    echo "To remove history as well, run: ./uninstall.sh --purge"
fi

echo -e "\n${GREEN}Uninstallation complete.${NC}"
