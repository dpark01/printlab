#!/usr/bin/env bash
# Install PrintLab's complete Linux toolchain. Official release artifacts are
# pinned by URL and SHA-256; PrusaSlicer's Flatpak is pinned by OSTree commit.
# The full stack is currently x86_64-only because Bambu Studio does not publish
# a Linux aarch64 artifact at the version pinned in tools.toml.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v uv >/dev/null 2>&1 || [[ "$(uv --version)" != "uv 0.11.27"* ]]; then
    echo "Install uv 0.11.27 before running this script; see docs/environment.md." >&2
    exit 1
fi

if [ "$(uname -m)" != "x86_64" ] && [ "$(uname -m)" != "amd64" ]; then
    echo "The pinned full Linux toolchain supports x86_64 only (found $(uname -m))." >&2
    exit 1
fi

TOOLS_DIR="${PRINTLAB_TOOLS_DIR:-$HOME/.local/share/printlab/tools}"
BIN_DIR="${PRINTLAB_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$TOOLS_DIR" "$BIN_DIR"
export PATH="$BIN_DIR:$PATH"
if [ -n "${GITHUB_PATH:-}" ]; then
    printf '%s\n' "$BIN_DIR" >> "$GITHUB_PATH"
fi

download_pinned() {
    local url="$1"
    local destination="$2"
    local sha256="$3"
    if [ ! -f "$destination" ]; then
        curl --fail --location --output "$destination" "$url"
    fi
    printf '%s  %s\n' "$sha256" "$destination" | sha256sum --check
    chmod +x "$destination"
}

extract_appimage() {
    local appimage="$1"
    local destination="$2"
    if [ -x "$destination/AppRun" ]; then
        return
    fi
    local extract_dir
    extract_dir="$(mktemp -d)"
    (cd "$extract_dir" && "$appimage" --appimage-extract >/dev/null)
    mv "$extract_dir/squashfs-root" "$destination"
    rmdir "$extract_dir"
}

write_wrapper() {
    local name="$1"
    local executable="$2"
    printf '%s\n' '#!/usr/bin/env bash' "exec \"$executable\" \"\$@\"" > "$BIN_DIR/$name"
    chmod +x "$BIN_DIR/$name"
}

echo "==> Installing complete Python environment from uv.lock"
uv sync --all-extras

if ! command -v apt-get >/dev/null 2>&1; then
    echo "The full Linux installer currently requires an apt-based distribution." >&2
    exit 1
fi

echo "==> Installing pinned-runtime prerequisites"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential curl flatpak fontconfig fonts-liberation gfortran \
    libarpack2-dev libglu1-mesa libopenblas-dev patch pkg-config xauth xvfb

echo "==> Installing PrusaSlicer 2.9.6 (pinned Flathub commits)"
PRUSA_COMMIT="bf3534e4ffc688bbaf625206f27f9333b1b8820d3425dae19d3083b47e08ce79"
GNOME_RUNTIME_COMMIT="dec0fb025083b3543c1b1342360af86d5942fb2ac1358df3b8ac66168661b923"
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
if flatpak info --user org.gnome.Platform/x86_64/50 >/dev/null 2>&1; then
    :
else
    flatpak install --user --noninteractive flathub org.gnome.Platform/x86_64/50
fi
flatpak update --user --noninteractive --commit="$GNOME_RUNTIME_COMMIT" org.gnome.Platform/x86_64/50
if flatpak info --user com.prusa3d.PrusaSlicer/x86_64/stable >/dev/null 2>&1; then
    :
else
    flatpak install --user --noninteractive flathub com.prusa3d.PrusaSlicer/x86_64/stable
fi
flatpak update --user --noninteractive --commit="$PRUSA_COMMIT" com.prusa3d.PrusaSlicer/x86_64/stable
printf '%s\n' '#!/usr/bin/env bash' 'exec flatpak run com.prusa3d.PrusaSlicer "$@"' > "$BIN_DIR/prusa-slicer"
chmod +x "$BIN_DIR/prusa-slicer"

echo "==> Installing Bambu Studio 02.07.01.62"
BAMBU_APPIMAGE="$TOOLS_DIR/BambuStudio_ubuntu24.04-v02.07.01.62-20260616195227.AppImage"
download_pinned \
    "https://github.com/bambulab/BambuStudio/releases/download/v02.07.01.62/$(basename "$BAMBU_APPIMAGE")" \
    "$BAMBU_APPIMAGE" \
    "fa98b608532dfbbbb2b0931483aac41e57fb19c175a2cc7bd7d528d5e0fbb287"
BAMBU_DIR="$TOOLS_DIR/BambuStudio-02.07.01.62-x86_64"
extract_appimage "$BAMBU_APPIMAGE" "$BAMBU_DIR"
write_wrapper BambuStudio "$BAMBU_DIR/AppRun"

echo "==> Installing OrcaSlicer 2.4.2"
ORCA_APPIMAGE="$TOOLS_DIR/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage"
download_pinned \
    "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v2.4.2/$(basename "$ORCA_APPIMAGE")" \
    "$ORCA_APPIMAGE" \
    "d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd"
ORCA_DIR="$TOOLS_DIR/OrcaSlicer-2.4.2-x86_64"
extract_appimage "$ORCA_APPIMAGE" "$ORCA_DIR"
write_wrapper OrcaSlicer "$ORCA_DIR/AppRun"

