#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

export PT_HEADLESS_ASSERT="${PT_HEADLESS_ASSERT:-1}"
export PT_HEADLESS_TEST_GPX="${PT_HEADLESS_TEST_GPX:-$REPO_ROOT/sample-tracks/Wauwatosa_to_Lakefront.gpx}"

if [[ -z "${PT_HEADLESS_RESULTS_PATH:-}" ]]; then
  export PT_HEADLESS_RESULTS_PATH="$(mktemp "/tmp/procedural-trainer-headless.XXXXXX").json"
fi

exec "$SCRIPT_DIR/run_local.sh" --headless --rendering-driver opengl3 --verbose
