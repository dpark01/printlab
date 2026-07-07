#!/usr/bin/env bash
# Set up PrintLab's full toolchain on Linux: Python deps via uv, plus the
# native slicers pinned in tools.toml. See docs/environment.md for the
# three-layer reproducibility model this script implements layer 2 of.
#
# PrusaSlicer does not publish a Linux binary on its GitHub releases (only
# Windows/macOS) -- confirmed by inspecting the version_2.9.6 release assets.
# Its supported Linux distribution channel is Flatpak, so that's what this
# script uses; if you build PrusaSlicer from source instead, `printlab
# doctor` will still report whatever version it finds on PATH.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TOOLS_DIR="${PRINTLAB_TOOLS_DIR:-$HOME/.local/share/printlab/tools}"
mkdir -p "$TOOLS_DIR"

echo "==> Installing Python dependencies (uv sync)"
uv sync

echo "==> Installing PrusaSlicer 2.9.6 (Flatpak)"
if command -v flatpak >/dev/null 2>&1; then
    flatpak install --noninteractive --or-update flathub com.prusa3d.PrusaSlicer
else
    echo "flatpak not found -- install it, or build PrusaSlicer 2.9.6 from source:"
    echo "  https://github.com/prusa3d/PrusaSlicer"
fi

echo "==> Downloading Bambu Studio 02.07.01.62 (pinned AppImage)"
BAMBU_APPIMAGE="$TOOLS_DIR/BambuStudio-02.07.01.62.AppImage"
BAMBU_URL="https://github.com/bambulab/BambuStudio/releases/download/v02.07.01.62/BambuStudio_ubuntu24.04-v02.07.01.62-20260616195227.AppImage"
if [ ! -f "$BAMBU_APPIMAGE" ]; then
    curl -L -o "$BAMBU_APPIMAGE" "$BAMBU_URL"
    chmod +x "$BAMBU_APPIMAGE"
fi
echo "Bambu Studio AppImage: $BAMBU_APPIMAGE"
echo "Add it to PATH as 'BambuStudio', e.g.:"
echo "  ln -sf \"$BAMBU_APPIMAGE\" ~/.local/bin/BambuStudio"

echo "==> Verifying installed versions against tools.toml"
uv run printlab doctor