echo "==> Installing OpenSCAD 2026.06.12 native snapshot"
OPENSCAD_APPIMAGE="$TOOLS_DIR/OpenSCAD-2026.06.12-x86_64.AppImage"
download_pinned \
    "https://files.openscad.org/snapshots/$(basename "$OPENSCAD_APPIMAGE")" \
    "$OPENSCAD_APPIMAGE" \
    "4e1739b3ec6314506ff6c5d34158143a2fc3ef857c9367b53d5e49ea2957e2bd"
OPENSCAD_DIR="$TOOLS_DIR/OpenSCAD-2026.06.12-x86_64"
extract_appimage "$OPENSCAD_APPIMAGE" "$OPENSCAD_DIR"
write_wrapper openscad "$OPENSCAD_DIR/AppRun"

echo "==> Installing FreeCAD 1.1.1"
FREECAD_APPIMAGE="$TOOLS_DIR/FreeCAD_1.1.1-Linux-x86_64-py311.AppImage"
download_pinned \
    "https://github.com/FreeCAD/FreeCAD/releases/download/1.1.1/$(basename "$FREECAD_APPIMAGE")" \
    "$FREECAD_APPIMAGE" \
    "e2006138400b2fa85fa2e160e872d00767eb32964e85075830f7e198a3a876e1"
FREECAD_DIR="$TOOLS_DIR/FreeCAD-1.1.1-x86_64"
extract_appimage "$FREECAD_APPIMAGE" "$FREECAD_DIR"
printf '%s\n' '#!/usr/bin/env bash' 'exec "$(dirname "$0")/AppRun" freecadcmd "$@"' > "$FREECAD_DIR/FreeCADCmd"
chmod +x "$FREECAD_DIR/FreeCADCmd"
ln -sf "$FREECAD_DIR/FreeCADCmd" "$BIN_DIR/FreeCADCmd"

echo "==> Installing CalculiX 2.23 from pinned sources"
CALCULIX_DIR="$TOOLS_DIR/CalculiX-2.23-x86_64"
if [ ! -x "$CALCULIX_DIR/ccx_2.23" ]; then
    CALCULIX_BUILD_DIR="$(mktemp -d)"
    download_pinned \
        "https://www.dhondt.de/ccx_2.23.src.tar.bz2" \
        "$CALCULIX_BUILD_DIR/ccx_2.23.src.tar.bz2" \
        "9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7"
    download_pinned \
        "https://www.netlib.org/linalg/spooles/spooles.2.2.tgz" \
        "$CALCULIX_BUILD_DIR/spooles.2.2.tgz" \
        "a84559a0e987a1e423055ef4fdf3035d55b65bbe4bf915efaa1a35bef7f8c5dd"
    tar -xjf "$CALCULIX_BUILD_DIR/ccx_2.23.src.tar.bz2" -C "$CALCULIX_BUILD_DIR"
    mkdir "$CALCULIX_BUILD_DIR/spooles"
    tar -xzf "$CALCULIX_BUILD_DIR/spooles.2.2.tgz" -C "$CALCULIX_BUILD_DIR/spooles"
    sed -i 's#/usr/lang-4.0/bin/cc#gcc#' "$CALCULIX_BUILD_DIR/spooles/Make.inc"
    sed -i 's/drawTree.c/tree.c/' "$CALCULIX_BUILD_DIR/spooles/Tree/src/makeGlobalLib"
    sed -i 's/IVinit(nfront, NULL)/IVinit(nfront, 0)/' "$CALCULIX_BUILD_DIR/spooles/ETree/src/transform.c"
    sed -i 's/^ccx_2.23: $(OCCXMAIN) ccx_2.23.a  $(LIBS)$/ccx_2.23: $(OCCXMAIN) ccx_2.23.a/' \
        "$CALCULIX_BUILD_DIR/ccx_2.23/src/Makefile"
    sed -i 's/  return NULL;/  return;/' "$CALCULIX_BUILD_DIR/ccx_2.23/src/readnewmesh.c"
    make -C "$CALCULIX_BUILD_DIR/spooles" lib
    make -C "$CALCULIX_BUILD_DIR/spooles/MT/src" makeLib
    make -C "$CALCULIX_BUILD_DIR/ccx_2.23/src" ccx_2.23 \
        CC=gcc FC=gfortran \
        'CFLAGS=-O2 -I../../spooles -DARCH=Linux -DSPOOLES -DARPACK -DMATRIXSTORAGE -DUSE_MT=1' \
        'FFLAGS=-O2 -fopenmp -cpp' \
        "LIBS=../../spooles/spooles.a $(pkg-config --libs arpack) -lopenblas -pthread"
    mkdir "$CALCULIX_DIR"
    cp "$CALCULIX_BUILD_DIR/ccx_2.23/src/ccx_2.23" "$CALCULIX_DIR/ccx_2.23"
    chmod +x "$CALCULIX_DIR/ccx_2.23"
fi
ln -sf "$CALCULIX_DIR/ccx_2.23" "$BIN_DIR/ccx_2.23"

echo "==> Verifying the complete native stack against tools.toml"
if [ -z "${DISPLAY:-}" ]; then
    xvfb-run -a uv run printlab doctor --strict
else
    uv run printlab doctor --strict
fi
