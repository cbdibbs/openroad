from __future__ import annotations

from pathlib import Path
from typing import Any

from geo_pipeline.phase1 import (
    DEFAULT_GPX_PATH,
    DEFAULT_REGION_CONFIG,
    DEFAULT_REGION_DIR,
    build_phase1_region,
    build_ride_graph,
    load_region_config,
    route_from_gpx,
)


def sample_ride_graph() -> dict[str, Any]:
    return build_ride_graph(DEFAULT_REGION_CONFIG)


def build_sample_region_pack(path: Path, gpx_path: Path = DEFAULT_GPX_PATH) -> dict[str, Any]:
    region = build_phase1_region(DEFAULT_REGION_CONFIG)
    if path != DEFAULT_REGION_DIR:
        from geo_pipeline.phase1 import package_region, work_paths

        config = load_region_config(DEFAULT_REGION_CONFIG)
        package_region(DEFAULT_REGION_CONFIG)
        default_dir = work_paths(config)["package"]
        path.mkdir(parents=True, exist_ok=True)
        for filename in [
            "manifest.json",
            "ride_graph.json",
            "scenery.json",
            "routes.json",
            "attribution.json",
            "source_manifest.json",
        ]:
            (path / filename).write_text((default_dir / filename).read_text(encoding="utf-8"), encoding="utf-8")
    if gpx_path != DEFAULT_GPX_PATH:
        ride_graph = region["ride_graph"]
        region["routes"] = [route_from_gpx(gpx_path, ride_graph, load_region_config(DEFAULT_REGION_CONFIG))]
    return region
