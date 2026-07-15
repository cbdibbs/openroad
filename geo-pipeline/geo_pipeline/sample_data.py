from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any
import json
import math

from geo_pipeline.determinism import region_pack_hash
from geo_pipeline.gpx import GpxPoint, gpx_source_hash, load_gpx_points


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_demo_region_pack"
DEFAULT_GPX_PATH = ROOT / "region-data" / "milwaukee" / "oak_leaf_demo_loop.gpx"


def _segment_length(points: list[list[float]]) -> float:
    total = 0.0
    for first, second in zip(points, points[1:]):
        total += math.dist(first, second)
    return round(total, 1)


def sample_ride_graph() -> dict[str, Any]:
    nodes = [
        {
            "node_id": "milwaukee_node_0001",
            "point_wgs84": [-87.9852, 43.0275],
            "point_m": [0.0, 0.0],
            "junction_kind": "start_finish",
        },
        {
            "node_id": "milwaukee_node_0002",
            "point_wgs84": [-87.9680, 43.0316],
            "point_m": [1400.0, 400.0],
            "junction_kind": "trail_split",
        },
        {
            "node_id": "milwaukee_node_0003",
            "point_wgs84": [-87.9508, 43.0458],
            "point_m": [2800.0, 1600.0],
            "junction_kind": "lookout",
        },
        {
            "node_id": "milwaukee_node_0004",
            "point_wgs84": [-87.9368, 43.0621],
            "point_m": [4000.0, 3000.0],
            "junction_kind": "bridge_entry",
        },
        {
            "node_id": "milwaukee_node_0005",
            "point_wgs84": [-87.9565, 43.0550],
            "point_m": [2300.0, 2400.0],
            "junction_kind": "park_gate",
        },
    ]

    edges = [
        {
            "edge_id": "osm_edge_1001",
            "osm_way_id": "way/1001",
            "start_node_id": "milwaukee_node_0001",
            "end_node_id": "milwaukee_node_0002",
            "bike_access": "designated",
            "surface": "asphalt",
            "geometry_wgs84": [
                [-87.9852, 43.0275],
                [-87.9778, 43.0288],
                [-87.9680, 43.0316],
            ],
            "geometry_m": [[0.0, 0.0], [650.0, 120.0], [1400.0, 400.0]],
            "elevation_profile_m": [188.2, 188.7, 189.1],
        },
        {
            "edge_id": "osm_edge_1002",
            "osm_way_id": "way/1002",
            "start_node_id": "milwaukee_node_0002",
            "end_node_id": "milwaukee_node_0003",
            "bike_access": "designated",
            "surface": "asphalt",
            "geometry_wgs84": [
                [-87.9680, 43.0316],
                [-87.9602, 43.0382],
                [-87.9508, 43.0458],
            ],
            "geometry_m": [[1400.0, 400.0], [2050.0, 950.0], [2800.0, 1600.0]],
            "elevation_profile_m": [189.1, 190.0, 191.0],
        },
        {
            "edge_id": "osm_edge_1008",
            "osm_way_id": "way/1008",
            "start_node_id": "milwaukee_node_0003",
            "end_node_id": "milwaukee_node_0004",
            "bike_access": "designated",
            "surface": "packed_gravel",
            "geometry_wgs84": [
                [-87.9508, 43.0458],
                [-87.9448, 43.0532],
                [-87.9368, 43.0621],
            ],
            "geometry_m": [[2800.0, 1600.0], [3325.0, 2250.0], [4000.0, 3000.0]],
            "elevation_profile_m": [191.0, 190.3, 189.9],
        },
        {
            "edge_id": "osm_edge_1015",
            "osm_way_id": "way/1015",
            "start_node_id": "milwaukee_node_0004",
            "end_node_id": "milwaukee_node_0001",
            "bike_access": "designated",
            "surface": "asphalt",
            "geometry_wgs84": [
                [-87.9368, 43.0621],
                [-87.9565, 43.0550],
                [-87.9718, 43.0440],
                [-87.9852, 43.0275],
            ],
            "geometry_m": [[4000.0, 3000.0], [2300.0, 2400.0], [1200.0, 1450.0], [0.0, 0.0]],
            "elevation_profile_m": [189.9, 189.0, 188.1, 187.5],
        },
    ]

    for edge in edges:
        edge["length_m"] = _segment_length(edge["geometry_m"])

    return {
        "region_id": "milwaukee_demo",
        "corridor_id": "oak_leaf_demo",
        "region_version": "milwaukee-v1.0.0",
        "graph_profile": "phase1-corridor-v1",
        "bbox_wgs84": [-87.9852, 43.0275, -87.9368, 43.0621],
        "nodes": nodes,
        "edges": edges,
    }


