from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import math
import shutil

from geo_pipeline.determinism import content_hash
from geo_pipeline.phase1 import (
    _distance_profile,
    _mkdir,
    _segment_length,
    _source_artifacts,
    build_grade_profile,
    load_region_config,
    route_from_gpx,
    stable_edge_id,
)
from geo_pipeline.gpx import GpxPoint, load_gpx_points


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGION_CONFIG = "milwaukee_phase2"
DEFAULT_REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_phase2_region_pack"
SAMPLE_TRACK_PATH = ROOT / "sample-tracks" / "Wauwatosa_to_Lakefront.gpx"
OAKLEAF_TRACK_PATH = ROOT / "region-data" / "milwaukee" / "oak_leaf_demo_loop.gpx"


@dataclass(frozen=True)
class Phase2Paths:
    raw: Path
    staged: Path
    build: Path
    package: Path


def work_paths(config: dict[str, Any]) -> Phase2Paths:
    work = config["work_dirs"]
    return Phase2Paths(
        raw=ROOT / work["raw"],
        staged=ROOT / work["staged"],
        build=ROOT / work["build"],
        package=ROOT / config["package_dir"],
    )


def _point_wgs84(config: dict[str, Any], point_m: list[float]) -> list[float]:
    west, south, east, north = config["bbox_wgs84"]
    width_m = float(config["world_bounds_m"][0])
    height_m = float(config["world_bounds_m"][1])
    lon = west + ((east - west) * (float(point_m[0]) / width_m))
    lat = south + ((north - south) * (float(point_m[1]) / height_m))
    return [round(lon, 6), round(lat, 6)]


def _sample_elevation(point_m: list[float]) -> float:
    x = float(point_m[0])
    y = float(point_m[1])
    elevation = 188.0 + (math.sin(x / 1500.0) * 4.0) + (math.cos(y / 1700.0) * 3.2) + ((x + y) / 12000.0)
    return round(elevation, 2)


def _corridor_feature(
	config: dict[str, Any],
	osm_way_id: str,
	tags: dict[str, str],
	geometry_m: list[list[float]],
	geometry_wgs84: list[list[float]] = [],
) -> dict[str, Any]:
	return {
		"osm_way_id": osm_way_id,
		"tags": tags,
		"geometry_m": geometry_m,
		"geometry_wgs84": geometry_wgs84 if geometry_wgs84 else [_point_wgs84(config, point) for point in geometry_m],
		"elevation_profile_m": [_sample_elevation(point) for point in geometry_m],
	}


