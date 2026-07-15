from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import math
import shutil

from geo_pipeline.determinism import content_hash, region_pack_hash
from geo_pipeline.gpx import GpxPoint, gpx_source_hash, load_gpx_points


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(__file__).resolve().parent / "configs"
WORK_ROOT = ROOT / "work"
DEFAULT_REGION_CONFIG = "milwaukee_phase1"
DEFAULT_REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_demo_region_pack"
DEFAULT_GPX_PATH = ROOT / "region-data" / "milwaukee" / "oak_leaf_demo_loop.gpx"


@dataclass(frozen=True)
class SourceArtifact:
    source_id: str
    name: str
    fetch_url: str
    product_id: str
    version: str
    role: str
    license: str
    attribution: str
    local_filename: str


def load_region_config(region_config: str | Path) -> dict[str, Any]:
    candidate = Path(region_config)
    if candidate.suffix == ".json":
        config_path = candidate
    else:
        config_path = CONFIG_DIR / f"{region_config}.json"
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["_config_path"] = str(config_path)
    return config


def work_paths(config: dict[str, Any]) -> dict[str, Path]:
    work = config["work_dirs"]
    return {
        "raw": ROOT / work["raw"],
        "staged": ROOT / work["staged"],
        "build": ROOT / work["build"],
        "package": ROOT / config["package_dir"],
    }


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _round_point(point: list[float]) -> list[float]:
    return [round(point[0], 3), round(point[1], 3)]


def _segment_length(points: list[list[float]]) -> float:
    total = 0.0
    for first, second in zip(points, points[1:]):
        total += math.dist(first, second)
    return round(total, 1)


def _distance_profile(points: list[list[float]]) -> list[float]:
    values = [0.0]
    total = 0.0
    for first, second in zip(points, points[1:]):
        total += math.dist(first, second)
        values.append(round(total, 1))
    return values


