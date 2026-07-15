# Procedural Trainer

Procedural Trainer is an open-source desktop cycling game built around an engine-agnostic geospatial pipeline and a Godot-first client. The project separates code, tooling, and distributable region data so contributors can rebuild or replace each layer without proprietary dependencies.

## Principles

- Fully open-source codebase under MIT.
- Free desktop distribution is the default product target.
- Region packs are versioned artifacts with explicit source provenance and attribution.
- The geospatial bake pipeline is independent of any specific runtime engine.
- Open/public data sources are preferred, with license obligations tracked in machine-readable manifests.

## Repository Layout

- `game-client/godot/`: Godot-first desktop client scaffold and integration boundaries.
- `geo-pipeline/`: Python tooling, schemas, and validation helpers for region-pack production.
- `region-data/`: Sample and future published region artifacts, kept separate from code.
- `docs/`: Architecture, licensing posture, and source policy.
- `docs/roadmap.md`: Phase-by-phase implementation plan from Milwaukee proof through open distribution.
- `tests/`: Validation and deterministic build tests for manifests and sample data.

## MVP Target

The initial MVP target follows the open-world plan:

- Milwaukee as the first region
- Solo riding plus ghost replays
- GPX import and snapping to a canonical ride graph
- DEM-derived elevation and trainer resistance support
- Stylized scenery rather than exact landmark reconstruction
- No mandatory cloud services for core gameplay

## Quick Start

Python 3.11+ is assumed.

```bash
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase1-region milwaukee_phase1
PYTHONPATH=geo-pipeline python3 -m unittest discover -s tests
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli validate-region region-data/milwaukee/mke_demo_region_pack
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli snap-gpx region-data/milwaukee/mke_demo_region_pack region-data/milwaukee/oak_leaf_demo_loop.gpx
game-client/godot/test_headless.sh
```

## Current Status

This repository currently provides the Phase 0 foundation:

- licensing and redistribution policy documents
- engine-agnostic data contracts for region packs
- a Godot-first client scaffold
- sample Milwaukee manifests and attribution artifacts
- local validation tooling and tests for reproducibility-oriented metadata

The repository now includes a deterministic Phase 1 Milwaukee corridor proof:

- a staged `fetch-sources` -> `prepare-sources` -> `build-phase1-region` corridor pipeline
- a generated `RideGraphPack`, `SceneryPack`, and `source_manifest.json`
- a curated Milwaukee GPX fixture for canonical snapping
- CLI commands to rebuild the sample region pack and emit snapped route definitions with distance and grade profiles
- a Godot runtime debug ride loop with virtual trainer controls and client-side GPX import through the external CLI boundary

The staged build remains lightweight and deterministic in-repo, but the public pack interfaces now model source fetch receipts, pack-local provenance, DEM-backed route grades, and a playable on-rails debug loop.

## Rebuild Walkthrough

The canonical Milwaukee proof rebuild is:

```bash
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli fetch-sources milwaukee_phase1
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli prepare-sources milwaukee_phase1
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase1-region milwaukee_phase1
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli validate-region region-data/milwaukee/mke_demo_region_pack
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli snap-gpx region-data/milwaukee/mke_demo_region_pack region-data/milwaukee/oak_leaf_demo_loop.gpx
```

## Toolchain

- Python 3.11+
- bare-Python CLI under `geo-pipeline/`
- optional GDAL/raster tooling, `osmium-tool`, and `awscli` for future live-source expansion
- Godot 4 for the runtime client
- no mandatory proprietary services or SDKs

The next execution targets are documented in [docs/roadmap.md](docs/roadmap.md).
