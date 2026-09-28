#!/usr/bin/env bash
# ==============================================================================
# ollux — Universal Linux One-Line Installer
# Installs ollux as a native desktop application with icons and desktop entry.
# https://github.com/AGIQdev-Aditya/ollux
# ==============================================================================

set -e

BOLD="\033[1m"
CYAN="\033[36m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${CYAN}${BOLD}"
echo "  ___  _ _ _  _ _ _ _ "
echo " / _ \| | | || | | | |"
echo "| (_) | | | || | | | |"
echo " \___/|_|_|_|\___/_|_|"
echo -e "${RESET}"
echo -e "${BOLD}ollux — Native Linux Desktop Companion for Ollama${RESET}"
echo -e "Created by Aditya Sharma (@AGIQdev-Aditya)\n"

# 1. Check for Arch Linux (Native pacman package install)
if command -v pacman >/dev/null 2>&1; then
    echo -e "${GREEN}✓${RESET} Detected Arch-based distribution."
    echo -e "Installing pre-built native package via pacman..."
    RELEASE_URL="https://github.com/AGIQdev-Aditya/ollux/releases/download/v0.1.0/ollux-0.1.0-1-any.pkg.tar.zst"
    sudo pacman -U --needed "$RELEASE_URL"
    echo -e "\n${GREEN}${BOLD}🎉 Installation Complete!${RESET}"
    echo -e "Launch ollux from your application menu or run: ${CYAN}ollux${RESET}\n"
    exit 0
fi

# 2. Universal / Multi-Distro User Install (~/.local)
INSTALL_DIR="$HOME/.local/share/ollux"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/512x512/apps"
ICON_SCALABLE="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$ICON_SCALABLE"

echo -e "${CYAN}•${RESET} Installing system dependencies..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv python3-gi \
        gir1.2-webkit2-4.1 gir1.2-gtk-3.0 python3-requests python3-pypdf
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-gobject webkit2gtk4.1 gtk3 \
        python3-requests python3-pypdf python3-pip
fi

echo -e "${CYAN}•${RESET} Fetching latest ollux release..."
TMP_DIR=$(mktemp -d)
curl -sSL "https://github.com/AGIQdev-Aditya/ollux/archive/refs/tags/v0.1.0.tar.gz" -o "$TMP_DIR/ollux.tar.gz"
tar -xzf "$TMP_DIR/ollux.tar.gz" -C "$TMP_DIR"
SRC_FOLDER=$(find "$TMP_DIR" -maxdepth 1 -type d -name "ollux*" | head -n 1)

rm -rf "$INSTALL_DIR/src" "$INSTALL_DIR/assets"
cp -r "$SRC_FOLDER/src" "$INSTALL_DIR/"
cp -r "$SRC_FOLDER/assets" "$INSTALL_DIR/"

# Setup python environment if needed
if [ ! -d "$INSTALL_DIR/.venv" ]; then
    echo -e "${CYAN}•${RESET} Setting up Python environment..."
    python3 -m venv --system-site-packages "$INSTALL_DIR/.venv"
    "$INSTALL_DIR/.venv/bin/pip" install --quiet pywebview ddgs
fi

# Create launcher script in ~/.local/bin/ollux
cat << 'EOF' > "$BIN_DIR/ollux"
#!/usr/bin/env bash
export WEBKIT_DISABLE_DMABUF_RENDERER=1
DIR="$HOME/.local/share/ollux"
if [ -d "$DIR/.venv" ]; then
    source "$DIR/.venv/bin/activate"
fi
exec python3 "$DIR/src/main.py" "$@"
EOF
chmod +x "$BIN_DIR/ollux"

# Install Desktop Entry & Icons
cp "$SRC_FOLDER/ollux.desktop" "$APP_DIR/ollux.desktop"
cp "$SRC_FOLDER/assets/ollux.png" "$ICON_DIR/ollux.png"
cp "$SRC_FOLDER/assets/ollux.svg" "$ICON_SCALABLE/ollux.svg"

rm -rf "$TMP_DIR"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

echo -e "\n${GREEN}${BOLD}🎉 Installation Complete!${RESET}"
echo -e "ollux is now installed as a desktop application."
echo -e "You can launch it from your app launcher (GNOME, KDE, Rofi) or run: ${CYAN}ollux${RESET}"
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo -e "${YELLOW}Note:${RESET} Ensure ~/.local/bin is in your PATH."
fi
echo ""
