#!/usr/bin/env bash
# Set up PrintLab's full toolchain on Linux: Python deps via uv, plus the
# native slicers and CAD tools pinned in tools.toml. See docs/environment.md for the
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

echo "==> Downloading OrcaSlicer 2.4.2 (pinned AppImage)"
ORCA_APPIMAGE="$TOOLS_DIR/OrcaSlicer-2.4.2.AppImage"
ORCA_URL="https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v2.4.2/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage"
if [ ! -f "$ORCA_APPIMAGE" ]; then
    curl -L -o "$ORCA_APPIMAGE" "$ORCA_URL"
    chmod +x "$ORCA_APPIMAGE"
fi
echo "OrcaSlicer AppImage: $ORCA_APPIMAGE"
echo "Add it to PATH as 'OrcaSlicer', e.g.:"
echo "  ln -sf \"$ORCA_APPIMAGE\" ~/.local/bin/OrcaSlicer"

echo "==> Installing OpenSCAD 2021.01"
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y openscad
else
    echo "apt-get not found -- install OpenSCAD 2021.01 from https://openscad.org/downloads.html"
fi

echo "==> Installing FreeCAD 1.1.1 (pinned official AppImage)"
case "$(uname -m)" in
    x86_64|amd64)
        FREECAD_ARCH="x86_64"
        FREECAD_SHA256="e2006138400b2fa85fa2e160e872d00767eb32964e85075830f7e198a3a876e1"
        ;;
    aarch64|arm64)
        FREECAD_ARCH="aarch64"
        FREECAD_SHA256="8004e166dc5c516cc8e8d85a5f58b5d56c3836cf8652301c2e6b9e4b1fd27827"
        ;;
    *)
        echo "No pinned FreeCAD AppImage for architecture $(uname -m)"
        exit 1
        ;;
esac
FREECAD_APPIMAGE="$TOOLS_DIR/FreeCAD_1.1.1-Linux-${FREECAD_ARCH}-py311.AppImage"
FREECAD_URL="https://github.com/FreeCAD/FreeCAD/releases/download/1.1.1/$(basename "$FREECAD_APPIMAGE")"
FREECAD_DIR="$TOOLS_DIR/FreeCAD-1.1.1-${FREECAD_ARCH}"
if [ ! -x "$FREECAD_DIR/AppRun" ]; then
    if [ ! -f "$FREECAD_APPIMAGE" ]; then
        curl -L -o "$FREECAD_APPIMAGE" "$FREECAD_URL"
    fi
    echo "$FREECAD_SHA256  $FREECAD_APPIMAGE" | sha256sum --check
    chmod +x "$FREECAD_APPIMAGE"
    FREECAD_EXTRACT_DIR="$(mktemp -d)"
    (cd "$FREECAD_EXTRACT_DIR" && "$FREECAD_APPIMAGE" --appimage-extract >/dev/null)
    mv "$FREECAD_EXTRACT_DIR/squashfs-root" "$FREECAD_DIR"
    rmdir "$FREECAD_EXTRACT_DIR"
fi
printf '%s\n' '#!/usr/bin/env bash' 'exec "$(dirname "$0")/AppRun" freecadcmd "$@"' > "$FREECAD_DIR/FreeCADCmd"
chmod +x "$FREECAD_DIR/FreeCADCmd"
mkdir -p "$HOME/.local/bin"
ln -sf "$FREECAD_DIR/FreeCADCmd" "$HOME/.local/bin/FreeCADCmd"
echo "FreeCADCmd: $HOME/.local/bin/FreeCADCmd"

echo "==> Installing CalculiX (ccx) FEA solver"
# calculix-ccx is packaged in Debian (bookworm/sid). Falls back to guidance
# elsewhere; conda-forge ships it for other distros.
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y calculix-ccx || {
        echo "apt-get could not install calculix-ccx -- install via conda-forge:"
        echo "  conda install -c conda-forge calculix"
        echo "or build ccx from source: http://www.calculix.de/"
    }
else
    echo "apt-get not found -- install CalculiX another way:"
    echo "  conda install -c conda-forge calculix"
    echo "or build ccx from source: http://www.calculix.de/"
fi

echo "==> Installing FEA Python dependency (gmsh, 'fea' extra)"
uv sync --extra fea

echo "==> Verifying installed versions against tools.toml"
uv run printlab doctor
