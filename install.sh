#!/usr/bin/env bash
#
# iina-mal-scrobbler installer for macOS
# Idempotent, safe, and zero-dependency
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== iina-mal-scrobbler Installer ===${NC}\n"

# 1. Verify macOS
OS_NAME=$(uname -s)
if [ "$OS_NAME" != "Darwin" ]; then
    echo -e "${RED}[ERROR] This utility is designed specifically for macOS.${NC}"
    exit 1
fi
echo -e "${GREEN}[✓] Platform: macOS ($OS_NAME)${NC}"

# 2. Locate compatible Python 3.9+ binary
PYTHON_BIN=""
for candidate in "/opt/homebrew/bin/python3" "/usr/local/bin/python3" "$(command -v python3 2>/dev/null || true)" "/usr/bin/python3"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[ERROR] Python 3.9 or higher was not found on this system.${NC}"
    echo "Please install Python via Homebrew (brew install python) or Xcode Command Line Tools."
    exit 1
fi
PY_VER=$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
echo -e "${GREEN}[✓] Python: $PY_VER ($PYTHON_BIN)${NC}"

# 3. Determine repository source directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -d "$SCRIPT_DIR/core" ] || [ ! -f "$SCRIPT_DIR/scripts/mal_scrobbler.lua" ]; then
    echo -e "${RED}[ERROR] Installer files not found in $SCRIPT_DIR.${NC}"
    echo "Please clone the repository and run install.sh from the repository root."
    exit 1
fi

# 4. Target Directories
INSTALL_DIR="$HOME/.local/share/mal-scrobbler"
BIN_DIR="$HOME/.local/bin"
MPV_SCRIPTS_DIR="$HOME/.config/mpv/scripts"
CONFIG_DIR="$HOME/.config/mal-scrobbler"

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$MPV_SCRIPTS_DIR" "$CONFIG_DIR"

# 5. Copy Core Application Files
echo "Installing application files into $INSTALL_DIR..."
rm -rf "$INSTALL_DIR/core"
cp -R "$SCRIPT_DIR/core" "$INSTALL_DIR/"

# 6. Install CLI Launcher Wrapper
LAUNCHER_PATH="$BIN_DIR/mal-scrobbler"
echo "Creating CLI launcher at $LAUNCHER_PATH..."
cat << LAUNCHER_EOF > "$LAUNCHER_PATH"
#!/usr/bin/env bash
exec "$PYTHON_BIN" "$INSTALL_DIR/core/__main__.py" "\$@"
LAUNCHER_EOF
chmod +x "$LAUNCHER_PATH"

# 7. Install Lua Script to mpv scripts directory
echo "Installing Lua script to $MPV_SCRIPTS_DIR/mal_scrobbler.lua..."
cp "$SCRIPT_DIR/scripts/mal_scrobbler.lua" "$MPV_SCRIPTS_DIR/mal_scrobbler.lua"

# 8. Check PATH for ~/.local/bin
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "\n${YELLOW}[NOTE] $BIN_DIR is not in your PATH.${NC}"
    echo "Add it to your shell configuration (~/.zshrc):"
    echo -e "    ${BLUE}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
fi

echo -e "\n${GREEN}[✓] Core installation complete!${NC}\n"

# 9. Verification with doctor
"$LAUNCHER_PATH" doctor

echo -e "\n${BLUE}=== IINA Configuration Required ===${NC}"
echo "To ensure IINA loads the script:"
echo "  1. Open IINA and open Preferences (Cmd + ,)"
echo "  2. Go to the 'Advanced' tab"
echo "  3. Check 'Use config directory'"
echo "  4. Ensure path is set to: ~/.config/mpv"
echo ""
echo -e "${BLUE}=== Next Step: Authentication ===${NC}"
echo "To authenticate your MyAnimeList account, run:"
echo -e "    ${GREEN}$LAUNCHER_PATH auth login${NC}\n"
