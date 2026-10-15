#!/bin/zsh
set -euo pipefail
python -m PyInstaller --noconfirm --windowed --name "Karaoke Collector" -m singws_live_test_runner.app
