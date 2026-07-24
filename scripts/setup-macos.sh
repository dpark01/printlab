#!/usr/bin/env bash
# Install PrintLab's complete macOS toolchain from pinned release artifacts.
# GUI applications live in ~/Applications so this recipe needs no admin access.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v uv >/dev/null 2>&1 || [[ "$(uv --version)" != "uv 0.11.27"* ]]; then
    echo "Install uv 0.11.27 before running this script; see docs/environment.md." >&2
    exit 1
fi

TOOLS_DIR="${PRINTLAB_TOOLS_DIR:-$HOME/.local/share/printlab/tools}"
APPLICATIONS_DIR="${PRINTLAB_APPLICATIONS_DIR:-$HOME/Applications}"
mkdir -p "$TOOLS_DIR" "$APPLICATIONS_DIR"

download_pinned() {
    local url="$1"
    local destination="$2"
    local sha256="$3"
    if [ ! -f "$destination" ]; then
        curl --fail --location --output "$destination" "$url"
    fi
    printf '%s  %s\n' "$sha256" "$destination" | shasum --algorithm 256 --check
}

install_dmg_app() {
    local name="$1"
    local source_path="$2"
    local url="$3"
    local sha256="$4"
    local target="$APPLICATIONS_DIR/$name.app"
    if [ -d "$target" ] || [ -d "/Applications/$name.app" ]; then
        return
    fi
    install_dmg_path "$source_path" "$url" "$sha256" "$target"
}

install_dmg_path() {
    local source_path="$1"
    local url="$2"
    local sha256="$3"
    local target="$4"
    if [ -d "$target" ]; then
        return
    fi
    local dmg="$TOOLS_DIR/$(basename "$url")"
    local mount_dir
    download_pinned "$url" "$dmg" "$sha256"
    mount_dir="$(mktemp -d)"
    hdiutil attach "$dmg" -nobrowse -readonly -mountpoint "$mount_dir" >/dev/null
    ditto "$mount_dir/$source_path" "$target"
    hdiutil detach "$mount_dir" >/dev/null
    rmdir "$mount_dir"
}

echo "==> Installing complete Python environment from uv.lock"
uv sync --all-extras

echo "==> Installing PrusaSlicer 2.9.6"
install_dmg_app \
    PrusaSlicer \
    "Original Prusa Drivers/PrusaSlicer.app" \
    "https://github.com/prusa3d/PrusaSlicer/releases/download/version_2.9.6/PrusaSlicer-2.9.6.dmg" \
    "94fd7b8a9f87c9631e1c71739b15b184fc5f4c0ceabd69072f1c78f229a4fe40"

echo "==> Installing Bambu Studio 02.07.01.62"
install_dmg_app \
    BambuStudio \
    "BambuStudio.app" \
    "https://github.com/bambulab/BambuStudio/releases/download/v02.07.01.62/Bambu_Studio_mac-v02.07.01.62-20260616174358.dmg" \
    "1e54c25aefc5249d56b63711cf773bed56f14430aafcc34340cd4894aef15896"

echo "==> Installing OrcaSlicer 2.4.2"
install_dmg_app \
    OrcaSlicer \
    "OrcaSlicer.app" \
    "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v2.4.2/OrcaSlicer_Mac_universal_V2.4.2.dmg" \
    "e15e7bb1b66214ec6e96b169b388004179c4f5f705effcdaf8c80d4992ee0366"

echo "==> Installing OpenSCAD 2026.06.12 universal snapshot"
install_dmg_path \
    "OpenSCAD.app" \
    "https://files.openscad.org/snapshots/OpenSCAD-2026.06.12.dmg" \
    "555be2ed313e67657b3d8ba3e1de0acd6141b982fd458776c52d3eda748f57c4" \
    "$TOOLS_DIR/OpenSCAD-2026.06.12.bundle"

echo "==> Installing FreeCAD 1.1.1"
case "$(uname -m)" in
    arm64)
        FREECAD_DMG="FreeCAD_1.1.1-macOS-arm64-py311.dmg"
        FREECAD_SHA256="fbcab489c3d37057c2283e298ef2d50c4930cc988fb331ea7df3ad75879e3949"
        ;;
    x86_64)
        FREECAD_DMG="FreeCAD_1.1.1-macOS-x86_64-py311.dmg"
        FREECAD_SHA256="bcbe4c74abb454a05728d84185a64d9d191a8f2c53d3a58dc2e33be597e3cf36"
        ;;
    *)
        echo "No pinned FreeCAD artifact for architecture $(uname -m)." >&2
        exit 1
        ;;
esac
install_dmg_app \
    FreeCAD \
    "FreeCAD.app" \
    "https://github.com/FreeCAD/FreeCAD/releases/download/1.1.1/$FREECAD_DMG" \
    "$FREECAD_SHA256"

echo "==> Installing CalculiX 2.23 from a pinned Homebrew formula"
if ! command -v ccx_2.23 >/dev/null 2>&1; then
    if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew is required to build the pinned CalculiX formula." >&2
        exit 1
    fi
    CALCULIX_FORMULA="$TOOLS_DIR/calculix-ccx-57711a3e.rb"
    download_pinned \
        "https://raw.githubusercontent.com/costerwi/homebrew-calculix/57711a3e00dec3128664260a9f58e69fbe874dca/calculix-ccx.rb" \
        "$CALCULIX_FORMULA" \
        "550e3bd241eddd2771df4eeccb9ebbb8895f8b884ebd114cf186865e03aee276"
    brew install --formula "$CALCULIX_FORMULA"
fi

echo "==> Verifying the complete native stack against tools.toml"
uv run printlab doctor --strict
