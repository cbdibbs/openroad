# Architecture

## Goals

The project is split into three durable boundaries:

1. `geo-pipeline`: open build pipeline that ingests and transforms geodata
2. `game-client`: open runtime client that consumes baked region packs
3. `region-data`: versioned data artifacts with provenance and attribution

This split is intentional. It keeps engine-specific runtime choices separate from geospatial processing and makes future secondary clients possible without reworking the data contracts.

## Runtime Defaults

- Client engine: Godot first
- Runtime target: desktop PC first
- Game mode: solo + ghosts for MVP
- Region target: Milwaukee first
- Trainer integration: native bridge boundary, likely Rust-backed

## Pipeline Defaults

- ETL and validation: Python
- Geospatial joins and canonical graph store: PostGIS
- Raster processing: GDAL and rasterio
- Intermediate analytical products: DuckDB and Parquet
- Region bake outputs: ride graph, scenery, attribution

## Public Data Contracts

### RegionTileManifest

- `tile_id`
- `bbox_wgs84`
- `region_version`
- `source_versions`
- `ride_graph_asset`
- `terrain_asset`
- `building_asset`
- `biome_asset`
- `attribution_asset`

### RouteDefinition

- `route_id`
- `source_type`
- `source_hash`
- `snapped_edge_sequence`
- `elevation_profile_m`
- `surface_profile`
- `distance_m`
- `region_version`

## Packaging Rules

- Code, tooling, and region datasets are separate deliverables.
- Every region pack ships with a machine-readable attribution manifest.
- ODbL-covered derived data is tracked explicitly through source manifests and notices.
- Runtime chunking defaults to 1 km generation tiles and 4 km streaming regions.

## MVP Exclusions

- live multiplayer
- in-game map editing
- exact landmark reconstruction
- commercial asset dependencies
- mandatory cloud services for core gameplay
