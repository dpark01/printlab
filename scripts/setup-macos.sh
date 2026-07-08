#!/usr/bin/env bash
# Set up PrintLab's full toolchain on macOS: Python deps via uv, plus the
# native slicers pinned in tools.toml. See docs/environment.md for the
# three-layer reproducibility model this script implements layer 2 of.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "==> Installing Python dependencies (uv sync)"
uv sync

echo "==> Installing native slicers (Homebrew casks)"
brew install --cask prusaslicer bambu-studio orcaslicer

echo "==> Verifying installed versions against tools.toml"
uv run printlab doctor
