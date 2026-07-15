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
