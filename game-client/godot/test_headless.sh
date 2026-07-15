#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

exec "$SCRIPT_DIR/run_local.sh" --headless --rendering-driver opengl3 --verbose --quit