def _smooth_series(values: list[float], window: int) -> list[float]:
    if window <= 1 or len(values) <= 2:
        return [round(value, 3) for value in values]
    radius = max(1, window // 2)
    smoothed: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        window_values = values[start:end]
        smoothed.append(round(sum(window_values) / len(window_values), 3))
    return smoothed


def build_grade_profile(
    distance_profile_m: list[float], elevation_profile_m: list[float], smoothing_window: int
) -> list[float]:
    raw = [0.0]
    for index in range(1, len(distance_profile_m)):
        delta_distance = distance_profile_m[index] - distance_profile_m[index - 1]
        delta_elevation = elevation_profile_m[index] - elevation_profile_m[index - 1]
        if delta_distance <= 0:
            raw.append(raw[-1])
            continue
        raw.append((delta_elevation / delta_distance) * 100.0)
    return _smooth_series(raw, smoothing_window)


def _wgs84_distance_m(first: list[float], second: list[float]) -> float:
    mean_lat = math.radians((first[1] + second[1]) / 2.0)
    meters_per_degree_lon = 111_320.0 * math.cos(mean_lat)
    meters_per_degree_lat = 110_540.0
    delta_lon = (second[0] - first[0]) * meters_per_degree_lon
    delta_lat = (second[1] - first[1]) * meters_per_degree_lat
    return math.hypot(delta_lon, delta_lat)


def _distance_to_segment_m(point: GpxPoint, first: list[float], second: list[float]) -> float:
    px = point.longitude
    py = point.latitude
    ax, ay = first
    bx, by = second
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return _wgs84_distance_m([px, py], [ax, ay])
    t = ((px - ax) * dx + (py - ay) * dy) / ((dx * dx) + (dy * dy))
    t = max(0.0, min(1.0, t))
    nearest = [ax + (t * dx), ay + (t * dy)]
    return _wgs84_distance_m([px, py], nearest)


def _edge_distance_m(point: GpxPoint, edge: dict[str, Any]) -> float:
    geometry = edge["geometry_wgs84"]
    return min(_distance_to_segment_m(point, first, second) for first, second in zip(geometry, geometry[1:]))


def bike_access_for_tags(tags: dict[str, str]) -> str | None:
    highway = tags.get("highway", "")
    bicycle = tags.get("bicycle", "")
    access = tags.get("access", "")
    footway = tags.get("footway", "")
    service = tags.get("service", "")

    if access in {"no", "private"} or bicycle == "no":
        return None
    if highway in {"motorway", "motorway_link", "trunk"}:
        return None
    if highway == "footway" and bicycle not in {"designated", "yes"} and footway != "shared":
        return None
    if highway == "service" and service == "driveway":
        return None
    if bicycle == "designated":
        return "designated"
    if highway in {"cycleway", "path", "living_street", "residential", "tertiary"}:
        return bicycle or "permitted"
    return None


def stable_edge_id(osm_way_id: str, geometry_m: list[list[float]]) -> str:
    fingerprint = {
        "osm_way_id": osm_way_id,
        "geometry_m": [_round_point(point) for point in geometry_m],
    }
    return f"osm_edge_{content_hash(fingerprint)[:8]}"


def _source_artifacts(config: dict[str, Any]) -> list[SourceArtifact]:
    sources = config["sources"]
    return [
        SourceArtifact(
            source_id="openstreetmap",
            name="OpenStreetMap",
            fetch_url=sources["openstreetmap"]["fetch_url"],
            product_id=sources["openstreetmap"]["product_id"],
            version=sources["openstreetmap"]["version"],
            role="ride_graph",
            license="ODbL 1.0",
            attribution="Copyright OpenStreetMap contributors",
            local_filename="wisconsin-latest.osm.pbf.receipt.json",
        ),
        SourceArtifact(
            source_id="usgs_3dep",
            name="USGS 3DEP",
            fetch_url=sources["usgs_3dep"]["fetch_url"],
            product_id=sources["usgs_3dep"]["product_id"],
            version=sources["usgs_3dep"]["version"],
            role="terrain_dem",
            license="USGS public use guidance",
            attribution="Source: U.S. Geological Survey",
            local_filename="milwaukee-3dep-dem.receipt.json",
        ),
        SourceArtifact(
            source_id="usda_naip",
            name="USDA NAIP",
            fetch_url=sources["usda_naip"]["fetch_url"],
            product_id=sources["usda_naip"]["product_id"],
            version=sources["usda_naip"]["version"],
            role="style_hints",
            license="public use with requested credit",
            attribution="USDA Farm Production and Conservation - Aerial Photography Field Office",
            local_filename="milwaukee-naip.receipt.json",
        ),
        SourceArtifact(
            source_id="esa_worldcover",
            name="ESA WorldCover",
            fetch_url=sources["esa_worldcover"]["fetch_url"],
            product_id=sources["esa_worldcover"]["product_id"],
            version=sources["esa_worldcover"]["version"],
            role="biome_masks",
            license="CC BY 4.0",
            attribution="Contains modified Copernicus WorldCover data (2021) processed by ESA WorldCover consortium",
            local_filename="milwaukee-worldcover.receipt.json",
        ),
    ]


def fetch_sources(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    raw_root = _mkdir(paths["raw"])
    fixed_retrieved_at = config["retrieved_at"]

    artifacts: list[dict[str, Any]] = []
    for source in _source_artifacts(config):
        source_dir = _mkdir(raw_root / source.source_id)
        receipt = {
            "source_id": source.source_id,
            "name": source.name,
            "fetch_url": source.fetch_url,
            "product_id": source.product_id,
            "version": source.version,
            "role": source.role,
            "license": source.license,
            "attribution": source.attribution,
            "retrieved_at": fixed_retrieved_at,
            "corridor_id": config["corridor_id"],
            "bbox_wgs84": config["bbox_wgs84"],
        }
        receipt_path = source_dir / source.local_filename
        receipt_bytes = json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        receipt_path.write_bytes(receipt_bytes)
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
                "retrieved_at": fixed_retrieved_at,
                "local_filename": str(receipt_path.relative_to(ROOT)),
            }
        )

    source_manifest = {
        "schema_version": "phase1-source-manifest-v1",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "generated_at": fixed_retrieved_at,
        "artifacts": artifacts,
    }
    source_manifest_path = raw_root / "source_manifest.json"
    source_manifest_path.write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return source_manifest


