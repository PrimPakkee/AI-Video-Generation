#!/usr/bin/env bash
# Reinstall ffmpeg with libass support so the `subtitles` / `ass`
# filters are available. Run from project root:
#   bash scripts/reinstall_ffmpeg_with_libass.sh

set -e

echo "=== Current ffmpeg ==="
/opt/homebrew/bin/ffmpeg -version 2>&1 | head -1 || true
echo

echo "=== Checking for libass support ==="
if /opt/homebrew/bin/ffmpeg -filters 2>&1 | grep -qE "^.* ass +"; then
    echo "libass IS available — no reinstall needed."
    exit 0
fi
echo "libass NOT available. Reinstalling..."
echo

# Uninstall any existing ffmpeg from main tap.
echo "=== Uninstalling current ffmpeg ==="
brew uninstall --ignore-dependencies ffmpeg 2>&1 || true

# Tap the homebrew-ffmpeg/ffmpeg formula which has --with-libass support.
echo "=== Tapping homebrew-ffmpeg ==="
brew tap homebrew-ffmpeg/ffmpeg

echo "=== Installing ffmpeg with libass ==="
# homebrew-ffmpeg/ffmpeg now bundles libass by default — no flag needed.
brew install homebrew-ffmpeg/ffmpeg/ffmpeg

echo
echo "=== Verifying ==="
/opt/homebrew/bin/ffmpeg -version 2>&1 | head -1
if /opt/homebrew/bin/ffmpeg -filters 2>&1 | grep -qE "^.* ass +"; then
    echo "SUCCESS — libass is now available."
else
    echo "FAILED — libass still missing. Try a manual install."
    exit 1
fi
