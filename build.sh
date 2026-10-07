#!/bin/bash
# Builds "The Counting.app" on a Mac. Open Terminal, drag this file in, press Return.
cd "$(dirname "$0")" || exit 1
echo "Building The Counting. This takes a few minutes the first time."
python3 -m pip install -r requirements.txt pyinstaller || { echo "Install did not finish."; exit 1; }
python3 -m PyInstaller --noconfirm --clean --windowed --name "The Counting" \
  --add-data "tally_app/web:tally_app/web" --collect-submodules webview --collect-data certifi run_thecounting.py || { echo "Build did not finish."; exit 1; }
echo
echo "Done. Your app is dist/The Counting.app. Drag it into your Applications folder."
open dist