def sample_scenery_pack() -> dict[str, Any]:
    return {
        "region_id": "milwaukee_demo",
        "corridor_id": "oak_leaf_demo",
        "region_version": "milwaukee-v1.0.0",
        "terrain_chunks": [
            {
                "chunk_id": "terrain_chunk_0001",
                "origin_m": [0.0, 0.0],
                "size_m": [4200.0, 3200.0],
                "elevation_grid_m": [
                    [187.9, 188.8, 189.7],
                    [188.4, 189.9, 190.6],
                    [188.1, 189.4, 189.8],
                ],
            }
        ],
        "road_segments": [
            {"edge_id": "osm_edge_1001", "width_m": 5.0, "material": "asphalt"},
            {"edge_id": "osm_edge_1002", "width_m": 5.0, "material": "asphalt"},
            {"edge_id": "osm_edge_1008", "width_m": 4.0, "material": "packed_gravel"},
            {"edge_id": "osm_edge_1015", "width_m": 5.0, "material": "asphalt"},
        ],
        "biome_patches": [
            {
                "biome_id": "parkland_001",
                "landcover_class": "urban_parkland",
                "polygon_m": [[250.0, 250.0], [1700.0, 250.0], [1500.0, 1200.0], [300.0, 1000.0]],
                "color_hint": "#77a35f",
            },
            {
                "biome_id": "waterside_001",
                "landcover_class": "shoreline",
                "polygon_m": [[2400.0, 1200.0], [3900.0, 1600.0], [3600.0, 2850.0], [2200.0, 2200.0]],
                "color_hint": "#7fb8c9",
            },
        ],
    }


def sample_attribution_pack() -> dict[str, Any]:
    return {
        "region_id": "milwaukee_demo",
        "region_version": "milwaukee-v1.0.0",
        "build_date": "2026-07-14",
        "region_hash": "<pending>",
        "sources": [
            {
                "name": "OpenStreetMap",
                "license": "ODbL 1.0",
                "version": "planet extract 2026-07-01",
                "used_for": ["ride_graph", "road_geometry"],
                "attribution": "Copyright OpenStreetMap contributors",
            },
            {
                "name": "USGS 3DEP",
                "license": "USGS public use guidance",
                "version": "1m DEM 2025-11-15",
                "used_for": ["terrain", "route_elevation"],
                "attribution": "Source: U.S. Geological Survey",
            },
            {
                "name": "USDA NAIP",
                "license": "public use with requested credit",
                "version": "2024 collection",
                "used_for": ["imagery_heuristics"],
                "attribution": "USDA Farm Production and Conservation - Aerial Photography Field Office",
            },
            {
                "name": "ESA WorldCover",
                "license": "CC BY 4.0",
                "version": "v200",
                "used_for": ["biome_masks", "landcover_classes"],
                "attribution": "Contains modified Copernicus WorldCover data (2021) processed by ESA WorldCover consortium",
            },
        ],
        "notices": [
            "This region pack contains a deterministic Milwaukee corridor proof for local validation and client integration.",
            "ODbL-sensitive ride graph outputs must retain attribution and provenance when redistributed.",
        ],
    }


def sample_manifest() -> dict[str, Any]:
    return {
        "schema_version": "phase1-region-pack-v1",
        "region_id": "milwaukee_demo",
        "corridor_id": "oak_leaf_demo",
        "tile_id": "milwaukee_demo_4km_0001",
        "bbox_wgs84": [-87.9852, 43.0275, -87.9368, 43.0621],
        "region_version": "milwaukee-v1.0.0",
        "source_versions": {
            "openstreetmap": "planet extract 2026-07-01",
            "usgs_3dep": "1m DEM 2025-11-15",
            "usda_naip": "2024 collection",
            "esa_worldcover": "v200",
        },
        "compatible_clients": ["godot-phase1"],
        "ride_graph_asset": "ride_graph.json",
        "scenery_asset": "scenery.json",
        "route_definitions_asset": "routes.json",
        "attribution_asset": "attribution.json",
    }


def _distance_to_segment(point: GpxPoint, first: list[float], second: list[float]) -> float:
    px = point.longitude
    py = point.latitude
    ax, ay = first
    bx, by = second
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.dist([px, py], [ax, ay])
    t = ((px - ax) * dx + (py - ay) * dy) / ((dx * dx) + (dy * dy))
    t = max(0.0, min(1.0, t))
    nearest = [ax + (t * dx), ay + (t * dy)]
    return math.dist([px, py], nearest)


def _edge_distance(point: GpxPoint, edge: dict[str, Any]) -> float:
    geometry = edge["geometry_wgs84"]
    return min(
        _distance_to_segment(point, first, second)
        for first, second in zip(geometry, geometry[1:])
    )


