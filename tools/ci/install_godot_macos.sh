#!/bin/zsh
set -euo pipefail

GODOT_VERSION="${GODOT_VERSION:-4.7.1-stable}"
TEMPLATE_VERSION="${GODOT_TEMPLATE_VERSION:-${GODOT_VERSION/-stable/.stable}}"
INSTALL_ROOT="${RUNNER_TEMP:-/tmp}/procedural-trainer-godot/${GODOT_VERSION}"
EDITOR_ZIP="$INSTALL_ROOT/Godot.zip"
TEMPLATES_TPZ="$INSTALL_ROOT/Godot_export_templates.tpz"
EDITOR_DIR="$INSTALL_ROOT/editor"
TEMPLATES_DIR="$INSTALL_ROOT/templates"
GODOT_BIN="$EDITOR_DIR/Godot.app/Contents/MacOS/Godot"
TARGET_TEMPLATE_DIR="$HOME/Library/Application Support/Godot/export_templates/$TEMPLATE_VERSION"

mkdir -p "$INSTALL_ROOT" "$EDITOR_DIR" "$TEMPLATES_DIR" "$TARGET_TEMPLATE_DIR"

curl --fail --silent --show-error --location \
  --output "$EDITOR_ZIP" \
  "https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}/Godot_v${GODOT_VERSION}_macos.universal.zip"

curl --fail --silent --show-error --location \
  --output "$TEMPLATES_TPZ" \
  "https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}/Godot_v${GODOT_VERSION}_export_templates.tpz"

unzip -q -o "$EDITOR_ZIP" -d "$EDITOR_DIR"
unzip -q -o "$TEMPLATES_TPZ" -d "$TEMPLATES_DIR"

if [[ -d "$TEMPLATES_DIR/templates" ]]; then
  cp -R "$TEMPLATES_DIR/templates/." "$TARGET_TEMPLATE_DIR/"
else
  cp -R "$TEMPLATES_DIR/." "$TARGET_TEMPLATE_DIR/"
fi

if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    print "GODOT_BIN=$GODOT_BIN"
    print "GODOT_TEMPLATE_VERSION=$TEMPLATE_VERSION"
  } >> "$GITHUB_ENV"
fi

print "$GODOT_BIN"
