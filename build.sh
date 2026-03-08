#!/bin/bash
set -e

PYTHON=/Users/hartlecs/venv/py_basic/bin/python3.12
PYINSTALLER=/Users/hartlecs/venv/py_basic/bin/pyinstaller

cd "$(dirname "$0")"

echo "==> Cleaning previous build..."
for d in build dist; do
    [ -d "$d" ] && { chflags -R nouchg "$d"; rm -rf "$d"; }
done

echo "==> Building app bundle..."
$PYINSTALLER ta_scheduler.spec

echo "==> Creating DMG..."
create-dmg \
    --volname "TA Scheduler" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 128 \
    --icon "TA Scheduler.app" 175 190 \
    --hide-extension "TA Scheduler.app" \
    --app-drop-link 425 190 \
    "dist/TA Scheduler.dmg" \
    "dist/TA Scheduler.app"

echo "==> Done: dist/TA Scheduler.dmg"