def _adjacent_edges(graph: dict[str, Any]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        edge_id = edge["edge_id"]
        adjacency.setdefault(edge_id, set())
        for other in graph["edges"]:
            other_edge_id = other["edge_id"]
            if edge_id == other_edge_id:
                continue
            if {
                edge["start_node_id"],
                edge["end_node_id"],
            } & {other["start_node_id"], other["end_node_id"]}:
                adjacency[edge_id].add(other_edge_id)
    return adjacency


def _find_bridge_path(graph: dict[str, Any], start_edge_id: str, end_edge_id: str) -> list[str]:
    if start_edge_id == end_edge_id:
        return [start_edge_id]

    adjacency = _adjacent_edges(graph)
    queue: deque[tuple[str, list[str]]] = deque([(start_edge_id, [start_edge_id])])
    visited = {start_edge_id}

    while queue:
        current, path = queue.popleft()
        for neighbor in sorted(adjacency.get(current, set())):
            if neighbor in visited:
                continue
            next_path = path + [neighbor]
            if neighbor == end_edge_id:
                return next_path
            visited.add(neighbor)
            queue.append((neighbor, next_path))

    raise ValueError(f"No connected path from {start_edge_id} to {end_edge_id}")


def snap_points_to_graph(points: list[GpxPoint], graph: dict[str, Any]) -> dict[str, Any]:
    nearest_edge_ids: list[str] = []
    for point in points:
        matched = min(
            graph["edges"],
            key=lambda edge: (_edge_distance(point, edge), edge["edge_id"]),
        )
        if not nearest_edge_ids or nearest_edge_ids[-1] != matched["edge_id"]:
            nearest_edge_ids.append(matched["edge_id"])

    snapped_edge_sequence: list[str] = []
    for edge_id in nearest_edge_ids:
        if not snapped_edge_sequence:
            snapped_edge_sequence.append(edge_id)
            continue
        if snapped_edge_sequence[-1] == edge_id:
            continue
        bridge = _find_bridge_path(graph, snapped_edge_sequence[-1], edge_id)
        snapped_edge_sequence.extend(bridge[1:])

    if len(snapped_edge_sequence) > 1 and snapped_edge_sequence[0] == snapped_edge_sequence[-1]:
        snapped_edge_sequence.pop()

    edge_lookup = {edge["edge_id"]: edge for edge in graph["edges"]}
    elevation_profile_m: list[float] = []
    surface_profile: list[str] = []
    distance_m = 0.0

    for edge_id in snapped_edge_sequence:
        edge = edge_lookup[edge_id]
        segment_elevation = edge["elevation_profile_m"]
        if not elevation_profile_m:
            elevation_profile_m.extend(segment_elevation)
        else:
            elevation_profile_m.extend(segment_elevation[1:])
        surface_profile.append(edge["surface"])
        distance_m += edge["length_m"]

    return {
        "snapped_edge_sequence": snapped_edge_sequence,
        "elevation_profile_m": elevation_profile_m,
        "surface_profile": surface_profile,
        "distance_m": round(distance_m, 1),
    }


def route_from_gpx(path: Path, graph: dict[str, Any]) -> dict[str, Any]:
    points = load_gpx_points(path)
    snapped = snap_points_to_graph(points, graph)
    return {
        "route_id": path.stem,
        "source_type": "gpx_import",
        "source_hash": gpx_source_hash(points),
        "snapped_edge_sequence": snapped["snapped_edge_sequence"],
        "elevation_profile_m": snapped["elevation_profile_m"],
        "surface_profile": snapped["surface_profile"],
        "distance_m": snapped["distance_m"],
        "region_version": graph["region_version"],
    }


def build_sample_region_pack(output_dir: Path, gpx_path: Path = DEFAULT_GPX_PATH) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = sample_manifest()
    ride_graph = sample_ride_graph()
    scenery = sample_scenery_pack()
    routes = [route_from_gpx(gpx_path, ride_graph)]
    attribution = sample_attribution_pack()
    attribution["region_hash"] = region_pack_hash(manifest, ride_graph, scenery, routes, attribution)

    files = {
        manifest["ride_graph_asset"]: ride_graph,
        manifest["scenery_asset"]: scenery,
        manifest["route_definitions_asset"]: routes,
        manifest["attribution_asset"]: attribution,
        "manifest.json": manifest,
    }

    for filename, payload in files.items():
        path = output_dir / filename
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "manifest": manifest,
        "ride_graph": ride_graph,
        "scenery": scenery,
        "routes": routes,
        "attribution": attribution,
    }
