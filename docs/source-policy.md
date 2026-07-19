# Source Policy

This document defines which sources are allowed in the MVP pipeline, where they can be used, and what obligations they introduce.

## Allowed Sources

## Phase 2 Contributor Toolchain

The canonical open Phase 2 toolchain is:

```bash
brew install osmium-tool gdal duckdb
python3 -m pip install rasterio
```

Checked-in Milwaukee Phase 2 fixtures under `geo-pipeline/geo_pipeline/fixtures/milwaukee_phase2/` represent clipped, version-pinned source excerpts derived from that toolchain so contributors can run deterministic local rebuilds without re-fetching large upstreams on every test run.

The repo now supports two Milwaukee Phase 2 source lanes:

- `--source-mode fixture`: deterministic local rebuilds from the checked-in clipped source excerpts
- `--source-mode live`: auditable upstream receipt and cache generation for Milwaukee using the documented source URLs, followed by normalization through the same staged Phase 2 contracts

When a live upstream artifact is cached but not yet normalized by the lightweight local toolchain, the Milwaukee live lane may materialize the documented source-derived acceptance extract so downstream staged builds remain deterministic and testable.

### OpenStreetMap

- Use: canonical road, trail, access, and route graph data
- License: ODbL 1.0
- Rules:
  - fetch the Wisconsin `.osm.pbf` extract from Geofabrik into `work/raw/`
  - for the checked-in Milwaukee Phase 2 acceptance pack, preserve the clipped source-derived fixture excerpt as a documented cache artifact rather than regenerating synthetic graph geometry
  - record fetch URL, product id, version, checksum, and retrieval time in `source_manifest.json`
  - attribution is required in every shipped region pack
  - derived or built-upon database outputs must keep ODbL handling explicit
  - OSM-derived data must not be merged into an opaque blob with no provenance

### USGS 3DEP

- Use: Milwaukee elevation for the MVP
- License posture: public use; follow USGS attribution guidance
- Rules:
  - query The National Map Access API for corridor-intersecting 1 m DEM products
  - stage clipped or warped DEM derivatives under `work/staged/`
  - for Phase 2 acceptance fixtures, preserve the clipped DEM control grid that drives seam-safe terrain rebuilds
  - preserve source version and acquisition metadata
  - use as the preferred DEM source for US regions

### USDA NAIP

- Use: imagery-assisted preprocessing and scenery heuristics
- License posture: broadly reusable with requested credit
- Rules:
  - query AOI-intersecting NAIP products from The National Map
  - keep NAIP usage preprocessing-only for Phases 1 and 2
  - Phase 2 may mark NAIP as optional when deterministic fallback scenery synthesis is available
  - do not ship raw imagery unless packaging and size tradeoffs are intentional
  - preserve source references in attribution manifests

### ESA WorldCover

- Use: landcover and biome masks
- License: CC BY 4.0
- Rules:
  - fetch required tiles from the public `esa-worldcover` bucket
  - clip and remap classes before packaging
  - attribution is required
  - preserve product version in source metadata

### Copernicus GLO-30 / related open DEM products

- Use: non-US fallback elevation
- License posture: open access with attribution and terms compliance
- Rules:
  - do not use for Milwaukee when 3DEP is available
  - capture product lineage and version in manifests

### Godot

- Use: default game client engine
- License: MIT
- Rules:
  - engine modifications remain allowed in a fully open repo
  - do not introduce proprietary engine requirements into the core development path

## Conditional Sources

### Microsoft Global ML Building Footprints

- Use: fill-in building coverage where OSM buildings are missing
- Rules:
  - include license and provenance explicitly if used in any region pack
  - keep source-specific attribution separate from OSM attribution
  - do not silently blend with OSM building data

### Overture Maps

- Use: possible future enrichment
- Rules:
  - theme-level licensing must be inspected per source
  - treat transportation and buildings as potentially ODbL-covered
  - do not make Overture a default MVP dependency

## Disallowed For MVP

- paid or closed-source geodata required to rebuild the shipped region
- commercial imagery that cannot be redistributed with the project
- proprietary asset stores required for core gameplay
- mandatory online services for route import, map matching, or world streaming

## Packaging Requirements

- every region pack must include `attribution.json`
- every region pack must include `source_manifest.json`
- every region pack must include ride graph and scenery assets referenced from the manifest
- every region pack must include license references for each source actually used
- source versions, build date, and a region hash must be recorded
- client compatibility must be explicit in the manifest
- missing optional sources must degrade gracefully without making the pack invalid
- raw NAIP imagery must not be redistributed in the checked-in sample pack
- Phase 2 packs must record AOI identity/hash, toolchain versions, deterministic build knobs, and seam-border metadata for every generation tile
