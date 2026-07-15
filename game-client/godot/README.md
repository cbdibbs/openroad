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

## Phase 1 Runtime

The checked-in Phase 1 scaffold loads the Milwaukee sample pack from `../../region-data/milwaukee/mke_demo_region_pack` by default and renders:

- manifest-driven region-pack loading
- ride graph road segments
- minimal terrain and biome patches
- deterministic route playback from the baked snapped edge sequence

GPX snapping remains outside the client. Use the Python CLI to rebuild the sample pack and emit route definitions before testing the Godot scene.

## Local Run And Test

Run the client locally:

```bash
game-client/godot/run_local.sh
```

Run a headless smoke test that loads the main scene:

```bash
game-client/godot/test_headless.sh
```

Both scripts prefer `/Applications/Godot.app/Contents/MacOS/Godot`, fall back to `godot` on `PATH`, and isolate Godot user data under a writable temp-style home if needed. Override the binary explicitly with `GODOT_BIN=/path/to/Godot`.