def _base_corridor_features() -> list[dict[str, Any]]:
    return [
        {
            "osm_way_id": "way/1001",
            "tags": {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"},
            "geometry_wgs84": [[-87.9852, 43.0275], [-87.9778, 43.0288], [-87.9680, 43.0316]],
            "geometry_m": [[0.0, 0.0], [650.0, 120.0], [1400.0, 400.0]],
            "elevation_profile_m": [188.2, 188.7, 189.1],
        },
        {
            "osm_way_id": "way/1002",
            "tags": {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"},
            "geometry_wgs84": [[-87.9680, 43.0316], [-87.9602, 43.0382], [-87.9508, 43.0458]],
            "geometry_m": [[1400.0, 400.0], [2050.0, 950.0], [2800.0, 1600.0]],
            "elevation_profile_m": [189.1, 190.0, 191.0],
        },
        {
            "osm_way_id": "way/1008",
            "tags": {"highway": "path", "bicycle": "designated", "surface": "compacted"},
            "geometry_wgs84": [[-87.9508, 43.0458], [-87.9448, 43.0532], [-87.9368, 43.0621]],
            "geometry_m": [[2800.0, 1600.0], [3325.0, 2250.0], [4000.0, 3000.0]],
            "elevation_profile_m": [191.0, 190.3, 189.9],
        },
        {
            "osm_way_id": "way/1015",
            "tags": {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"},
            "geometry_wgs84": [[-87.9368, 43.0621], [-87.9565, 43.0550], [-87.9718, 43.0440], [-87.9852, 43.0275]],
            "geometry_m": [[4000.0, 3000.0], [2300.0, 2400.0], [1200.0, 1450.0], [0.0, 0.0]],
            "elevation_profile_m": [189.9, 189.0, 188.1, 187.5],
        },
        {
            "osm_way_id": "way/1099",
            "tags": {"highway": "footway", "bicycle": "no", "surface": "paved"},
            "geometry_wgs84": [[-87.9720, 43.0405], [-87.9700, 43.0412]],
            "geometry_m": [[1900.0, 1100.0], [2050.0, 1160.0]],
            "elevation_profile_m": [189.8, 189.9],
        },
    ]


def prepare_sources(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    raw_manifest_path = paths["raw"] / "source_manifest.json"
    if not raw_manifest_path.exists():
        fetch_sources(region_config)
    _mkdir(paths["staged"])
    prepared = {
        "schema_version": "phase1-prepared-sources-v1",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "target_crs": config["target_crs"],
        "osm_features": _base_corridor_features(),
        "terrain_grid_m": [
            [187.9, 188.8, 189.7, 190.0],
            [188.4, 189.9, 190.6, 190.2],
            [188.1, 189.4, 189.8, 189.4],
            [187.8, 188.7, 189.2, 189.0],
        ],
        "worldcover_polygons": [
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
        "naip_style_hints": {
            "vegetation_density": 0.67,
            "shoreline_emphasis": 0.55,
        },
    }
    prepared_path = paths["staged"] / "prepared_sources.json"
    prepared_path.write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return prepared


def build_ride_graph(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    prepared_path = paths["staged"] / "prepared_sources.json"
    if not prepared_path.exists():
        prepare_sources(region_config)
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    features = prepared["osm_features"]

    bikeable_features = []
    for feature in features:
        bike_access = bike_access_for_tags(feature["tags"])
        if bike_access is None:
            continue
        surface = feature["tags"].get("surface", "asphalt")
        if surface in {"compacted", "gravel"}:
            surface = "packed_gravel"
        bikeable_features.append(
            {
                **feature,
                "bike_access": bike_access,
                "surface": surface,
            }
        )

    endpoint_counts: dict[tuple[float, float], int] = {}
    for feature in bikeable_features:
        for endpoint in (tuple(feature["geometry_m"][0]), tuple(feature["geometry_m"][-1])):
            endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1

    nodes: list[dict[str, Any]] = []
    node_lookup: dict[tuple[float, float], str] = {}
    for feature in bikeable_features:
        for point_m, point_wgs84 in (
            (feature["geometry_m"][0], feature["geometry_wgs84"][0]),
            (feature["geometry_m"][-1], feature["geometry_wgs84"][-1]),
        ):
            key = tuple(point_m)
            if key in node_lookup:
                continue
            node_id = f"milwaukee_node_{content_hash({'point_m': _round_point(point_m)})[:8]}"
            node_lookup[key] = node_id
            count = endpoint_counts[key]
            junction_kind = "junction" if count > 1 else "corridor_anchor"
            nodes.append(
                {
                    "node_id": node_id,
                    "point_wgs84": point_wgs84,
                    "point_m": point_m,
                    "junction_kind": junction_kind,
                }
            )

    edges: list[dict[str, Any]] = []
    for feature in bikeable_features:
        geometry_m = feature["geometry_m"]
        edge_id = stable_edge_id(feature["osm_way_id"], geometry_m)
        edges.append(
            {
                "edge_id": edge_id,
                "osm_way_id": feature["osm_way_id"],
                "start_node_id": node_lookup[tuple(geometry_m[0])],
                "end_node_id": node_lookup[tuple(geometry_m[-1])],
                "bike_access": feature["bike_access"],
                "surface": feature["surface"],
                "length_m": _segment_length(geometry_m),
                "geometry_wgs84": feature["geometry_wgs84"],
                "geometry_m": geometry_m,
                "distance_profile_m": _distance_profile(geometry_m),
                "elevation_profile_m": feature["elevation_profile_m"],
            }
        )

    ride_graph = {
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "graph_profile": config["graph_profile"],
        "bbox_wgs84": config["bbox_wgs84"],
        "nodes": sorted(nodes, key=lambda node: node["node_id"]),
        "edges": sorted(edges, key=lambda edge: edge["edge_id"]),
    }
    _mkdir(paths["build"])
    (paths["build"] / "ride_graph.json").write_text(json.dumps(ride_graph, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ride_graph


def build_scenery(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    prepared_path = paths["staged"] / "prepared_sources.json"
    ride_graph_path = paths["build"] / "ride_graph.json"
    if not prepared_path.exists():
        prepare_sources(region_config)
    if not ride_graph_path.exists():
        build_ride_graph(region_config)
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    ride_graph = json.loads(ride_graph_path.read_text(encoding="utf-8"))

    scenery = {
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "terrain_chunks": [
            {
                "chunk_id": "terrain_chunk_0001",
                "origin_m": [0.0, 0.0],
                "size_m": [4200.0, 3200.0],
                "elevation_grid_m": prepared["terrain_grid_m"],
            }
        ],
        "road_segments": [
            {
                "edge_id": edge["edge_id"],
                "width_m": 4.0 if edge["surface"] == "packed_gravel" else 5.0,
                "material": edge["surface"],
            }
            for edge in ride_graph["edges"]
        ],
        "biome_patches": prepared["worldcover_polygons"],
        "style_hints": prepared["naip_style_hints"],
    }
    (paths["build"] / "scenery.json").write_text(json.dumps(scenery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return scenery


def _adjacent_edges(graph: dict[str, Any]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        edge_id = edge["edge_id"]
        adjacency.setdefault(edge_id, set())
        for other in graph["edges"]:
            other_edge_id = other["edge_id"]
            if edge_id == other_edge_id:
                continue
            if {edge["start_node_id"], edge["end_node_id"]} & {other["start_node_id"], other["end_node_id"]}:
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


def snap_points_to_graph(points: list[GpxPoint], graph: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    nearest_edge_ids: list[str] = []
    matched_points = 0
    threshold_m = float(config["deterministic_knobs"]["max_snap_distance_m"])

    for point in points:
        matched = min(graph["edges"], key=lambda edge: (_edge_distance_m(point, edge), edge["edge_id"]))
        distance_m = _edge_distance_m(point, matched)
        if distance_m <= threshold_m:
            matched_points += 1
        if not nearest_edge_ids or nearest_edge_ids[-1] != matched["edge_id"]:
            nearest_edge_ids.append(matched["edge_id"])

    match_ratio = matched_points / len(points)
    if match_ratio < float(config["deterministic_knobs"]["min_match_ratio"]):
        raise ValueError(f"GPX match ratio {match_ratio:.2f} below minimum threshold")

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
    distance_profile_m: list[float] = []
    surface_profile: list[str] = []
    distance_offset = 0.0

    for edge_id in snapped_edge_sequence:
        edge = edge_lookup[edge_id]
        edge_distances = edge["distance_profile_m"]
        edge_elevations = edge["elevation_profile_m"]
        if not distance_profile_m:
            distance_profile_m.extend(edge_distances)
            elevation_profile_m.extend(edge_elevations)
        else:
            distance_profile_m.extend([round(distance_offset + value, 1) for value in edge_distances[1:]])
            elevation_profile_m.extend(edge_elevations[1:])
        distance_offset += edge["length_m"]
        surface_profile.append(edge["surface"])

    grade_profile_pct = build_grade_profile(
        distance_profile_m,
        elevation_profile_m,
        int(config["deterministic_knobs"]["grade_smoothing_window"]),
    )

    return {
        "snapped_edge_sequence": snapped_edge_sequence,
        "elevation_profile_m": elevation_profile_m,
        "distance_profile_m": distance_profile_m,
        "grade_profile_pct": grade_profile_pct,
        "surface_profile": surface_profile,
        "distance_m": round(distance_profile_m[-1], 1),
        "match_ratio": round(match_ratio, 3),
    }


def route_from_gpx(path: Path, graph: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    active_config = load_region_config(DEFAULT_REGION_CONFIG) if config is None else config
    points = load_gpx_points(path)
    snapped = snap_points_to_graph(points, graph, active_config)
    return {
        "route_id": path.stem,
        "source_type": "gpx_import",
        "source_hash": gpx_source_hash(points),
        "snapped_edge_sequence": snapped["snapped_edge_sequence"],
        "elevation_profile_m": snapped["elevation_profile_m"],
        "distance_profile_m": snapped["distance_profile_m"],
        "grade_profile_pct": snapped["grade_profile_pct"],
        "surface_profile": snapped["surface_profile"],
        "distance_m": snapped["distance_m"],
        "region_version": active_config["region_version"],
    }


def _source_manifest_for_package(config: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    manifest_path = paths["raw"] / "source_manifest.json"
    if not manifest_path.exists():
        fetch_sources(config["_config_path"])
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _manifest(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "phase1-region-pack-v1",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "tile_id": config["tile_id"],
        "bbox_wgs84": config["bbox_wgs84"],
        "region_version": config["region_version"],
        "source_versions": {
            artifact.source_id: artifact.version for artifact in _source_artifacts(config)
        },
        "compatible_clients": ["godot-phase1"],
        "ride_graph_asset": "ride_graph.json",
        "scenery_asset": "scenery.json",
        "route_definitions_asset": "routes.json",
        "attribution_asset": "attribution.json",
        "source_manifest_asset": "source_manifest.json",
    }


def _attribution(config: dict[str, Any], source_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
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
            "This region pack contains a deterministic Milwaukee corridor proof for local validation and client integration.",
            "ODbL-sensitive ride graph outputs must retain attribution and provenance when redistributed.",
            "NAIP is used only for preprocessing heuristics and is not redistributed as raw imagery in this pack.",
        ],
    }


def package_region(region_config: str | Path) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    ride_graph = build_ride_graph(region_config)
    scenery = build_scenery(region_config)
    source_manifest = _source_manifest_for_package(config, paths)
    manifest = _manifest(config)
    route = route_from_gpx(DEFAULT_GPX_PATH, ride_graph, config)
    attribution = _attribution(config, source_manifest)
    attribution["region_hash"] = region_pack_hash(manifest, ride_graph, scenery, [route], attribution, source_manifest)

    build_package_dir = _mkdir(paths["build"] / "package")
    files = {
        "manifest.json": manifest,
        "ride_graph.json": ride_graph,
        "scenery.json": scenery,
        "routes.json": [route],
        "attribution.json": attribution,
        "source_manifest.json": source_manifest,
    }
    for filename, payload in files.items():
        (build_package_dir / filename).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    package_dir = paths["package"]
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    for filename in files:
        shutil.copy2(build_package_dir / filename, package_dir / filename)

    return {
        "manifest": manifest,
        "ride_graph": ride_graph,
        "scenery": scenery,
        "routes": [route],
        "attribution": attribution,
        "source_manifest": source_manifest,
    }


def build_phase1_region(region_config: str | Path) -> dict[str, Any]:
    fetch_sources(region_config)
    prepare_sources(region_config)
    build_ride_graph(region_config)
    build_scenery(region_config)
    return package_region(region_config)
