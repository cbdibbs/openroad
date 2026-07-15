# Third-Party Notices

This repository uses or plans to use the following upstream projects and datasets in its open build and distribution flow.

## Runtime And Tooling

- Godot Engine, MIT License: https://godotengine.org/license/

## Data Sources Referenced By Policy

- OpenStreetMap contributors, ODbL 1.0: https://www.openstreetmap.org/copyright
- OSM Foundation license guidance: https://osmfoundation.org/wiki/Licence/Community_Guidelines
- USGS 3D Elevation Program: https://www.usgs.gov/3d-elevation-program
- USDA NAIP dataset summary: https://developers.google.com/earth-engine/datasets/catalog/USDA_NAIP_DOQQ
- ESA WorldCover, CC BY 4.0: https://worldcover2021.esa.int/
- Copernicus DEM collection: https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM
- Microsoft Global ML Building Footprints: https://github.com/microsoft/GlobalMLBuildingFootprints

Project-level notices in this file are not a substitute for per-region attribution manifests. Shipped region packs must include their own explicit source inventory and license references.
## Milwaukee Phase 1 Sample Corridor

The checked-in Milwaukee Phase 1 sample corridor pack under `region-data/milwaukee/mke_demo_region_pack` references the following upstream sources in machine-readable form:

- OpenStreetMap contributors, ODbL 1.0, Geofabrik Wisconsin extract lineage
- U.S. Geological Survey 3DEP, public use guidance, TNM 1 m DEM lineage
- USDA NAIP, public use with requested credit, preprocessing-only heuristic lineage
- ESA WorldCover, CC BY 4.0, v200 2021 tile lineage

See `region-data/milwaukee/mke_demo_region_pack/attribution.json` and `region-data/milwaukee/mke_demo_region_pack/source_manifest.json` for the versioned source list, usage mapping, source receipts, and redistribution notices for that pack.

## Milwaukee Phase 2 Streamed World Pack

The checked-in Milwaukee Phase 2 region pack under `region-data/milwaukee/mke_phase2_region_pack` references the same upstream source families in machine-readable form:

- OpenStreetMap contributors, ODbL 1.0, Geofabrik Wisconsin extract lineage
- U.S. Geological Survey 3DEP, public use guidance, TNM 1 m DEM lineage
- USDA NAIP, public use with requested credit, optional preprocessing-only heuristic lineage
- ESA WorldCover, CC BY 4.0, v200 2021 tile lineage

See `region-data/milwaukee/mke_phase2_region_pack/attribution.json` and `region-data/milwaukee/mke_phase2_region_pack/source_manifest.json` for the versioned source list, optional-source flags, usage mapping, source receipts, and redistribution notices for that pack.
