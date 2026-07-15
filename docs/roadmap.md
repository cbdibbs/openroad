# Roadmap

This document carries forward the implementation plan beyond the completed Phase 0 foundation. It is intended to guide future iterations without weakening the project's open-source, engine-agnostic, and attribution-safe constraints.

## Phase 1: Milwaukee Technical Proof

### Goal

Produce one playable Milwaukee corridor of roughly 10-20 km that proves the end-to-end loop from source ingestion to Godot playback.

### Deliverables

- Milwaukee source-ingestion scripts for:
  - OpenStreetMap transportation data
  - USGS 3DEP elevation
  - USDA NAIP imagery-derived preprocessing inputs
  - ESA WorldCover biome and landcover classes
- A corridor-scale `RideGraphPack` with:
  - snapped bikeable edges
  - bike-access filtering
  - sampled DEM elevation
  - basic junction metadata
- A minimal `SceneryPack` with:
  - terrain chunks
  - stylized road geometry
  - basic biome masks
- Godot client support for:
  - loading one sample region pack
  - importing a GPX file
  - snapping that GPX to the canonical ride graph
  - riding the resulting route with elevation-driven grade playback
- A generated `AttributionPack` shipped alongside the sample Milwaukee artifacts

### Pipeline Work

- Define Milwaukee area-of-interest clipping and source version capture.
- Build import jobs that normalize CRS, metadata, and source lineage.
- Convert OSM ways and relations into a canonical bikeable graph model.
- Replace noisy GPX elevation with DEM-derived samples.
- Produce one corridor asset set that can be loaded by the Godot client without hand-authored scene dependencies.

### Client Work

- Implement region-pack discovery and compatibility checks.
- Add a first-pass route loader for baked edges and elevation profiles.
- Render basic terrain, roads, and landmark-light scenery sufficient for ride orientation.
- Keep all map matching and bake logic out of the client.

### Acceptance Criteria

- A contributor can build the sample pack and load it in the Godot client without proprietary tooling.
- GPX import works for the sample corridor and resolves to deterministic snapped route output.
- Elevation playback comes from DEM-derived route data rather than raw GPX elevation.
- Attribution files are generated automatically and validated as part of the pack.

## Phase 2: Canonical Route And World Packs

### Goal

Expand from one corridor to a full Milwaukee ride graph and region-pack bake flow.

### Deliverables

- Full Milwaukee `RideGraphPack` generation with:
  - bike-access filtering
  - surface defaults
  - bridge and underpass handling
  - stable edge identifiers suitable for replay and route reuse
- `SceneryPack` generation for:
  - 1 km generation tiles
  - 4 km streaming regions
  - terrain chunk seams handled deterministically
  - building extrusions and simple class assignments
  - biome-driven prop masks
- Region-pack packaging workflow that emits:
  - versioned manifests
  - source version metadata
  - baked asset references
  - attribution and notice bundles

### Pipeline Work

- Move from ad hoc sample scripts to an explicit staged bake flow.
- Add deterministic tile assembly and stable ordering for asset manifests.
- Introduce validation around missing optional data sources so degradation is visible but non-fatal.
- Preserve enough lineage metadata to rebuild the same region version from the same inputs.

### Client Work

- Implement streaming-region loading around the rider.
- Load adjacent chunks and hide chunk boundaries from the ride experience.
- Improve road mesh generation and terrain alignment enough to avoid obvious seams or jumps.
- Add representative scenery, not exact landmark fidelity.

### Acceptance Criteria

- Milwaukee can be baked into versioned region packs from documented source inputs.
- The same source versions produce matching manifests and functionally identical route output.
- Chunk boundaries do not create visible terrain discontinuities or route interruptions during normal riding.
- All published region artifacts pass attribution and source metadata validation.

## Phase 3: Trainer Loop And Ghosts

### Goal

Turn the technical world-pack pipeline into a convincing ride loop with deterministic trainer playback and ghost replays.

### Deliverables

- Native trainer bridge boundary for:
  - FTMS support first
  - optional ANT+ support later
- Grade-to-resistance runtime logic driven by baked elevation and filtered slope data
- Ghost recording format based on:
  - snapped route identifiers
  - normalized timing samples
  - deterministic playback expectations
- Godot client support for:
  - recording solo efforts
  - replaying ghost rides
  - showing rider versus ghost progress without network services

### Pipeline Work

- Smooth route grades enough to avoid unrealistic resistance spikes.
- Preserve stable route and edge identifiers across rebuilds of the same region version.
- Add reference GPX and replay fixtures for deterministic validation.

### Client And Native Work

- Add a trainer abstraction layer that keeps device protocols outside gameplay code.
- Ensure route progression is based on canonical snapped geometry, not floating client-only approximations.
- Implement ghost storage as local artifacts tied to region version and route identifiers.

### Acceptance Criteria

- Trainer resistance changes are smooth enough for realistic effort transitions.
- Replaying the same ghost on the same region version yields materially identical playback across machines.
- Ghost artifacts remain valid as long as the route and region version are unchanged.
- Core riding and ghost features remain offline-capable.

## Phase 4: Open Distribution Workflow

### Goal

Publish the project and its Milwaukee region pack in a way that is reproducible, legally clear, and contributor-friendly.

### Deliverables

- Public source repository with contributor build documentation
- Separate published Milwaukee region-pack artifact with:
  - attribution bundle
  - source metadata
  - versioned manifest
  - license references appropriate to included data
- CI checks for:
  - notice file presence
  - attribution manifest validity
  - deterministic metadata expectations
  - sample pack verification
- Optional telemetry only if:
  - it is privacy-preserving
  - it is opt-in
  - the game remains fully usable offline without it

### Release Work

- Document the exact rebuild steps for the sample and Milwaukee region packs.
- Version code and region artifacts independently but compatibly.
- Publish license explanations that distinguish MIT code from data-license obligations.
- Treat region packs as auditable deliverables, not opaque export blobs.

### Acceptance Criteria

- A new contributor can clone the repo, run the documented validation commands, and understand how to rebuild a sample pack.
- Milwaukee region-pack distribution is accompanied by clear attribution and license notices.
- CI fails when region-pack metadata or notices are missing or inconsistent.
- No blocking proprietary dependency is introduced into the core development or distribution path.

## Cross-Phase Test Plan

The following tests must exist before the MVP is considered complete:

- The same GPX snaps to the same route on repeated imports.
- Rebuilding Milwaukee with the same source versions yields the same manifests and functionally identical route output.
- Region packs include all required attribution and source metadata.
- Missing optional sources degrade gracefully without breaking gameplay.
- Bridge and underpass routes avoid false elevation spikes.
- Chunk boundaries do not produce visible seams or ride interruptions.
- Trainer resistance is smooth enough for realistic effort changes.
- A new contributor can build the client and run one sample region without proprietary tooling.

## Acceptance Thresholds

- `>= 95%` snap success on a curated Milwaukee GPX set
- deterministic rebuilds for the same source inputs
- no blocking proprietary dependency in the core development path
- all shipped region artifacts pass attribution and license checks
