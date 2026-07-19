# Godot Client

This directory is the default runtime client for the MVP.

## Scope

- desktop PC target first
- region-pack ingestion only; no embedded geospatial bake logic
- world streaming by 4 km regions backed by 1 km source tiles
- native bridge boundary for trainer integration and future high-performance helpers

## Integration Boundaries

- `addons/procedural_trainer/`: region-pack loader and validation hooks
- `native/`: future Rust or C-compatible bridge outputs
- `scenes/`: gameplay and streaming scenes

The client intentionally depends on baked data contracts defined under `geo-pipeline/geo_pipeline/schemas/`.

## Phase 2 Runtime

The checked-in client now loads the deterministic Milwaukee Phase 2 pack from `region-data/milwaukee/mke_phase2_region_pack` by default and renders:

- root-manifest driven region-pack loading
- starter-route selection plus GPX import
- an over-the-bars riding camera with a first-person-ish `66 degree` FOV
- forward-biased tile streaming backed by `1 km` tile assets
- deferred detail loading so dense props, buildings, and side-street detail stay near the rider
- deterministic route playback from baked snapped edge sequences
- representative terrain, roads, building extrusions, biome patches, and prop hints
- keyboard-driven debug trainer controls with a live HUD

When exported for release, the client also looks for the same `region-data/`, `sample-tracks/`, and `geo-pipeline/` layout adjacent to the app bundle so the shipped starter routes still work outside the repo checkout. GPX import continues to rely on an available `python3` runtime.

GPX snapping remains outside the client. The runtime shells out to `geo-pipeline/run_geo_pipeline_cli.py` using the configured Python executable and loads the resulting route JSON from a temp output directory.

## Local Run And Test

Run the client locally:

```bash
game-client/godot/run_local.sh
```

Run a headless smoke test that loads the main scene:

```bash
game-client/godot/test_headless.sh
```

The headless command now runs assertion-based Phase 2 playback checks by default. It validates boot, route activation, route restart, stream-region transitions, and GPX import handling, and can emit machine-readable results with `PT_HEADLESS_RESULTS_PATH=/tmp/phase2.json`.

Both scripts prefer `/Applications/Godot.app/Contents/MacOS/Godot`, fall back to `godot` on `PATH`, and isolate Godot user data under a writable temp-style home if needed. Override the binary explicitly with `GODOT_BIN=/path/to/Godot`.

## Debug Controls

- `W` / `S`: power up/down
- `A` / `D`: brake down/up
- `Q` / `E`: cadence down/up
- `[` / `]`: previous/next starter route
- `1` / `2` / `3`: select starter route directly
- `Space`: clear brake
- `R`: restart route
- `P`: pause/resume
- `I`: import GPX
- `Tab`: toggle HUD