def _grid_lines(start: float, end: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current <= end + 0.001:
        values.append(round(current, 1))
        current += step
    return values


def _gpx_track_geometry_m(points: list[GpxPoint], offset_x: float, offset_y: float) -> list[list[float]]:
    first = points[0]
    mean_lat = math.radians(sum(point.latitude for point in points) / len(points))
    meters_per_degree_lon = 111_320.0 * math.cos(mean_lat)
    meters_per_degree_lat = 110_540.0
    geometry: list[list[float]] = []
    for point in points:
        x = offset_x + ((point.longitude - first.longitude) * meters_per_degree_lon)
        y = offset_y + ((point.latitude - first.latitude) * meters_per_degree_lat)
        rounded = [round(x, 1), round(y, 1)]
        if not geometry or geometry[-1] != rounded:
            geometry.append(rounded)
    if geometry[0] != geometry[-1]:
        geometry.append(list(geometry[0]))
    return geometry


def _feature_from_gpx_track(config: dict[str, Any], path: Path, osm_way_id: str, offset_x: float, offset_y: float) -> dict[str, Any]:
    points = load_gpx_points(path)
    deduped_points: list[GpxPoint] = []
    for point in points:
        if deduped_points and point.latitude == deduped_points[-1].latitude and point.longitude == deduped_points[-1].longitude:
            continue
        deduped_points.append(point)
    geometry_wgs84 = [[round(point.longitude, 6), round(point.latitude, 6)] for point in deduped_points]
    if geometry_wgs84[0] != geometry_wgs84[-1]:
        geometry_wgs84.append(list(geometry_wgs84[0]))
    geometry_m = _gpx_track_geometry_m(deduped_points, offset_x, offset_y)
    feature = _corridor_feature(
        config,
        osm_way_id,
        {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"},
        geometry_m,
        geometry_wgs84,
    )
    feature["elevation_profile_m"] = [
        round((point.elevation_m if point.elevation_m is not None else _sample_elevation(geometry_m[index])) - 8.0, 2)
        for index, point in enumerate(deduped_points)
    ]
    if len(feature["elevation_profile_m"]) < len(feature["geometry_m"]):
        feature["elevation_profile_m"].append(feature["elevation_profile_m"][0])
    return feature


def _network_features(config: dict[str, Any]) -> list[dict[str, Any]]:
    width_m = float(config["world_bounds_m"][0])
    height_m = float(config["world_bounds_m"][1])
    features: list[dict[str, Any]] = []
    way_index = 2000

    def next_way_id() -> str:
        nonlocal way_index
        way_index += 1
        return f"way/{way_index}"

    for x in _grid_lines(800.0, width_m - 800.0, 1600.0):
        for y0 in _grid_lines(0.0, height_m - 800.0, 800.0):
            y1 = min(height_m, y0 + 800.0)
            features.append(
                _corridor_feature(
                    config,
                    next_way_id(),
                    {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"},
                    [[x, y0], [x, y1]],
                )
            )

    for y in _grid_lines(800.0, height_m - 800.0, 1600.0):
        for x0 in _grid_lines(0.0, width_m - 800.0, 800.0):
            x1 = min(width_m, x0 + 800.0)
            surface = "compacted" if int((x0 + y) / 800.0) % 3 == 0 else "asphalt"
            features.append(
                _corridor_feature(
                    config,
                    next_way_id(),
                    {"highway": "path", "bicycle": "designated", "surface": surface},
                    [[x0, y], [x1, y]],
                )
            )

    river_points = [
        [1000.0, 1200.0],
        [2200.0, 900.0],
        [4200.0, 1200.0],
        [6200.0, 2200.0],
        [7000.0, 4200.0],
        [6400.0, 6200.0],
        [4200.0, 7000.0],
        [2200.0, 6600.0],
        [900.0, 4800.0],
        [1000.0, 1200.0],
    ]
    for index, (first, second) in enumerate(zip(river_points, river_points[1:]), start=1):
        features.append(
            _corridor_feature(
                config,
                f"way/river-{index:02d}",
                {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"},
                [first, second],
            )
        )

    lake_points = [
        [6400.0, 700.0],
        [7000.0, 1600.0],
        [7300.0, 3000.0],
        [7200.0, 4700.0],
        [6800.0, 6100.0],
        [6200.0, 7300.0],
    ]
    for index, (first, second) in enumerate(zip(lake_points, lake_points[1:]), start=1):
        features.append(
            _corridor_feature(
                config,
                f"way/lake-{index:02d}",
                {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"},
                [first, second],
            )
        )

    for osm_way_id, geometry_m in [
        ("way/cross-01", [[800.0, 3600.0], [2400.0, 3600.0]]),
        ("way/cross-02", [[2400.0, 3600.0], [3200.0, 3600.0]]),
        ("way/cross-03", [[5200.0, 3600.0], [6400.0, 3600.0]]),
        ("way/cross-04", [[6400.0, 3600.0], [7200.0, 4700.0]]),
    ]:
        features.append(
            _corridor_feature(
                config,
                osm_way_id,
                {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"},
                geometry_m,
            )
        )

    features.append(_feature_from_gpx_track(config, OAKLEAF_TRACK_PATH, "way/oakleaf-fixture-01", 400.0, 700.0))
    features.append(_feature_from_gpx_track(config, SAMPLE_TRACK_PATH, "way/sample-track-01", 900.0, 4200.0))

    features.append(
        _corridor_feature(
            config,
            "way/bridge-3001",
            {
                "highway": "cycleway",
                "bicycle": "designated",
                "surface": "asphalt",
                "layer": "1",
                "bridge": "yes",
            },
            [[3200.0, 3600.0], [4200.0, 3600.0], [5200.0, 3600.0]],
        )
    )
    features.append(
        _corridor_feature(
            config,
            "way/tunnel-3002",
            {
                "highway": "cycleway",
                "bicycle": "designated",
                "surface": "asphalt",
                "layer": "-1",
                "tunnel": "yes",
            },
            [[4200.0, 2800.0], [4200.0, 3600.0], [4200.0, 4400.0]],
        )
    )

    features.append(
        _corridor_feature(
            config,
            next_way_id(),
            {"highway": "motorway", "surface": "asphalt"},
            [[400.0, 7600.0], [7600.0, 7600.0]],
        )
    )
    return features


def _tile_grid(config: dict[str, Any]) -> list[dict[str, Any]]:
    tile_size_m = float(config["tile_size_m"])
    width_tiles = int(round(float(config["world_bounds_m"][0]) / tile_size_m))
    height_tiles = int(round(float(config["world_bounds_m"][1]) / tile_size_m))
    return [
        {
            "tile_id": f"tile_x{x:02d}_y{y:02d}",
            "tile_x": x,
            "tile_y": y,
            "origin_m": [round(x * tile_size_m, 1), round(y * tile_size_m, 1)],
            "size_m": [round(tile_size_m, 1), round(tile_size_m, 1)],
        }
        for y in range(height_tiles)
        for x in range(width_tiles)
    ]


def _tile_id(point_m: list[float], config: dict[str, Any]) -> str:
    tile_size_m = float(config["tile_size_m"])
    width_tiles = int(round(float(config["world_bounds_m"][0]) / tile_size_m))
    height_tiles = int(round(float(config["world_bounds_m"][1]) / tile_size_m))
    x_index = min(width_tiles - 1, max(0, int(float(point_m[0]) // tile_size_m)))
    y_index = min(height_tiles - 1, max(0, int(float(point_m[1]) // tile_size_m)))
    return f"tile_x{x_index:02d}_y{y_index:02d}"


def _stream_region_id_for_tile(tile_x: int, tile_y: int, config: dict[str, Any]) -> str:
    span = int(round(float(config["streaming_region_size_m"]) / float(config["tile_size_m"])))
    return f"stream_x{tile_x // span:02d}_y{tile_y // span:02d}"


def _surface_class(tags: dict[str, str]) -> str:
    return "packed_gravel" if tags.get("surface") in {"compacted", "gravel"} else "asphalt"


def fetch_sources(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    raw_root = _mkdir(paths.raw)
    artifacts: list[dict[str, Any]] = []
    for source in _source_artifacts(config):
        receipt = {
            "source_id": source.source_id,
            "name": source.name,
            "fetch_url": source.fetch_url,
            "product_id": source.product_id,
            "version": source.version,
            "role": source.role,
            "license": source.license,
            "attribution": source.attribution,
            "retrieved_at": config["retrieved_at"],
            "region_id": config["region_id"],
            "bbox_wgs84": config["bbox_wgs84"],
            "optional": source.source_id in config.get("optional_source_ids", []),
        }
        source_dir = _mkdir(raw_root / source.source_id)
        receipt_path = source_dir / source.local_filename
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        artifacts.append(
            {
                "source_id": source.source_id,
                "name": source.name,
                "role": source.role,
                "fetch_url": source.fetch_url,
                "product_id": source.product_id,
                "version": source.version,
                "license": source.license,
                "attribution": source.attribution,
                "checksum_sha256": content_hash(receipt),
                "retrieved_at": config["retrieved_at"],
                "local_filename": str(receipt_path.relative_to(ROOT)),
                "optional": source.source_id in config.get("optional_source_ids", []),
            }
        )
    source_manifest = {
        "schema_version": "phase2-source-manifest-v1",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "generated_at": config["retrieved_at"],
        "artifacts": artifacts,
    }
    (raw_root / "source_manifest.json").write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return source_manifest


def prepare_sources(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    _mkdir(paths.staged)
    if not (paths.raw / "source_manifest.json").exists():
        fetch_sources(region_config)
    prepared = {
        "schema_version": "phase2-prepared-sources-v1",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "target_crs": config["target_crs"],
        "tile_size_m": config["tile_size_m"],
        "streaming_region_size_m": config["streaming_region_size_m"],
        "world_bounds_m": config["world_bounds_m"],
        "osm_features": _network_features(config),
        "build_warnings": [
            f"optional source {source_id} not required for Phase 2 bake; using deterministic fallback synthesis"
            for source_id in config.get("optional_source_ids", [])
        ],
    }
    (paths.staged / "prepared_sources.json").write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return prepared


def build_ride_graph(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    prepared_path = paths.staged / "prepared_sources.json"
    if not prepared_path.exists():
        prepare_sources(region_config)
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_lookup: dict[tuple[float, float, str], str] = {}

    bikeable_features = [feature for feature in prepared["osm_features"] if feature["tags"].get("highway") != "motorway"]
    for feature in bikeable_features:
        layer = str(feature["tags"].get("layer", "0"))
        for point_m, point_wgs84 in (
            (feature["geometry_m"][0], feature["geometry_wgs84"][0]),
            (feature["geometry_m"][-1], feature["geometry_wgs84"][-1]),
        ):
            key = (round(point_m[0], 3), round(point_m[1], 3), layer)
            if key in node_lookup:
                continue
            tile_id = _tile_id(point_m, config)
            tile_x = int(tile_id.split("_")[1][1:])
            tile_y = int(tile_id.split("_")[2][1:])
            node_id = f"milwaukee_phase2_node_{content_hash({'point_m': point_m, 'layer': layer})[:10]}"
            node_lookup[key] = node_id
            nodes.append(
                {
                    "node_id": node_id,
                    "point_wgs84": point_wgs84,
                    "point_m": point_m,
                    "junction_kind": "junction",
                    "layer": layer,
                    "tile_id": tile_id,
                    "stream_region_id": _stream_region_id_for_tile(tile_x, tile_y, config),
                }
            )

    for feature in bikeable_features:
        geometry_m = feature["geometry_m"]
        midpoint = geometry_m[len(geometry_m) // 2]
        tile_id = _tile_id(midpoint, config)
        tile_x = int(tile_id.split("_")[1][1:])
        tile_y = int(tile_id.split("_")[2][1:])
        layer = str(feature["tags"].get("layer", "0"))
        structure = "bridge" if feature["tags"].get("bridge") == "yes" else "underpass" if feature["tags"].get("tunnel") == "yes" else "surface"
        start_key = (round(geometry_m[0][0], 3), round(geometry_m[0][1], 3), layer)
        end_key = (round(geometry_m[-1][0], 3), round(geometry_m[-1][1], 3), layer)
        edges.append(
            {
                "edge_id": stable_edge_id(feature["osm_way_id"], geometry_m),
                "osm_way_id": feature["osm_way_id"],
                "start_node_id": node_lookup[start_key],
                "end_node_id": node_lookup[end_key],
                "bike_access": "designated",
                "surface": _surface_class(feature["tags"]),
                "length_m": _segment_length(geometry_m),
                "geometry_wgs84": feature["geometry_wgs84"],
                "geometry_m": geometry_m,
                "distance_profile_m": _distance_profile(geometry_m),
                "elevation_profile_m": feature["elevation_profile_m"],
                "layer": layer,
                "structure": structure,
                "tile_id": tile_id,
                "stream_region_id": _stream_region_id_for_tile(tile_x, tile_y, config),
            }
        )

    ride_graph = {
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "graph_profile": config["graph_profile"],
        "bbox_wgs84": config["bbox_wgs84"],
        "nodes": sorted(nodes, key=lambda item: item["node_id"]),
        "edges": sorted(edges, key=lambda item: item["edge_id"]),
    }
    _mkdir(paths.build)
    (paths.build / "ride_graph.json").write_text(json.dumps(ride_graph, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ride_graph


def _terrain_grid(origin_x: float, origin_y: float, size: float, samples: int = 5) -> list[list[float]]:
    step = size / float(samples - 1)
    grid: list[list[float]] = []
    for row in range(samples):
        grid.append([_sample_elevation([origin_x + (col * step), origin_y + (row * step)]) for col in range(samples)])
    return grid


def _biome_patch(tile: dict[str, Any]) -> dict[str, Any]:
    origin_x, origin_y = tile["origin_m"]
    landcover = "urban_parkland" if (tile["tile_x"] + tile["tile_y"]) % 2 == 0 else "shoreline"
    return {
        "biome_id": f"{tile['tile_id']}_biome",
        "landcover_class": landcover,
        "polygon_m": [
            [origin_x + 80.0, origin_y + 80.0],
            [origin_x + 920.0, origin_y + 110.0],
            [origin_x + 840.0, origin_y + 900.0],
            [origin_x + 120.0, origin_y + 860.0],
        ],
        "color_hint": "#6f9151" if landcover == "urban_parkland" else "#6aa7b8",
    }


def _tile_buildings(tile: dict[str, Any]) -> list[dict[str, Any]]:
    origin_x, origin_y = tile["origin_m"]
    return [
        {
            "building_id": f"{tile['tile_id']}_bldg_01",
            "footprint_m": [[origin_x + 180.0, origin_y + 180.0], [origin_x + 300.0, origin_y + 180.0], [origin_x + 300.0, origin_y + 320.0], [origin_x + 180.0, origin_y + 320.0]],
            "height_m": 10.0 + ((tile["tile_x"] + tile["tile_y"]) % 4) * 6.0,
            "kind": "midrise",
        },
        {
            "building_id": f"{tile['tile_id']}_bldg_02",
            "footprint_m": [[origin_x + 620.0, origin_y + 560.0], [origin_x + 780.0, origin_y + 560.0], [origin_x + 780.0, origin_y + 760.0], [origin_x + 620.0, origin_y + 760.0]],
            "height_m": 8.0 + ((tile["tile_x"] * 2 + tile["tile_y"]) % 5) * 5.0,
            "kind": "mixed_use",
        },
    ]


def _tile_prop_masks(tile: dict[str, Any]) -> list[dict[str, Any]]:
    origin_x, origin_y = tile["origin_m"]
    return [
        {
            "mask_id": f"{tile['tile_id']}_trees",
            "prop_class": "trees",
            "polygon_m": [[origin_x + 80.0, origin_y + 640.0], [origin_x + 400.0, origin_y + 600.0], [origin_x + 440.0, origin_y + 920.0], [origin_x + 120.0, origin_y + 940.0]],
            "density": 0.7,
        },
        {
            "mask_id": f"{tile['tile_id']}_shore",
            "prop_class": "shoreline_grass",
            "polygon_m": [[origin_x + 520.0, origin_y + 60.0], [origin_x + 940.0, origin_y + 100.0], [origin_x + 900.0, origin_y + 360.0], [origin_x + 540.0, origin_y + 300.0]],
            "density": 0.45,
        },
    ]


def build_scenery(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    ride_graph_path = paths.build / "ride_graph.json"
    prepared_path = paths.staged / "prepared_sources.json"
    if not ride_graph_path.exists():
        build_ride_graph(region_config)
    if not prepared_path.exists():
        prepare_sources(region_config)

    ride_graph = json.loads(ride_graph_path.read_text(encoding="utf-8"))
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    tiles = _tile_grid(config)
    tile_graph_map = {tile["tile_id"]: [] for tile in tiles}
    for edge in ride_graph["edges"]:
        tile_graph_map[edge["tile_id"]].append(edge)

    tile_root = _mkdir(paths.build / "tiles")
    scenery_index = {
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "tile_size_m": config["tile_size_m"],
        "streaming_region_size_m": config["streaming_region_size_m"],
        "tiles": [],
        "style_hints": {"vegetation_density": 0.64, "shoreline_emphasis": 0.58, "building_color_variation": 0.35},
        "build_warnings": prepared["build_warnings"],
    }

    for tile in tiles:
        tile_dir = _mkdir(tile_root / tile["tile_id"])
        road_segments = [
            {
                "edge_id": edge["edge_id"],
                "width_m": 4.0 if edge["surface"] == "packed_gravel" else 5.5,
                "material": edge["surface"],
                "structure": edge["structure"],
            }
            for edge in sorted(tile_graph_map[tile["tile_id"]], key=lambda item: item["edge_id"])
        ]
        scenery = {
            "region_id": config["region_id"],
            "corridor_id": config["corridor_id"],
            "region_version": config["region_version"],
            "terrain_chunks": [
                {
                    "chunk_id": f"{tile['tile_id']}_terrain",
                    "origin_m": tile["origin_m"],
                    "size_m": tile["size_m"],
                    "elevation_grid_m": _terrain_grid(tile["origin_m"][0], tile["origin_m"][1], tile["size_m"][0]),
                    "seam_keys": {
                        "north": f"north_{tile['tile_x']}_{tile['tile_y']}",
                        "south": f"south_{tile['tile_x']}_{tile['tile_y']}",
                        "east": f"east_{tile['tile_x']}_{tile['tile_y']}",
                        "west": f"west_{tile['tile_x']}_{tile['tile_y']}",
                    },
                }
            ],
            "road_segments": road_segments,
            "biome_patches": [_biome_patch(tile)],
            "style_hints": scenery_index["style_hints"],
            "buildings": _tile_buildings(tile),
            "prop_masks": _tile_prop_masks(tile),
        }
        tile_node_ids = {
            edge["start_node_id"]
            for edge in tile_graph_map[tile["tile_id"]]
        } | {
            edge["end_node_id"]
            for edge in tile_graph_map[tile["tile_id"]]
        }
        tile_graph = {
            "region_id": config["region_id"],
            "corridor_id": config["corridor_id"],
            "region_version": config["region_version"],
            "graph_profile": config["graph_profile"],
            "bbox_wgs84": config["bbox_wgs84"],
            "nodes": [node for node in ride_graph["nodes"] if node["node_id"] in tile_node_ids],
            "edges": sorted(tile_graph_map[tile["tile_id"]], key=lambda item: item["edge_id"]),
        }
        tile_manifest = {
            "schema_version": "phase2-region-tile-v1",
            "region_id": config["region_id"],
            "corridor_id": config["corridor_id"],
            "tile_id": tile["tile_id"],
            "bbox_wgs84": config["bbox_wgs84"],
            "region_version": config["region_version"],
            "source_versions": {artifact.source_id: artifact.version for artifact in _source_artifacts(config)},
            "compatible_clients": ["godot-phase2"],
            "ride_graph_asset": f"tiles/{tile['tile_id']}/ride_graph.json",
            "scenery_asset": f"tiles/{tile['tile_id']}/scenery.json",
            "route_definitions_asset": "routes.json",
            "attribution_asset": "attribution.json",
            "source_manifest_asset": "source_manifest.json",
        }
        (tile_dir / "manifest.json").write_text(json.dumps(tile_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (tile_dir / "ride_graph.json").write_text(json.dumps(tile_graph, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (tile_dir / "scenery.json").write_text(json.dumps(scenery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        scenery_index["tiles"].append(
            {
                "tile_id": tile["tile_id"],
                "origin_m": tile["origin_m"],
                "size_m": tile["size_m"],
                "stream_region_id": _stream_region_id_for_tile(tile["tile_x"], tile["tile_y"], config),
                "manifest_asset": f"tiles/{tile['tile_id']}/manifest.json",
            }
        )

    (paths.build / "scenery_index.json").write_text(json.dumps(scenery_index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return scenery_index


def _streaming_regions(config: dict[str, Any], scenery_index: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for tile in scenery_index["tiles"]:
        grouped.setdefault(tile["stream_region_id"], []).append(tile)
    tile_size_m = float(config["tile_size_m"])
    span = int(round(float(config["streaming_region_size_m"]) / tile_size_m))
    regions: list[dict[str, Any]] = []
    for stream_region_id, tiles in sorted(grouped.items()):
        tile_ids = sorted(tile["tile_id"] for tile in tiles)
        tile_x_values = [int(tile_id.split("_")[1][1:]) for tile_id in tile_ids]
        tile_y_values = [int(tile_id.split("_")[2][1:]) for tile_id in tile_ids]
        min_x = min(tile_x_values)
        min_y = min(tile_y_values)
        region_x = min_x // span
        region_y = min_y // span
        neighbors = []
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            candidate = f"stream_x{region_x + dx:02d}_y{region_y + dy:02d}"
            if candidate in grouped:
                neighbors.append(candidate)
        regions.append(
            {
                "stream_region_id": stream_region_id,
                "tile_ids": tile_ids,
                "origin_m": [round(min_x * tile_size_m, 1), round(min_y * tile_size_m, 1)],
                "size_m": [round(span * tile_size_m, 1), round(span * tile_size_m, 1)],
                "neighbor_region_ids": sorted(neighbors),
            }
        )
    return regions


def _starter_routes(ride_graph: dict[str, Any], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    edge_by_way = {edge["osm_way_id"]: edge for edge in ride_graph["edges"]}

    def build_route(route_id: str, display_name: str, difficulty: str, way_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
        edges = [edge_by_way[way_id] for way_id in way_ids]
        distance_profile_m: list[float] = []
        elevation_profile_m: list[float] = []
        surface_profile: list[str] = []
        distance_offset = 0.0
        for edge in edges:
            if not distance_profile_m:
                distance_profile_m.extend(edge["distance_profile_m"])
                elevation_profile_m.extend(edge["elevation_profile_m"])
            else:
                distance_profile_m.extend([round(distance_offset + value, 1) for value in edge["distance_profile_m"][1:]])
                elevation_profile_m.extend(edge["elevation_profile_m"][1:])
            distance_offset += edge["length_m"]
            surface_profile.append(edge["surface"])
        route = {
            "route_id": route_id,
            "source_type": "starter_route",
            "source_hash": f"starter:{content_hash({'route_id': route_id, 'ways': way_ids})}",
            "snapped_edge_sequence": [edge["edge_id"] for edge in edges],
            "elevation_profile_m": elevation_profile_m,
            "distance_profile_m": distance_profile_m,
            "grade_profile_pct": build_grade_profile(distance_profile_m, elevation_profile_m, int(config["deterministic_knobs"]["grade_smoothing_window"])),
            "surface_profile": surface_profile,
            "distance_m": round(distance_profile_m[-1], 1),
            "region_version": config["region_version"],
        }
        catalog = {
            "route_id": route_id,
            "display_name": display_name,
            "difficulty": difficulty,
            "start_area": "Milwaukee core trails",
            "distance_m": route["distance_m"],
            "elevation_gain_m": round(sum(max(0.0, elevation_profile_m[index] - elevation_profile_m[index - 1]) for index in range(1, len(elevation_profile_m))), 1),
            "preview_edge_id": route["snapped_edge_sequence"][0],
            "region_version": config["region_version"],
        }
        return route, catalog

    route_specs = [
        ("starter_cross_city", "Cross-City Connector", "moderate", ["way/cross-01", "way/cross-02", "way/bridge-3001", "way/cross-03", "way/cross-04", "way/lake-04", "way/lake-05"]),
        ("starter_lakefront_spin", "Lakefront Spin", "easy", ["way/lake-01", "way/lake-02", "way/lake-03", "way/lake-04", "way/lake-05"]),
        ("starter_river_loop", "River Loop", "moderate", ["way/river-01", "way/river-02", "way/river-03", "way/river-04", "way/river-05", "way/river-06", "way/river-07", "way/river-08", "way/river-09"]),
        ("starter_wauwatosa_lakefront", "Wauwatosa to Lakefront", "moderate", ["way/sample-track-01"]),
    ]
    routes: list[dict[str, Any]] = []
    catalog_entries: list[dict[str, Any]] = []
    for route_id, name, difficulty, way_ids in route_specs:
        route, catalog = build_route(route_id, name, difficulty, way_ids)
        routes.append(route)
        catalog_entries.append(catalog)
    return sorted(routes, key=lambda item: item["route_id"]), sorted(catalog_entries, key=lambda item: item["route_id"])


def _root_manifest(config: dict[str, Any], scenery_index: dict[str, Any], starter_route_ids: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "phase2-region-root-v1",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "bbox_wgs84": config["bbox_wgs84"],
        "source_versions": {artifact.source_id: artifact.version for artifact in _source_artifacts(config)},
        "compatible_clients": ["godot-phase2"],
        "tile_size_m": config["tile_size_m"],
        "streaming_region_size_m": config["streaming_region_size_m"],
        "ride_graph_asset": "ride_graph.json",
        "route_catalog_asset": "route_catalog.json",
        "route_definitions_asset": "routes.json",
        "streaming_regions_asset": "streaming_regions.json",
        "scenery_index_asset": "scenery_index.json",
        "attribution_asset": "attribution.json",
        "source_manifest_asset": "source_manifest.json",
        "build_warnings": scenery_index["build_warnings"],
        "starter_route_ids": starter_route_ids,
    }


def _attribution(config: dict[str, Any], source_manifest: dict[str, Any], root_manifest: dict[str, Any], ride_graph: dict[str, Any], routes: list[dict[str, Any]], streaming_regions: list[dict[str, Any]], scenery_index: dict[str, Any]) -> dict[str, Any]:
    attribution = {
        "region_id": config["region_id"],
        "region_version": config["region_version"],
        "build_date": config["build_date"],
        "region_hash": "<pending>",
        "sources": [
            {
                "source_id": artifact["source_id"],
                "name": artifact["name"],
                "license": artifact["license"],
                "version": artifact["version"],
                "used_for": [artifact["role"]],
                "attribution": artifact["attribution"],
            }
            for artifact in source_manifest["artifacts"]
        ],
        "notices": [
            "This Milwaukee Phase 2 pack contains a deterministic, streamed region bake for local open-source gameplay validation.",
            "ODbL-sensitive ride graph outputs retain attribution and provenance requirements on redistribution.",
            "Optional preprocessing sources may degrade scenery richness, but route graph and gameplay remain valid.",
        ],
    }
    attribution["region_hash"] = content_hash(
        {
            "root_manifest": root_manifest,
            "ride_graph": ride_graph,
            "routes": routes,
            "streaming_regions": streaming_regions,
            "scenery_index": scenery_index,
            "source_manifest": source_manifest,
            "attribution": {**attribution, "region_hash": "<computed>"},
        }
    )
    return attribution


def package_region(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    ride_graph = build_ride_graph(region_config)
    scenery_index = build_scenery(region_config)
    raw_manifest_path = paths.raw / "source_manifest.json"
    if not raw_manifest_path.exists():
        fetch_sources(region_config)
    source_manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
    routes, route_catalog = _starter_routes(ride_graph, config)
    streaming_regions = _streaming_regions(config, scenery_index)
    root_manifest = _root_manifest(config, scenery_index, [entry["route_id"] for entry in route_catalog])
    attribution = _attribution(config, source_manifest, root_manifest, ride_graph, routes, streaming_regions, scenery_index)

    build_package_dir = _mkdir(paths.build / "package")
    files = {
        "region_manifest.json": root_manifest,
        "ride_graph.json": ride_graph,
        "routes.json": routes,
        "route_catalog.json": route_catalog,
        "streaming_regions.json": streaming_regions,
        "scenery_index.json": scenery_index,
        "attribution.json": attribution,
        "source_manifest.json": source_manifest,
    }
    for filename, payload in files.items():
        (build_package_dir / filename).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if paths.package.exists():
        shutil.rmtree(paths.package)
    paths.package.mkdir(parents=True, exist_ok=True)
    for filename in files:
        shutil.copy2(build_package_dir / filename, paths.package / filename)
    shutil.copytree(paths.build / "tiles", paths.package / "tiles")

    return {
        "root_manifest": root_manifest,
        "ride_graph": ride_graph,
        "routes": routes,
        "route_catalog": route_catalog,
        "streaming_regions": streaming_regions,
        "scenery_index": scenery_index,
        "attribution": attribution,
        "source_manifest": source_manifest,
    }


def build_phase2_region(region_config: str | Path) -> dict[str, Any]:
    fetch_sources(region_config)
    prepare_sources(region_config)
    build_ride_graph(region_config)
    build_scenery(region_config)
    return package_region(region_config)


def route_from_gpx_phase2(path: Path, graph: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    active_config = load_region_config(DEFAULT_REGION_CONFIG) if config is None else config
    return route_from_gpx(path, graph, active_config)
