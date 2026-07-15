#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_DIR="$SCRIPT_DIR"
DEFAULT_GODOT_APP="/Applications/Godot.app/Contents/MacOS/Godot"

if [[ -n "${GODOT_BIN:-}" ]]; then
  GODOT="$GODOT_BIN"
elif [[ -x "$DEFAULT_GODOT_APP" ]]; then
  GODOT="$DEFAULT_GODOT_APP"
elif command -v godot >/dev/null 2>&1; then
  GODOT="$(command -v godot)"
else
  echo "Godot binary not found. Set GODOT_BIN or install /Applications/Godot.app." >&2
  exit 1
fi

GODOT_HOME_DEFAULT="$PROJECT_DIR/.godot-home"
export HOME="${GODOT_HOME:-$GODOT_HOME_DEFAULT}"
mkdir -p "$HOME"

exec "$GODOT" --path "$PROJECT_DIR" "$@"
