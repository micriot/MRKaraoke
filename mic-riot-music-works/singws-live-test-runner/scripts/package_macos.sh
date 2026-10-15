#!/bin/zsh
set -euo pipefail
python -m PyInstaller --noconfirm --windowed --name "Mic Riot Test Runner" -m singws_live_test_runner.app
