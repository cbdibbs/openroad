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
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase2-region milwaukee_phase2
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli validate-region region-data/milwaukee/mke_phase2_region_pack
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli snap-gpx region-data/milwaukee/mke_phase2_region_pack region-data/milwaukee/oak_leaf_demo_loop.gpx
game-client/godot/test_headless.sh

# Legacy Phase 1 proof commands remain available:
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase1-region milwaukee_phase1
PYTHONPATH=geo-pipeline python3 -m unittest discover -s tests
```

## Run The Game

Current playable state: a streamed Godot solo ride that loads the checked-in Milwaukee Phase 2 pack with curated starter routes and GPX import.

Requirements:
- Python 3.11+
- Godot 4, or `/Applications/Godot.app/Contents/MacOS/Godot` on macOS

From the repo root:

```bash
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase2-region milwaukee_phase2
game-client/godot/run_local.sh
```

If the pack is already built and you just want to launch the game again:

```bash
game-client/godot/run_local.sh
```

Controls:
- `W` / `S`: power up/down
- `A` / `D`: brake down/up
- `Q` / `E`: cadence down/up
- `Space`: clear brake
- `R`: restart route
- `P`: pause/resume
- `I`: import GPX
- `Tab`: toggle the debug HUD

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

The repository now also includes the Phase 2 Milwaukee world-pack implementation:

- a streamed Milwaukee `city + core trails` source-derived acceptance pack with `1 km` tiles and `4 km` stream regions
- staged Phase 2 source fixtures and manifests that preserve AOI identity, toolchain versions, deterministic build knobs, and source lineage
- four curated starter routes plus retained GPX import against the full Phase 2 ride graph
- a Godot client that streams adjacent regions around the rider and renders seam-safe terrain meshes, terrain-aligned roads, buildings, and biome props

## Rebuild Walkthrough

The canonical Milwaukee proof rebuild is:

```bash
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli fetch-sources milwaukee_phase2 --source-mode fixture
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli prepare-sources milwaukee_phase2 --source-mode fixture
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-ride-graph milwaukee_phase2 --source-mode fixture
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-scenery milwaukee_phase2 --source-mode fixture
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli package-region milwaukee_phase2 --source-mode fixture

# Or run the end-to-end shortcut:
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase2-region milwaukee_phase2
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli validate-region region-data/milwaukee/mke_phase2_region_pack
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli snap-gpx region-data/milwaukee/mke_phase2_region_pack region-data/milwaukee/oak_leaf_demo_loop.gpx

# Phase 1 corridor rebuild remains available:
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli fetch-sources milwaukee_phase1
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli prepare-sources milwaukee_phase1
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase1-region milwaukee_phase1
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli validate-region region-data/milwaukee/mke_demo_region_pack
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli snap-gpx region-data/milwaukee/mke_demo_region_pack region-data/milwaukee/oak_leaf_demo_loop.gpx
```

For Milwaukee live-source receipt and cache generation, use:

```bash
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli fetch-sources milwaukee_phase2 --source-mode live
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase2-region milwaukee_phase2 --source-mode live
```

The live Milwaukee lane preserves auditable upstream receipts and cached source artifacts, then normalizes through the same staged Phase 2 contracts used by the deterministic fixture lane.

## Toolchain

- Python 3.11+
- bare-Python CLI under `geo-pipeline/`
- Homebrew-installed `osmium-tool`, `gdal`, `duckdb`, and `rasterio` for the documented Phase 2 open geospatial stack
- Godot 4 for the runtime client
- no mandatory proprietary services or SDKs

The next execution targets are documented in [docs/roadmap.md](docs/roadmap.md).
