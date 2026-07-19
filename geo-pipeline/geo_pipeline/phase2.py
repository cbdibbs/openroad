from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import heapq
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen
import hashlib
import json
import math
import subprocess
import shutil

from geo_pipeline.determinism import content_hash
from geo_pipeline.phase1 import (
    _distance_profile,
    _edge_distance_m,
    _mkdir,
    _segment_length,
    _smooth_series,
    bike_access_for_tags,
    build_grade_profile,
    load_region_config,
    route_from_gpx,
    stable_edge_id,
)
from geo_pipeline.gpx import GpxPoint, gpx_source_hash, load_gpx_points


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGION_CONFIG = "milwaukee_phase2"
DEFAULT_REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_phase2_region_pack"
SAMPLE_TRACK_PATH = ROOT / "sample-tracks" / "Wauwatosa_to_Lakefront.gpx"
OAKLEAF_TRACK_PATH = ROOT / "region-data" / "milwaukee" / "oak_leaf_demo_loop.gpx"
SOURCE_MODE_FIXTURE = "fixture"
SOURCE_MODE_LIVE = "live"
PHASE2_SOURCE_MODES = {SOURCE_MODE_FIXTURE, SOURCE_MODE_LIVE}


@dataclass(frozen=True)
class Phase2Paths:
    raw: Path
    staged: Path
    build: Path
    package: Path


@dataclass(frozen=True)
class ProjectionContext:
    west: float
    south: float
    east: float
    north: float
    mean_lat_rad: float
    meters_per_degree_lon: float
    meters_per_degree_lat: float


@dataclass(frozen=True)
class DemGrid:
    x_positions_m: list[float]
    y_positions_m: list[float]
    elevation_m: list[list[float]]


def work_paths(config: dict[str, Any]) -> Phase2Paths:
    work = config["work_dirs"]
    return Phase2Paths(
        raw=ROOT / work["raw"],
        staged=ROOT / work["staged"],
        build=ROOT / work["build"],
        package=ROOT / config["package_dir"],
    )


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixture_path(config: dict[str, Any], source_id: str) -> Path:
    return ROOT / config["fixture_assets"][source_id]


def _projection_context(bbox_wgs84: list[float]) -> ProjectionContext:
    west, south, east, north = bbox_wgs84
    mean_lat_rad = math.radians((south + north) / 2.0)
    return ProjectionContext(
        west=west,
        south=south,
        east=east,
        north=north,
        mean_lat_rad=mean_lat_rad,
        meters_per_degree_lon=111_320.0 * math.cos(mean_lat_rad),
        meters_per_degree_lat=110_540.0,
    )


def _project_point(context: ProjectionContext, point_wgs84: list[float]) -> list[float]:
    return [
        round((point_wgs84[0] - context.west) * context.meters_per_degree_lon, 3),
        round((point_wgs84[1] - context.south) * context.meters_per_degree_lat, 3),
    ]


def _unproject_point(context: ProjectionContext, point_m: list[float]) -> list[float]:
    return [
        round(context.west + (point_m[0] / context.meters_per_degree_lon), 6),
        round(context.south + (point_m[1] / context.meters_per_degree_lat), 6),
    ]


def _world_bounds_m(context: ProjectionContext) -> list[float]:
    return _project_point(context, [context.east, context.north])


def _interpolate_point(first: list[float], second: list[float], fraction: float, precision: int = 6) -> list[float]:
    return [
        round(first[0] + ((second[0] - first[0]) * fraction), precision),
        round(first[1] + ((second[1] - first[1]) * fraction), precision),
    ]


def _point_in_bbox(point_wgs84: list[float], bbox_wgs84: list[float]) -> bool:
    west, south, east, north = bbox_wgs84
    return west <= point_wgs84[0] <= east and south <= point_wgs84[1] <= north


def _line_intersects_bbox(geometry_wgs84: list[list[float]], bbox_wgs84: list[float]) -> bool:
    return any(_point_in_bbox(point, bbox_wgs84) for point in geometry_wgs84)


def _phase2_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [
        ("openstreetmap", "OpenStreetMap", "ride_graph", "ODbL 1.0", "Copyright OpenStreetMap contributors"),
        ("usgs_3dep", "USGS 3DEP", "terrain_dem", "USGS public use guidance", "Source: U.S. Geological Survey"),
        (
            "usda_naip",
            "USDA NAIP",
            "style_hints",
            "public use with requested credit",
            "USDA Farm Production and Conservation - Aerial Photography Field Office",
        ),
        (
            "esa_worldcover",
            "ESA WorldCover",
            "biome_masks",
            "CC BY 4.0",
            "Contains modified Copernicus WorldCover data (2021) processed by ESA WorldCover consortium",
        ),
    ]
    sources: list[dict[str, Any]] = []
    for source_id, name, role, license_name, attribution in specs:
        source_config = config["sources"][source_id]
        sources.append(
            {
                "source_id": source_id,
                "name": name,
                "role": role,
                "license": license_name,
                "attribution": attribution,
                "fetch_url": source_config["fetch_url"],
                "product_id": source_config["product_id"],
                "version": source_config["version"],
                "required": source_id not in set(config.get("optional_source_ids", [])),
                "fixture_asset": config["fixture_assets"][source_id],
            }
        )
    return sources


def _way_centroid(points_wgs84: list[list[float]]) -> list[float]:
    if not points_wgs84:
        return [0.0, 0.0]
    return [
        round(sum(point[0] for point in points_wgs84) / len(points_wgs84), 6),
        round(sum(point[1] for point in points_wgs84) / len(points_wgs84), 6),
    ]


def _polygon_from_geometry(geometry: list[dict[str, Any]]) -> list[list[float]]:
    polygon = [[round(float(point["lon"]), 6), round(float(point["lat"]), 6)] for point in geometry]
    if len(polygon) >= 3 and polygon[0] == polygon[-1]:
        polygon = polygon[:-1]
    return polygon


def _height_from_building_tags(tags: dict[str, str]) -> float:
    raw_height = tags.get("height", "")
    if raw_height.endswith(" m"):
        raw_height = raw_height[:-2]
    try:
        if raw_height:
            return max(6.0, min(80.0, round(float(raw_height), 1)))
    except ValueError:
        pass
    levels = tags.get("building:levels", "")
    try:
        if levels:
            return max(6.0, min(80.0, round(float(levels) * 3.2, 1)))
    except ValueError:
        pass
    building_kind = tags.get("building", "yes")
    if building_kind in {"cathedral", "church", "civic", "commercial", "office"}:
        return 20.0
    return 12.0


def _landcover_from_osm_tags(tags: dict[str, str]) -> tuple[str, str] | None:
    if tags.get("leisure") == "park":
        return ("urban_parkland", "#6f9158")
    if tags.get("landuse") in {"grass", "meadow", "recreation_ground"}:
        return ("parkland", "#7aa35f")
    if tags.get("natural") == "wood":
        return ("woodland", "#557348")
    if tags.get("landuse") == "cemetery":
        return ("cemetery_green", "#6f8464")
    return None


def _is_water_feature(tags: dict[str, str]) -> bool:
    return tags.get("natural") == "water" or tags.get("waterway") in {"riverbank", "canal", "stream"} or tags.get("landuse") in {"basin", "reservoir"}


def _is_landmark_feature(tags: dict[str, str]) -> bool:
    return bool(tags.get("name")) and any(
        key in tags for key in ["amenity", "tourism", "historic", "leisure", "shop", "building", "man_made"]
    )


def _normalize_live_openstreetmap_payload(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    bbox = config["bbox_wgs84"]
    ways: list[dict[str, Any]] = []
    streets: list[dict[str, Any]] = []
    buildings: list[dict[str, Any]] = []
    landuse_patches: list[dict[str, Any]] = []
    water_patches: list[dict[str, Any]] = []
    landmarks: list[dict[str, Any]] = []

    for element in payload.get("elements", []):
        tags = {str(key): str(value) for key, value in element.get("tags", {}).items()}
        if element.get("type") == "way" and isinstance(element.get("geometry"), list):
            geometry_wgs84 = [[round(float(point["lon"]), 6), round(float(point["lat"]), 6)] for point in element["geometry"]]
            if len(geometry_wgs84) >= 2 and tags.get("highway"):
                street_feature = {
                    "osm_way_id": f"way/{element['id']}",
                    "tags": tags,
                    "geometry_wgs84": geometry_wgs84,
                }
                streets.append(street_feature)
                if bike_access_for_tags(tags) is not None:
                    ways.append(street_feature)

            polygon_wgs84 = _polygon_from_geometry(element["geometry"])
            if len(polygon_wgs84) >= 3 and tags.get("building"):
                buildings.append(
                    {
                        "building_id": f"bldg_{element['id']}",
                        "footprint_wgs84": polygon_wgs84,
                        "height_m": _height_from_building_tags(tags),
                        "kind": tags.get("building", "yes"),
                        "name": tags.get("name", ""),
                    }
                )

            landcover = _landcover_from_osm_tags(tags)
            if len(polygon_wgs84) >= 3 and landcover is not None:
                landuse_patches.append(
                    {
                        "biome_id": f"osm_patch_{element['id']}",
                        "landcover_class": landcover[0],
                        "color_hint": landcover[1],
                        "polygon_wgs84": polygon_wgs84,
                    }
                )

            if len(polygon_wgs84) >= 3 and _is_water_feature(tags):
                water_patches.append(
                    {
                        "water_id": f"water_{element['id']}",
                        "kind": tags.get("water", tags.get("waterway", tags.get("natural", "water"))),
                        "polygon_wgs84": polygon_wgs84,
                    }
                )

            if _is_landmark_feature(tags):
                landmarks.append(
                    {
                        "landmark_id": f"landmark_way_{element['id']}",
                        "name": tags["name"],
                        "kind": tags.get("tourism", tags.get("amenity", tags.get("historic", tags.get("building", "landmark")))),
                        "point_wgs84": _way_centroid(geometry_wgs84),
                    }
                )

        if element.get("type") == "node" and _is_landmark_feature(tags):
            point_wgs84 = [round(float(element["lon"]), 6), round(float(element["lat"]), 6)]
            if _point_in_bbox(point_wgs84, bbox):
                landmarks.append(
                    {
                        "landmark_id": f"landmark_node_{element['id']}",
                        "name": tags["name"],
                        "kind": tags.get("tourism", tags.get("amenity", tags.get("historic", "landmark"))),
                        "point_wgs84": point_wgs84,
                    }
                )

    return {
        "ways": sorted(ways, key=lambda item: item["osm_way_id"]),
        "streets": sorted(streets, key=lambda item: item["osm_way_id"]),
        "buildings": sorted(buildings, key=lambda item: item["building_id"]),
        "landuse_patches": sorted(landuse_patches, key=lambda item: item["biome_id"]),
        "water_patches": sorted(water_patches, key=lambda item: item["water_id"]),
        "landmarks": sorted(landmarks, key=lambda item: item["landmark_id"]),
    }


def _openstreetmap_live_query(config: dict[str, Any]) -> str:
    west, south, east, north = config["bbox_wgs84"]
    bbox = f"{south},{west},{north},{east}"
    return "\n".join(
        [
            "[out:json][timeout:120];",
            "(",
            f'  way["highway"]({bbox});',
            f'  way["building"]({bbox});',
            f'  way["leisure"]({bbox});',
            f'  way["landuse"]({bbox});',
            f'  way["natural"]({bbox});',
            f'  way["waterway"]({bbox});',
            f'  way["amenity"]({bbox});',
            f'  way["tourism"]({bbox});',
            f'  way["historic"]({bbox});',
            f'  node["amenity"]({bbox});',
            f'  node["tourism"]({bbox});',
            f'  node["historic"]({bbox});',
            f'  node["man_made"]({bbox});',
            ");",
            "out geom;",
        ]
    )


def _fetch_live_openstreetmap_artifact(source_dir: Path, config: dict[str, Any], source: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    cache_path = source_dir / "openstreetmap.overpass.json"
    if source["fetch_url"].startswith("file://") or Path(source["fetch_url"]).exists():
        return cache_path, _download_source_artifact(source["fetch_url"], cache_path)
    live_fetch_url = config["sources"]["openstreetmap"].get("live_fetch_url", source["fetch_url"])
    if live_fetch_url.startswith("file://") or Path(live_fetch_url).exists():
        return cache_path, _download_source_artifact(live_fetch_url, cache_path)

    query = _openstreetmap_live_query(config)
    try:
        request = Request(live_fetch_url, data=query.encode("utf-8"), method="POST")
        request.add_header("Content-Type", "text/plain")
        request.add_header("User-Agent", "procedural-trainer-phase2-live-fetch")
        with urlopen(request) as response:
            payload = response.read()
            cache_path.write_bytes(payload)
            return cache_path, {
                "resolved_fetch_url": response.geturl(),
                "content_length_bytes": len(payload),
                "osm_query": query,
            }
    except Exception:
        fetch_metadata = _curl_fetch(live_fetch_url, cache_path, query)
        fetch_metadata["osm_query"] = query
        return cache_path, fetch_metadata


def _validate_source_mode(mode: str) -> str:
    if mode not in PHASE2_SOURCE_MODES:
        raise ValueError(f"unsupported Phase 2 source mode: {mode}")
    return mode


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_cache_filename(source: dict[str, Any], mode: str) -> str:
    if mode == SOURCE_MODE_FIXTURE:
        return Path(source["fixture_asset"]).name
    parsed = urlparse(source["fetch_url"])
    candidate = Path(parsed.path).name
    if candidate:
        return candidate
    return f"{source['source_id']}.source"


def _download_source_artifact(url: str, destination: Path) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme in {"", "file"}:
        local_path = Path(parsed.path if parsed.scheme == "file" else url)
        shutil.copy2(local_path, destination)
        return {"resolved_fetch_url": local_path.as_uri(), "content_length_bytes": destination.stat().st_size}

    with urlopen(url) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
        return {
            "resolved_fetch_url": response.geturl(),
            "content_length_bytes": int(response.headers.get("Content-Length", destination.stat().st_size or 0)),
        }


def _curl_fetch(url: str, destination: Path, post_body: str | None = None) -> dict[str, Any]:
    command = ["curl", "--fail", "--silent", "--show-error", "--location", "--output", str(destination)]
    if post_body is not None:
        command.extend(["--header", "Content-Type: text/plain", "--data-binary", post_body])
    command.append(url)
    subprocess.run(command, check=True, cwd=ROOT)
    return {"resolved_fetch_url": url, "content_length_bytes": destination.stat().st_size}


def _metadata_only_live_cache(source_dir: Path, source: dict[str, Any], config: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    cache_path = source_dir / f"{source['source_id']}.live-metadata.json"
    payload = {
        "source_id": source["source_id"],
        "fetch_url": source["fetch_url"],
        "product_id": source["product_id"],
        "version": source["version"],
        "region_id": config["region_id"],
        "aoi_id": config["aoi"]["id"],
        "bbox_wgs84": config["bbox_wgs84"],
        "source_mode": SOURCE_MODE_LIVE,
        "cache_kind": "metadata_only_live_receipt",
    }
    _dump_json(cache_path, payload)
    return cache_path, {"resolved_fetch_url": source["fetch_url"], "content_length_bytes": cache_path.stat().st_size}


def _sample_positions(max_value: float, spacing_m: float) -> list[float]:
    positions = [0.0]
    current = spacing_m
    while current < max_value:
        positions.append(round(current, 3))
        current += spacing_m
    if round(max_value, 3) != positions[-1]:
        positions.append(round(max_value, 3))
    return positions


def _fetch_live_usgs_3dep_artifact(source_dir: Path, config: dict[str, Any], source: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    metadata_path = source_dir / "usgs_3dep.live-metadata.json"
    metadata_url = config["sources"]["usgs_3dep"].get("live_metadata_url", source["fetch_url"])
    if metadata_url.startswith("file://") or Path(metadata_url).exists():
        _download_source_artifact(metadata_url, metadata_path)
    else:
        query_url = f"{metadata_url}&bbox={config['bbox_wgs84'][0]},{config['bbox_wgs84'][1]},{config['bbox_wgs84'][2]},{config['bbox_wgs84'][3]}&max=10"
        _curl_fetch(query_url, metadata_path)

    context = _projection_context(config["bbox_wgs84"])
    world_bounds_m = _world_bounds_m(context)
    spacing_m = float(config.get("live_dem_sample_spacing_m", 500.0))
    x_positions_m = _sample_positions(float(world_bounds_m[0]), spacing_m)
    y_positions_m = _sample_positions(float(world_bounds_m[1]), spacing_m)
    elevation_url = config["sources"]["usgs_3dep"].get("live_elevation_url", "https://epqs.nationalmap.gov/v1/json")

    def query_point(point_m: tuple[float, float]) -> float:
        point_wgs84 = _unproject_point(context, [point_m[0], point_m[1]])
        command = [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--retry",
            "2",
            "--retry-delay",
            "1",
            "--get",
            elevation_url,
            "--data-urlencode",
            f"x={point_wgs84[0]}",
            "--data-urlencode",
            f"y={point_wgs84[1]}",
            "--data-urlencode",
            "units=Meters",
            "--data-urlencode",
            "wkid=4326",
            "--data-urlencode",
            "includeDate=false",
        ]
        result = subprocess.run(command, check=True, cwd=ROOT, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        return round(float(payload["value"]), 2)

    point_order = [(x_value, y_value) for y_value in y_positions_m for x_value in x_positions_m]
    elevations: dict[tuple[float, float], float] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(point_order) or 1)) as pool:
        for point, value in zip(point_order, pool.map(query_point, point_order)):
            elevations[point] = value

    grid_path = source_dir / "usgs_3dep.live-grid.json"
    grid_payload = {
        "grid": {
            "x_positions_m": x_positions_m,
            "y_positions_m": y_positions_m,
            "elevation_m": [
                [elevations[(x_value, y_value)] for x_value in x_positions_m]
                for y_value in y_positions_m
            ],
        },
        "source": {
            "metadata_url": metadata_url,
            "elevation_url": elevation_url,
            "sample_spacing_m": spacing_m,
        },
    }
    _dump_json(grid_path, grid_payload)
    return grid_path, metadata_path, {
        "resolved_fetch_url": elevation_url,
        "content_length_bytes": grid_path.stat().st_size,
        "metadata_cache_path": str(metadata_path.relative_to(ROOT)),
        "live_dem_sample_spacing_m": spacing_m,
    }


def _load_json_if_possible(path: Path) -> Any | None:
    try:
        return _load_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _source_fixture_shape_matches(source_id: str, payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if source_id == "openstreetmap":
        return isinstance(payload.get("ways"), list)
    if source_id == "usgs_3dep":
        return isinstance(payload.get("grid"), dict)
    if source_id == "esa_worldcover":
        return isinstance(payload.get("biome_patches"), list) and isinstance(payload.get("prop_masks"), list)
    if source_id == "usda_naip":
        return isinstance(payload.get("style_hints"), dict)
    return False


def _materialized_fixture_extract(
    config: dict[str, Any],
    source: dict[str, Any],
    source_dir: Path,
    local_cache_path: Path,
) -> tuple[Path, str, str]:
    payload = _load_json_if_possible(local_cache_path)
    if payload is not None and _source_fixture_shape_matches(source["source_id"], payload):
        return local_cache_path, "direct_source_extract", ""

    if source["source_id"] == "openstreetmap" and payload is not None and isinstance(payload.get("elements"), list):
        normalized_extract_path = source_dir / "openstreetmap.normalized.json"
        normalized_payload = _normalize_live_openstreetmap_payload(payload, config)
        _dump_json(normalized_extract_path, normalized_payload)
        return normalized_extract_path, "overpass_osm_normalization", ""

    normalized_extract_path = source_dir / f"{source['source_id']}.normalized.json"
    shutil.copy2(_fixture_path(config, source["source_id"]), normalized_extract_path)
    warning = (
        f"live source {source['source_id']} cached the upstream artifact but normalized through the documented Milwaukee "
        "source-derived fixture extract for deterministic local rebuilds"
    )
    return normalized_extract_path, "fixture_fallback_extract", warning


def _load_raw_source_manifest(region_config: str | Path, source_mode: str = SOURCE_MODE_FIXTURE) -> dict[str, Any]:
    config = load_region_config(region_config)
    manifest_path = work_paths(config).raw / "source_manifest.json"
    if not manifest_path.exists():
        fetch_sources(region_config, source_mode)
    return _load_json(manifest_path)


def fetch_sources(region_config: str | Path, mode: str = SOURCE_MODE_FIXTURE) -> dict[str, Any]:
    active_mode = _validate_source_mode(mode)
    config = load_region_config(region_config)
    paths = work_paths(config)
    raw_root = _mkdir(paths.raw)
    artifacts: list[dict[str, Any]] = []
    for source in _phase2_sources(config):
        source_dir = _mkdir(raw_root / source["source_id"])
        cache_path = source_dir / _source_cache_filename(source, active_mode)
        if active_mode == SOURCE_MODE_LIVE and source["source_id"] == "openstreetmap":
            cache_path = source_dir / "openstreetmap.overpass.json"
        normalized_extract_path = cache_path
        normalization_strategy = "direct_source_extract"
        normalization_warning = ""
        fetch_metadata: dict[str, Any]

        if active_mode == SOURCE_MODE_FIXTURE:
            fixture_path = _fixture_path(config, source["source_id"])
            shutil.copy2(fixture_path, cache_path)
            fetch_metadata = {"resolved_fetch_url": fixture_path.as_uri(), "content_length_bytes": cache_path.stat().st_size}
        else:
            try:
                if source["source_id"] == "openstreetmap":
                    cache_path, fetch_metadata = _fetch_live_openstreetmap_artifact(source_dir, config, source)
                elif source["source_id"] == "usgs_3dep" and not (source["fetch_url"].startswith("file://") or Path(source["fetch_url"]).exists()):
                    cache_path, metadata_path, fetch_metadata = _fetch_live_usgs_3dep_artifact(source_dir, config, source)
                    normalized_extract_path = cache_path
                    normalization_strategy = "epqs_dem_grid_sampling"
                    fetch_metadata["metadata_cache_path"] = str(metadata_path.relative_to(ROOT))
                elif source["source_id"] in {"usgs_3dep", "usda_naip", "esa_worldcover"}:
                    cache_path, fetch_metadata = _metadata_only_live_cache(source_dir, source, config)
                else:
                    fetch_metadata = _download_source_artifact(source["fetch_url"], cache_path)
            except Exception as exc:
                if active_mode == SOURCE_MODE_LIVE and cache_path.exists():
                    fetch_metadata = {
                        "resolved_fetch_url": source["fetch_url"],
                        "content_length_bytes": cache_path.stat().st_size,
                    }
                    normalization_warning = f"live source {source['source_id']} reused cached artifact after fetch failure: {exc}"
                elif source["required"]:
                    raise ValueError(f"failed to fetch required live source {source['source_id']}: {exc}") from exc
                else:
                    shutil.copy2(_fixture_path(config, source["source_id"]), cache_path)
                    fetch_metadata = {
                        "resolved_fetch_url": _fixture_path(config, source["source_id"]).as_uri(),
                        "content_length_bytes": cache_path.stat().st_size,
                    }
                    normalization_warning = f"optional live source {source['source_id']} could not be fetched; using documented fixture extract"

            if normalization_strategy == "direct_source_extract":
                normalized_extract_path, normalization_strategy, extract_warning = _materialized_fixture_extract(
                    config,
                    source,
                    source_dir,
                    cache_path,
                )
                if extract_warning:
                    normalization_warning = extract_warning

        cache_payload = _load_json_if_possible(cache_path)
        checksum_sha256 = content_hash(cache_payload) if cache_payload is not None else _sha256_bytes(cache_path.read_bytes())
        receipt = {
            "source_id": source["source_id"],
            "name": source["name"],
            "fetch_url": source["fetch_url"],
            "resolved_fetch_url": fetch_metadata["resolved_fetch_url"],
            "product_id": source["product_id"],
            "version": source["version"],
            "role": source["role"],
            "license": source["license"],
            "attribution": source["attribution"],
            "required": source["required"],
            "retrieved_at": config["retrieved_at"],
            "region_id": config["region_id"],
            "aoi_id": config["aoi"]["id"],
            "bbox_wgs84": config["bbox_wgs84"],
            "fixture_asset": source["fixture_asset"],
            "source_mode": active_mode,
            "content_length_bytes": fetch_metadata["content_length_bytes"],
            "normalization_strategy": normalization_strategy,
        }
        if "osm_query" in fetch_metadata:
            receipt["osm_query"] = fetch_metadata["osm_query"]
        if "metadata_cache_path" in fetch_metadata:
            receipt["metadata_cache_path"] = fetch_metadata["metadata_cache_path"]
        if normalization_warning:
            receipt["normalization_warning"] = normalization_warning
        receipt_path = source_dir / f"{source['source_id']}.receipt.json"
        _dump_json(receipt_path, receipt)
        artifacts.append(
            {
                "source_id": source["source_id"],
                "name": source["name"],
                "role": source["role"],
                "fetch_url": source["fetch_url"],
                "product_id": source["product_id"],
                "version": source["version"],
                "license": source["license"],
                "attribution": source["attribution"],
                "checksum_sha256": checksum_sha256,
                "retrieved_at": config["retrieved_at"],
                "required": bool(source["required"]),
                "optional": not bool(source["required"]),
                "local_receipt_path": str(receipt_path.relative_to(ROOT)),
                "local_cache_path": str(cache_path.relative_to(ROOT)),
                "fixture_asset": source["fixture_asset"],
                "source_mode": active_mode,
                "resolved_fetch_url": fetch_metadata["resolved_fetch_url"],
                "cache_format": "json" if cache_payload is not None else "binary",
                "content_length_bytes": fetch_metadata["content_length_bytes"],
                "normalized_extract_path": str(normalized_extract_path.relative_to(ROOT)),
                "normalization_strategy": normalization_strategy,
            }
        )
        if "osm_query" in fetch_metadata:
            artifacts[-1]["osm_query"] = fetch_metadata["osm_query"]
        if "metadata_cache_path" in fetch_metadata:
            artifacts[-1]["metadata_cache_path"] = fetch_metadata["metadata_cache_path"]
        if normalization_warning:
            artifacts[-1]["normalization_warning"] = normalization_warning
    source_manifest = {
        "schema_version": "phase2-source-manifest-v2",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "aoi_id": config["aoi"]["id"],
        "generated_at": config["retrieved_at"],
        "source_mode": active_mode,
        "toolchain_versions": config["toolchain_versions"],
        "artifacts": sorted(artifacts, key=lambda artifact: artifact["source_id"]),
    }
    _dump_json(raw_root / "source_manifest.json", source_manifest)
    return source_manifest


def prepare_sources(region_config: str | Path, source_mode: str = SOURCE_MODE_FIXTURE) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    _mkdir(paths.staged)
    source_manifest = _load_raw_source_manifest(region_config, source_mode)
    if source_manifest.get("source_mode") != _validate_source_mode(source_mode):
        source_manifest = fetch_sources(region_config, source_mode)
    artifact_by_source = {artifact["source_id"]: artifact for artifact in source_manifest["artifacts"]}
    context = _projection_context(config["bbox_wgs84"])
    projected_bounds = _world_bounds_m(context)
    osm_fixture = _load_json(ROOT / artifact_by_source["openstreetmap"].get("normalized_extract_path", artifact_by_source["openstreetmap"]["local_cache_path"]))
    dem_fixture = _load_json(ROOT / artifact_by_source["usgs_3dep"].get("normalized_extract_path", artifact_by_source["usgs_3dep"]["local_cache_path"]))
    landcover_fixture = _load_json(ROOT / artifact_by_source["esa_worldcover"].get("normalized_extract_path", artifact_by_source["esa_worldcover"]["local_cache_path"]))
    style_fixture = _load_json(ROOT / artifact_by_source["usda_naip"].get("normalized_extract_path", artifact_by_source["usda_naip"]["local_cache_path"]))

    build_warnings = [
        "optional source usda_naip only affects style hints; graph, terrain, and route snapping remain source-complete without it"
    ]
    for artifact in source_manifest["artifacts"]:
        warning = artifact.get("normalization_warning", "")
        if warning and warning not in build_warnings:
            build_warnings.append(warning)

    osm_features = []
    for feature in sorted(osm_fixture["ways"], key=lambda item: item["osm_way_id"]):
        if not _line_intersects_bbox(feature["geometry_wgs84"], config["bbox_wgs84"]):
            continue
        osm_features.append(
            {
                "osm_way_id": feature["osm_way_id"],
                "tags": feature["tags"],
                "geometry_wgs84": feature["geometry_wgs84"],
                "geometry_m": [_project_point(context, point) for point in feature["geometry_wgs84"]],
                "source_lineage": {
                    "source_id": "openstreetmap",
                    "source_feature_id": feature["osm_way_id"],
                    "source_dataset_path": artifact_by_source["openstreetmap"]["local_cache_path"],
                },
            }
        )

    street_features = []
    for feature in sorted(osm_fixture.get("streets", osm_fixture["ways"]), key=lambda item: item["osm_way_id"]):
        if not _line_intersects_bbox(feature["geometry_wgs84"], config["bbox_wgs84"]):
            continue
        street_features.append(
            {
                "osm_way_id": feature["osm_way_id"],
                "tags": feature["tags"],
                "geometry_wgs84": feature["geometry_wgs84"],
                "geometry_m": [_project_point(context, point) for point in feature["geometry_wgs84"]],
            }
        )

    buildings = []
    for building in sorted(osm_fixture.get("buildings", []), key=lambda item: item["building_id"]):
        buildings.append(
            {
                **building,
                "footprint_m": [_project_point(context, point) for point in building["footprint_wgs84"]],
            }
        )

    landcover_patches = []
    for patch in sorted(landcover_fixture["biome_patches"], key=lambda item: item["biome_id"]):
        landcover_patches.append(
            {
                **patch,
                "polygon_m": [_project_point(context, point) for point in patch["polygon_wgs84"]],
            }
        )
    for patch in sorted(osm_fixture.get("landuse_patches", []), key=lambda item: item["biome_id"]):
        landcover_patches.append(
            {
                **patch,
                "polygon_m": [_project_point(context, point) for point in patch["polygon_wgs84"]],
            }
        )

    prop_masks = []
    for mask in sorted(landcover_fixture["prop_masks"], key=lambda item: item["mask_id"]):
        prop_masks.append(
            {
                **mask,
                "polygon_m": [_project_point(context, point) for point in mask["polygon_wgs84"]],
            }
        )
    for patch in osm_fixture.get("landuse_patches", []):
        if patch["landcover_class"] not in {"urban_parkland", "parkland", "woodland", "shoreline_park"}:
            continue
        prop_masks.append(
            {
                "mask_id": f"{patch['biome_id']}_derived_props",
                "density": 0.66 if patch["landcover_class"] == "woodland" else 0.42,
                "prop_class": "trees" if patch["landcover_class"] != "shoreline_park" else "shoreline_grass",
                "polygon_m": [_project_point(context, point) for point in patch["polygon_wgs84"]],
            }
        )

    water_patches = []
    for patch in sorted(osm_fixture.get("water_patches", []), key=lambda item: item["water_id"]):
        water_patches.append(
            {
                **patch,
                "polygon_m": [_project_point(context, point) for point in patch["polygon_wgs84"]],
            }
        )

    landmarks = []
    for landmark in sorted(osm_fixture.get("landmarks", []), key=lambda item: item["landmark_id"]):
        if not _point_in_bbox(landmark["point_wgs84"], config["bbox_wgs84"]):
            continue
        landmarks.append(
            {
                **landmark,
                "point_m": _project_point(context, landmark["point_wgs84"]),
            }
        )

    prepared = {
        "schema_version": "phase2-prepared-sources-v2",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "target_crs": config["target_crs"],
        "intermediate_schema_version": "phase2-intermediate-v2",
        "aoi": {
            "id": config["aoi"]["id"],
            "bbox_wgs84": config["bbox_wgs84"],
            "routeable_inclusion_rule": config["aoi"]["routeable_inclusion_rule"],
            "hash": content_hash({"aoi": config["aoi"], "bbox_wgs84": config["bbox_wgs84"]}),
        },
        "world_bounds_m": projected_bounds,
        "tile_size_m": config["tile_size_m"],
        "streaming_region_size_m": config["streaming_region_size_m"],
        "deterministic_knobs": config["deterministic_knobs"],
        "toolchain_versions": config["toolchain_versions"],
        "source_mode": source_manifest.get("source_mode", SOURCE_MODE_FIXTURE),
        "osm_features": osm_features,
        "street_features": street_features,
        "dem": {
            "source_id": "usgs_3dep",
            "grid": dem_fixture["grid"],
        },
        "landcover": {
            "source_id": "esa_worldcover",
            "biome_patches": sorted(landcover_patches, key=lambda item: item["biome_id"]),
            "prop_masks": sorted(prop_masks, key=lambda item: item["mask_id"]),
        },
        "buildings": buildings,
        "water_patches": water_patches,
        "landmarks": landmarks,
        "style_hints": style_fixture["style_hints"],
        "build_warnings": build_warnings,
    }
    _dump_json(paths.staged / "prepared_sources.json", prepared)
    return prepared


def _tile_counts(world_bounds_m: list[float], tile_size_m: float) -> tuple[int, int]:
    return (
        int(math.ceil(float(world_bounds_m[0]) / tile_size_m)),
        int(math.ceil(float(world_bounds_m[1]) / tile_size_m)),
    )


def _tile_grid_from_bounds(world_bounds_m: list[float], tile_size_m: float) -> list[dict[str, Any]]:
    width_tiles, height_tiles = _tile_counts(world_bounds_m, tile_size_m)
    return [
        {
            "tile_id": f"tile_x{x:02d}_y{y:02d}",
            "tile_x": x,
            "tile_y": y,
            "origin_m": [round(x * tile_size_m, 3), round(y * tile_size_m, 3)],
            "size_m": [round(tile_size_m, 3), round(tile_size_m, 3)],
        }
        for y in range(height_tiles)
        for x in range(width_tiles)
    ]


def _tile_id(point_m: list[float], world_bounds_m: list[float], tile_size_m: float) -> str:
    width_tiles, height_tiles = _tile_counts(world_bounds_m, tile_size_m)
    tile_x = min(width_tiles - 1, max(0, int(point_m[0] // tile_size_m)))
    tile_y = min(height_tiles - 1, max(0, int(point_m[1] // tile_size_m)))
    return f"tile_x{tile_x:02d}_y{tile_y:02d}"


def _stream_region_id_for_tile(tile_x: int, tile_y: int, tile_size_m: float, streaming_region_size_m: float) -> str:
    span = int(round(streaming_region_size_m / tile_size_m))
    return f"stream_x{tile_x // span:02d}_y{tile_y // span:02d}"


def _surface_class(tags: dict[str, str]) -> str:
    return "packed_gravel" if tags.get("surface") in {"compacted", "gravel", "fine_gravel"} else "asphalt"


def _densify_segment(
    first_m: list[float],
    second_m: list[float],
    first_wgs84: list[float],
    second_wgs84: list[float],
    max_step_m: float,
) -> list[tuple[list[float], list[float]]]:
    length_m = math.dist(first_m, second_m)
    steps = max(1, int(math.ceil(length_m / max_step_m)))
    samples: list[tuple[list[float], list[float]]] = []
    for index in range(steps + 1):
        fraction = index / steps
        samples.append(
            (
                _interpolate_point(first_m, second_m, fraction, precision=3),
                _interpolate_point(first_wgs84, second_wgs84, fraction, precision=6),
            )
        )
    return samples


def _split_segment_to_tile_boundaries(
    first_m: list[float],
    second_m: list[float],
    first_wgs84: list[float],
    second_wgs84: list[float],
    tile_size_m: float,
) -> list[tuple[list[list[float]], list[list[float]]]]:
    x1, y1 = first_m
    x2, y2 = second_m
    fractions = {0.0, 1.0}
    for axis_first, axis_second in [(x1, x2), (y1, y2)]:
        start_index = int(math.floor(min(axis_first, axis_second) / tile_size_m))
        end_index = int(math.floor(max(axis_first, axis_second) / tile_size_m))
        for boundary_index in range(start_index + 1, end_index + 1):
            boundary = boundary_index * tile_size_m
            delta = axis_second - axis_first
            if abs(delta) < 1e-6:
                continue
            fraction = (boundary - axis_first) / delta
            if 1e-6 < fraction < 1.0 - 1e-6:
                fractions.add(round(fraction, 10))

    ordered = sorted(fractions)
    segments: list[tuple[list[list[float]], list[list[float]]]] = []
    for start_fraction, end_fraction in zip(ordered, ordered[1:]):
        segment_m = [
            _interpolate_point(first_m, second_m, start_fraction, precision=3),
            _interpolate_point(first_m, second_m, end_fraction, precision=3),
        ]
        segment_wgs84 = [
            _interpolate_point(first_wgs84, second_wgs84, start_fraction, precision=6),
            _interpolate_point(first_wgs84, second_wgs84, end_fraction, precision=6),
        ]
        if math.dist(segment_m[0], segment_m[1]) > 0.1:
            segments.append((segment_m, segment_wgs84))
    return segments


def _build_dem_grid(prepared: dict[str, Any]) -> DemGrid:
    grid = prepared["dem"]["grid"]
    return DemGrid(
        x_positions_m=[float(value) for value in grid["x_positions_m"]],
        y_positions_m=[float(value) for value in grid["y_positions_m"]],
        elevation_m=[[float(value) for value in row] for row in grid["elevation_m"]],
    )


def _interpolate_axis_positions(positions: list[float], value: float) -> tuple[int, int, float]:
    clamped = min(max(value, positions[0]), positions[-1])
    for index in range(len(positions) - 1):
        first = positions[index]
        second = positions[index + 1]
        if first <= clamped <= second:
            span = max(second - first, 1.0)
            return index, index + 1, (clamped - first) / span
    return len(positions) - 2, len(positions) - 1, 1.0


def _sample_dem(point_m: list[float], dem_grid: DemGrid) -> float:
    x0, x1, tx = _interpolate_axis_positions(dem_grid.x_positions_m, float(point_m[0]))
    y0, y1, ty = _interpolate_axis_positions(dem_grid.y_positions_m, float(point_m[1]))
    z00 = dem_grid.elevation_m[y0][x0]
    z10 = dem_grid.elevation_m[y0][x1]
    z01 = dem_grid.elevation_m[y1][x0]
    z11 = dem_grid.elevation_m[y1][x1]
    top = z00 + ((z10 - z00) * tx)
    bottom = z01 + ((z11 - z01) * tx)
    return round(top + ((bottom - top) * ty), 2)


def _structure_offset_m(tags: dict[str, str]) -> float:
    if tags.get("bridge") == "yes":
        return 2.5
    if tags.get("tunnel") == "yes":
        return -2.5
    return 0.0


def _build_feature_segments(
    feature: dict[str, Any],
    tile_size_m: float,
    dem_grid: DemGrid,
    world_bounds_m: list[float],
    streaming_region_size_m: float,
) -> list[dict[str, Any]]:
    densified: list[tuple[list[float], list[float]]] = []
    geometry_m = feature["geometry_m"]
    geometry_wgs84 = feature["geometry_wgs84"]
    for first_index in range(len(geometry_m) - 1):
        segment_samples = _densify_segment(
            geometry_m[first_index],
            geometry_m[first_index + 1],
            geometry_wgs84[first_index],
            geometry_wgs84[first_index + 1],
            max_step_m=240.0,
        )
        if densified:
            segment_samples = segment_samples[1:]
        densified.extend(segment_samples)

    segments: list[dict[str, Any]] = []
    source_segment_index = 0
    for first, second in zip(densified, densified[1:]):
        split_segments = _split_segment_to_tile_boundaries(first[0], second[0], first[1], second[1], tile_size_m)
        for segment_m, segment_wgs84 in split_segments:
            midpoint_m = [
                round((segment_m[0][0] + segment_m[1][0]) / 2.0, 3),
                round((segment_m[0][1] + segment_m[1][1]) / 2.0, 3),
            ]
            tile_id = _tile_id(midpoint_m, world_bounds_m, tile_size_m)
            tile_x = int(tile_id.split("_")[1][1:])
            tile_y = int(tile_id.split("_")[2][1:])
            base_elevations = [_sample_dem(point, dem_grid) for point in segment_m]
            structure_offset = _structure_offset_m(feature["tags"])
            source_segment_index += 1
            source_segment_id = f"{feature['osm_way_id']}#seg{source_segment_index:03d}"
            segments.append(
                {
                    "edge_id": stable_edge_id(source_segment_id, segment_m),
                    "osm_way_id": feature["osm_way_id"],
                    "source_way_id": feature["osm_way_id"],
                    "source_segment_index": source_segment_index,
                    "start_point_m": segment_m[0],
                    "end_point_m": segment_m[-1],
                    "geometry_m": segment_m,
                    "geometry_wgs84": segment_wgs84,
                    "distance_profile_m": _distance_profile(segment_m),
                    "elevation_profile_m": [round(value + structure_offset, 2) for value in base_elevations],
                    "bike_access": bike_access_for_tags(feature["tags"]) or "permitted",
                    "surface": _surface_class(feature["tags"]),
                    "layer": str(feature["tags"].get("layer", "0")),
                    "structure": (
                        "bridge"
                        if feature["tags"].get("bridge") == "yes"
                        else "underpass"
                        if feature["tags"].get("tunnel") == "yes"
                        else "surface"
                    ),
                    "tile_id": tile_id,
                    "stream_region_id": _stream_region_id_for_tile(
                        tile_x,
                        tile_y,
                        tile_size_m,
                        streaming_region_size_m,
                    ),
                    "source_lineage": {
                        **feature["source_lineage"],
                        "source_segment_id": source_segment_id,
                        "upstream_way_id": feature["osm_way_id"],
                    },
                }
            )
    return segments


def _finalize_junction_kinds(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    adjacency: dict[str, int] = {node["node_id"]: 0 for node in nodes}
    for edge in edges:
        adjacency[edge["start_node_id"]] += 1
        adjacency[edge["end_node_id"]] += 1
    for node in nodes:
        degree = adjacency[node["node_id"]]
        node["junction_kind"] = "junction" if degree > 2 else "transition" if degree == 2 else "endpoint"


def build_ride_graph(region_config: str | Path, source_mode: str = SOURCE_MODE_FIXTURE) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    prepared_path = paths.staged / "prepared_sources.json"
    if not prepared_path.exists():
        prepare_sources(region_config, source_mode)
    prepared = _load_json(prepared_path)
    dem_grid = _build_dem_grid(prepared)
    world_bounds_m = [float(value) for value in prepared["world_bounds_m"]]
    tile_size_m = float(prepared["tile_size_m"])
    streaming_region_size_m = float(prepared["streaming_region_size_m"])

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_lookup: dict[tuple[float, float, str], str] = {}
    for feature in sorted(prepared["osm_features"], key=lambda item: item["osm_way_id"]):
        bike_access = bike_access_for_tags(feature["tags"])
        if bike_access is None:
            continue
        for segment in _build_feature_segments(
            feature,
            tile_size_m,
            dem_grid,
            world_bounds_m,
            streaming_region_size_m,
        ):
            for point_m, point_wgs84 in zip(
                [segment["start_point_m"], segment["end_point_m"]],
                [segment["geometry_wgs84"][0], segment["geometry_wgs84"][-1]],
            ):
                layer = segment["layer"]
                node_key = (round(point_m[0], 3), round(point_m[1], 3), layer)
                if node_key not in node_lookup:
                    tile_id = _tile_id(point_m, world_bounds_m, tile_size_m)
                    tile_x = int(tile_id.split("_")[1][1:])
                    tile_y = int(tile_id.split("_")[2][1:])
                    node_id = f"milwaukee_phase2_node_{content_hash({'point_m': point_m, 'layer': layer})[:10]}"
                    node_lookup[node_key] = node_id
                    nodes.append(
                        {
                            "node_id": node_id,
                            "point_wgs84": point_wgs84,
                            "point_m": point_m,
                            "junction_kind": "endpoint",
                            "layer": layer,
                            "tile_id": tile_id,
                            "stream_region_id": _stream_region_id_for_tile(
                                tile_x,
                                tile_y,
                                tile_size_m,
                                streaming_region_size_m,
                            ),
                        }
                    )
            start_key = (round(segment["start_point_m"][0], 3), round(segment["start_point_m"][1], 3), segment["layer"])
            end_key = (round(segment["end_point_m"][0], 3), round(segment["end_point_m"][1], 3), segment["layer"])
            edges.append(
                {
                    "edge_id": segment["edge_id"],
                    "osm_way_id": segment["osm_way_id"],
                    "source_way_id": segment["source_way_id"],
                    "source_segment_index": segment["source_segment_index"],
                    "source_lineage": segment["source_lineage"],
                    "start_node_id": node_lookup[start_key],
                    "end_node_id": node_lookup[end_key],
                    "bike_access": segment["bike_access"],
                    "surface": segment["surface"],
                    "length_m": _segment_length(segment["geometry_m"]),
                    "geometry_wgs84": segment["geometry_wgs84"],
                    "geometry_m": segment["geometry_m"],
                    "distance_profile_m": segment["distance_profile_m"],
                    "elevation_profile_m": segment["elevation_profile_m"],
                    "layer": segment["layer"],
                    "structure": segment["structure"],
                    "tile_id": segment["tile_id"],
                    "stream_region_id": segment["stream_region_id"],
                }
            )

    _finalize_junction_kinds(nodes, edges)
    ride_graph = {
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "graph_profile": config["graph_profile"],
        "bbox_wgs84": config["bbox_wgs84"],
        "aoi_id": prepared["aoi"]["id"],
        "aoi_hash": prepared["aoi"]["hash"],
        "nodes": sorted(nodes, key=lambda node: node["node_id"]),
        "edges": sorted(edges, key=lambda edge: edge["edge_id"]),
    }
    _mkdir(paths.build)
    _dump_json(paths.build / "ride_graph.json", ride_graph)
    return ride_graph


def _bbox_overlap(bounds_a: tuple[float, float, float, float], bounds_b: tuple[float, float, float, float]) -> bool:
    return not (
        bounds_a[2] < bounds_b[0]
        or bounds_a[0] > bounds_b[2]
        or bounds_a[3] < bounds_b[1]
        or bounds_a[1] > bounds_b[3]
    )


def _polygon_bounds(points: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _tile_bounds(tile: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(tile["origin_m"][0]),
        float(tile["origin_m"][1]),
        float(tile["origin_m"][0] + tile["size_m"][0]),
        float(tile["origin_m"][1] + tile["size_m"][1]),
    )


def _terrain_grid(tile: dict[str, Any], dem_grid: DemGrid, samples_per_edge: int) -> list[list[float]]:
    size_m = float(tile["size_m"][0])
    step_m = size_m / float(samples_per_edge - 1)
    grid: list[list[float]] = []
    for row in range(samples_per_edge):
        row_values: list[float] = []
        for column in range(samples_per_edge):
            row_values.append(
                _sample_dem(
                    [
                        float(tile["origin_m"][0]) + (column * step_m),
                        float(tile["origin_m"][1]) + (row * step_m),
                    ],
                    dem_grid,
                )
            )
        grid.append(row_values)
    return grid


def _seam_metadata(elevation_grid_m: list[list[float]]) -> tuple[dict[str, list[float]], dict[str, str]]:
    seam_samples = {
        "south": [round(value, 2) for value in elevation_grid_m[0]],
        "north": [round(value, 2) for value in elevation_grid_m[-1]],
        "west": [round(row[0], 2) for row in elevation_grid_m],
        "east": [round(row[-1], 2) for row in elevation_grid_m],
    }
    seam_hashes = {
        edge_name: content_hash({"samples_m": seam_samples[edge_name]})
        for edge_name in sorted(seam_samples)
    }
    return seam_samples, seam_hashes


def _style_hints(prepared: dict[str, Any], tile: dict[str, Any]) -> dict[str, Any]:
    hints = dict(prepared["style_hints"])
    hints["tile_visual_seed"] = content_hash({"tile_id": tile["tile_id"], "aoi_id": prepared["aoi"]["id"]})[:10]
    return hints


def _street_width_m(tags: dict[str, str]) -> float:
    highway = tags.get("highway", "")
    return {
        "motorway": 12.0,
        "trunk": 11.0,
        "primary": 9.5,
        "secondary": 8.5,
        "tertiary": 7.5,
        "residential": 6.5,
        "service": 5.0,
        "living_street": 5.5,
        "cycleway": 4.6,
        "path": 3.2,
        "footway": 2.2,
    }.get(highway, 4.5)


def _street_material(tags: dict[str, str]) -> str:
    if _is_water_feature(tags):
        return "water"
    if tags.get("surface") in {"compacted", "gravel", "fine_gravel"}:
        return "packed_gravel"
    if tags.get("highway") in {"footway", "path"}:
        return "trail"
    return "asphalt"


def _street_segments_for_tile(
    street_features: list[dict[str, Any]],
    tile_bounds: tuple[float, float, float, float],
    dem_grid: DemGrid,
    excluded_way_ids: set[str],
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for feature in street_features:
        if feature["osm_way_id"] in excluded_way_ids:
            continue
        if not _bbox_overlap(_polygon_bounds(feature["geometry_m"]), tile_bounds):
            continue
        elevations = [_sample_dem(point, dem_grid) for point in feature["geometry_m"]]
        segments.append(
            {
                "segment_id": feature["osm_way_id"],
                "geometry_m": feature["geometry_m"],
                "elevation_profile_m": elevations,
                "width_m": _street_width_m(feature["tags"]),
                "material": _street_material(feature["tags"]),
                "highway": feature["tags"].get("highway", "street"),
            }
        )
    return sorted(segments, key=lambda item: item["segment_id"])


def _rect_polygon(center_m: list[float], width_m: float, depth_m: float) -> list[list[float]]:
    half_width = width_m / 2.0
    half_depth = depth_m / 2.0
    return [
        [round(center_m[0] - half_width, 3), round(center_m[1] - half_depth, 3)],
        [round(center_m[0] + half_width, 3), round(center_m[1] - half_depth, 3)],
        [round(center_m[0] + half_width, 3), round(center_m[1] + half_depth, 3)],
        [round(center_m[0] - half_width, 3), round(center_m[1] + half_depth, 3)],
    ]


def _tile_inset_polygon(tile: dict[str, Any], inset_m: float) -> list[list[float]]:
    origin_x = float(tile["origin_m"][0]) + inset_m
    origin_y = float(tile["origin_m"][1]) + inset_m
    max_x = float(tile["origin_m"][0] + tile["size_m"][0]) - inset_m
    max_y = float(tile["origin_m"][1] + tile["size_m"][1]) - inset_m
    return [
        [round(origin_x, 3), round(origin_y, 3)],
        [round(max_x, 3), round(origin_y, 3)],
        [round(max_x, 3), round(max_y, 3)],
        [round(origin_x, 3), round(max_y, 3)],
    ]


def _point_within_bounds(point_m: list[float], bounds: tuple[float, float, float, float], margin_m: float = 0.0) -> bool:
    return (
        bounds[0] + margin_m <= float(point_m[0]) <= bounds[2] - margin_m
        and bounds[1] + margin_m <= float(point_m[1]) <= bounds[3] - margin_m
    )


def _edge_midpoint_m(edge: dict[str, Any]) -> list[float]:
    geometry = edge["geometry_m"]
    midpoint_index = len(geometry) // 2
    return [float(geometry[midpoint_index][0]), float(geometry[midpoint_index][1])]


def _district_kind(
    buildings: list[dict[str, Any]],
    biome_patches: list[dict[str, Any]],
    road_edges: list[dict[str, Any]],
) -> str:
    landcover_classes = {patch["landcover_class"] for patch in biome_patches}
    if "urban_core" in landcover_classes:
        return "urban_core"
    if "shoreline_park" in landcover_classes:
        return "shoreline_park"
    if "urban_parkland" in landcover_classes:
        return "parkland"
    if buildings:
        return "mixed_use"
    if len(road_edges) >= 5:
        return "neighborhood"
    if road_edges:
        return "corridor"
    return "open_ground"


def _terrain_tint_hex(district_kind: str) -> str:
    return {
        "urban_core": "#847c6b",
        "mixed_use": "#7f8467",
        "neighborhood": "#73835e",
        "corridor": "#7a8462",
        "parkland": "#678351",
        "shoreline_park": "#739c67",
        "open_ground": "#6d7f5b",
    }.get(district_kind, "#6d7f5b")


def _fallback_biome_patches(tile: dict[str, Any], biome_patches: list[dict[str, Any]], district_kind: str) -> list[dict[str, Any]]:
    if biome_patches:
        return sorted(biome_patches, key=lambda patch: patch["biome_id"])
    inset = 100.0 if district_kind in {"urban_core", "mixed_use"} else 70.0
    return [
        {
            "biome_id": f"{tile['tile_id']}_{district_kind}",
            "landcover_class": district_kind,
            "color_hint": _terrain_tint_hex(district_kind),
            "polygon_m": _tile_inset_polygon(tile, inset),
        }
    ]


def _fallback_prop_masks(tile: dict[str, Any], prop_masks: list[dict[str, Any]], district_kind: str, road_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if prop_masks:
        return sorted(prop_masks, key=lambda mask: mask["mask_id"])
    if not road_edges and district_kind not in {"parkland", "shoreline_park"}:
        return []
    prop_class = "street_trees" if district_kind in {"urban_core", "mixed_use", "neighborhood", "corridor"} else "trees"
    density = 0.34 if district_kind == "urban_core" else 0.45 if district_kind in {"mixed_use", "neighborhood"} else 0.58
    return [
        {
            "mask_id": f"{tile['tile_id']}_{prop_class}",
            "density": density,
            "polygon_m": _tile_inset_polygon(tile, 130.0),
            "prop_class": prop_class,
        }
    ]


def _fallback_buildings(
    tile: dict[str, Any],
    tile_bounds: tuple[float, float, float, float],
    road_edges: list[dict[str, Any]],
    buildings: list[dict[str, Any]],
    district_kind: str,
) -> list[dict[str, Any]]:
    if buildings:
        return sorted(buildings, key=lambda building: building["building_id"])
    if district_kind not in {"urban_core", "mixed_use", "neighborhood"}:
        return []
    synthesized: list[dict[str, Any]] = []
    candidate_edges = sorted(road_edges, key=lambda edge: edge["edge_id"])[: 4 if district_kind == "urban_core" else 2]
    for index, edge in enumerate(candidate_edges):
        midpoint = _edge_midpoint_m(edge)
        offset_x = 90.0 if index % 2 == 0 else -90.0
        offset_y = 55.0 if index % 3 == 0 else -55.0
        center = [midpoint[0] + offset_x, midpoint[1] + offset_y]
        if not _point_within_bounds(center, tile_bounds, 120.0):
            center = [
                min(max(midpoint[0], tile_bounds[0] + 160.0), tile_bounds[2] - 160.0),
                min(max(midpoint[1], tile_bounds[1] + 160.0), tile_bounds[3] - 160.0),
            ]
        width_m = 60.0 if district_kind == "urban_core" else 42.0
        depth_m = 42.0 if district_kind == "urban_core" else 28.0
        height_m = 26.0 if district_kind == "urban_core" else 15.0
        synthesized.append(
            {
                "building_id": f"{tile['tile_id']}_bldg_{index + 1:02d}",
                "footprint_m": _rect_polygon(center, width_m, depth_m),
                "height_m": height_m,
                "kind": district_kind,
            }
        )
    return synthesized


def _tile_style_hints(prepared: dict[str, Any], tile: dict[str, Any], district_kind: str) -> dict[str, Any]:
    hints = _style_hints(prepared, tile)
    hints["district_kind"] = district_kind
    hints["terrain_tint"] = _terrain_tint_hex(district_kind)
    return hints


def _streaming_regions(config: dict[str, Any], scenery_index: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for tile in scenery_index["tiles"]:
        grouped.setdefault(tile["stream_region_id"], []).append(tile)
    span = int(round(float(config["streaming_region_size_m"]) / float(config["tile_size_m"])))
    regions: list[dict[str, Any]] = []
    for stream_region_id, tiles in sorted(grouped.items()):
        tile_ids = sorted(tile["tile_id"] for tile in tiles)
        tile_x_values = [int(tile_id.split("_")[1][1:]) for tile_id in tile_ids]
        tile_y_values = [int(tile_id.split("_")[2][1:]) for tile_id in tile_ids]
        min_x = min(tile_x_values)
        min_y = min(tile_y_values)
        region_x = min_x // span
        region_y = min_y // span
        neighbor_region_ids: list[str] = []
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            candidate = f"stream_x{region_x + dx:02d}_y{region_y + dy:02d}"
            if candidate in grouped:
                neighbor_region_ids.append(candidate)
        regions.append(
            {
                "stream_region_id": stream_region_id,
                "tile_ids": tile_ids,
                "origin_m": [round(min_x * float(config["tile_size_m"]), 3), round(min_y * float(config["tile_size_m"]), 3)],
                "size_m": [
                    round(span * float(config["tile_size_m"]), 3),
                    round(span * float(config["tile_size_m"]), 3),
                ],
                "neighbor_region_ids": sorted(neighbor_region_ids),
            }
        )
    return regions


def build_scenery(region_config: str | Path, source_mode: str = SOURCE_MODE_FIXTURE) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    prepared_path = paths.staged / "prepared_sources.json"
    ride_graph_path = paths.build / "ride_graph.json"
    if not prepared_path.exists():
        prepare_sources(region_config, source_mode)
    if not ride_graph_path.exists():
        build_ride_graph(region_config, source_mode)
    prepared = _load_json(prepared_path)
    ride_graph = _load_json(ride_graph_path)
    dem_grid = _build_dem_grid(prepared)
    tiles = _tile_grid_from_bounds(prepared["world_bounds_m"], float(config["tile_size_m"]))
    tile_root = _mkdir(paths.build / "tiles")
    tile_graph_map = {tile["tile_id"]: [] for tile in tiles}
    for edge in ride_graph["edges"]:
        tile_graph_map[edge["tile_id"]].append(edge)

    scenery_index = {
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "tile_size_m": config["tile_size_m"],
        "streaming_region_size_m": config["streaming_region_size_m"],
        "tiles": [],
        "style_hints": prepared["style_hints"],
        "build_warnings": prepared["build_warnings"],
    }

    for tile in tiles:
        tile_dir = _mkdir(tile_root / tile["tile_id"])
        tile_bounds = _tile_bounds(tile)
        tile_edges = sorted(tile_graph_map[tile["tile_id"]], key=lambda item: item["edge_id"])
        terrain_samples = int(config["terrain_grid_samples"])
        elevation_grid_m = _terrain_grid(tile, dem_grid, terrain_samples)
        seam_samples_m, seam_hashes = _seam_metadata(elevation_grid_m)
        road_segments = [
            {
                "edge_id": edge["edge_id"],
                "width_m": 4.0 if edge["surface"] == "packed_gravel" else 5.0,
                "material": edge["surface"],
                "structure": edge["structure"],
            }
            for edge in tile_edges
        ]
        existing_buildings = [
            building
            for building in prepared["buildings"]
            if _bbox_overlap(_polygon_bounds(building["footprint_m"]), tile_bounds)
        ]
        existing_biome_patches = [
            patch
            for patch in prepared["landcover"]["biome_patches"]
            if _bbox_overlap(_polygon_bounds(patch["polygon_m"]), tile_bounds)
        ]
        existing_prop_masks = [
            mask
            for mask in prepared["landcover"]["prop_masks"]
            if _bbox_overlap(_polygon_bounds(mask["polygon_m"]), tile_bounds)
        ]
        street_segments = _street_segments_for_tile(
            prepared.get("street_features", []),
            tile_bounds,
            dem_grid,
            {edge["source_way_id"] for edge in tile_edges},
        )
        water_patches = [
            patch
            for patch in prepared.get("water_patches", [])
            if _bbox_overlap(_polygon_bounds(patch["polygon_m"]), tile_bounds)
        ]
        landmarks = [
            landmark
            for landmark in prepared.get("landmarks", [])
            if _point_within_bounds(landmark["point_m"], tile_bounds)
        ]
        district_kind = _district_kind(existing_buildings, existing_biome_patches, tile_edges)
        buildings = _fallback_buildings(tile, tile_bounds, tile_edges, existing_buildings, district_kind)
        biome_patches = _fallback_biome_patches(tile, existing_biome_patches, district_kind)
        prop_masks = _fallback_prop_masks(tile, existing_prop_masks, district_kind, tile_edges)
        scenery = {
            "region_id": config["region_id"],
            "corridor_id": config["corridor_id"],
            "region_version": config["region_version"],
            "terrain_chunks": [
                {
                    "chunk_id": f"{tile['tile_id']}_terrain",
                    "origin_m": tile["origin_m"],
                    "size_m": tile["size_m"],
                    "grid_resolution": terrain_samples,
                    "sample_spacing_m": round(float(tile["size_m"][0]) / float(terrain_samples - 1), 3),
                    "elevation_grid_m": elevation_grid_m,
                    "seam_samples_m": seam_samples_m,
                    "seam_hashes": seam_hashes,
                    "normal_policy": "derive_from_shared_heightfield",
                    "skirt_policy": "disabled",
                }
            ],
            "road_segments": road_segments,
            "street_segments": street_segments,
            "water_patches": sorted(water_patches, key=lambda patch: patch["water_id"]),
            "landmarks": sorted(landmarks, key=lambda landmark: landmark["landmark_id"]),
            "biome_patches": biome_patches,
            "style_hints": _tile_style_hints(prepared, tile, district_kind),
            "buildings": buildings,
            "prop_masks": prop_masks,
        }
        tile_edge_ids = {edge["edge_id"] for edge in tile_edges}
        tile_node_ids = {
            node_id
            for edge in tile_edges
            for node_id in [edge["start_node_id"], edge["end_node_id"]]
        }
        tile_graph = {
            "region_id": config["region_id"],
            "corridor_id": config["corridor_id"],
            "region_version": config["region_version"],
            "graph_profile": config["graph_profile"],
            "bbox_wgs84": config["bbox_wgs84"],
            "aoi_id": prepared["aoi"]["id"],
            "aoi_hash": prepared["aoi"]["hash"],
            "nodes": [node for node in ride_graph["nodes"] if node["node_id"] in tile_node_ids],
            "edges": [edge for edge in ride_graph["edges"] if edge["edge_id"] in tile_edge_ids],
        }
        tile_manifest = {
            "schema_version": "phase2-region-tile-v2",
            "region_id": config["region_id"],
            "corridor_id": config["corridor_id"],
            "tile_id": tile["tile_id"],
            "bbox_wgs84": config["bbox_wgs84"],
            "region_version": config["region_version"],
            "source_versions": {artifact["source_id"]: artifact["version"] for artifact in _load_raw_source_manifest(region_config, source_mode)["artifacts"]},
            "compatible_clients": ["godot-phase2"],
            "ride_graph_asset": f"tiles/{tile['tile_id']}/ride_graph.json",
            "scenery_asset": f"tiles/{tile['tile_id']}/scenery.json",
            "route_definitions_asset": "routes.json",
            "attribution_asset": "attribution.json",
            "source_manifest_asset": "source_manifest.json",
            "seam_hashes": seam_hashes,
        }
        _dump_json(tile_dir / "manifest.json", tile_manifest)
        _dump_json(tile_dir / "ride_graph.json", tile_graph)
        _dump_json(tile_dir / "scenery.json", scenery)
        tile_x = int(tile["tile_id"].split("_")[1][1:])
        tile_y = int(tile["tile_id"].split("_")[2][1:])
        scenery_index["tiles"].append(
            {
                "tile_id": tile["tile_id"],
                "origin_m": tile["origin_m"],
                "size_m": tile["size_m"],
                "stream_region_id": _stream_region_id_for_tile(
                    tile_x,
                    tile_y,
                    float(config["tile_size_m"]),
                    float(config["streaming_region_size_m"]),
                ),
                "manifest_asset": f"tiles/{tile['tile_id']}/manifest.json",
                "seam_hashes": seam_hashes,
            }
        )

    scenery_index["tiles"] = sorted(scenery_index["tiles"], key=lambda tile: tile["tile_id"])
    _dump_json(paths.build / "scenery_index.json", scenery_index)
    return scenery_index


def _route_from_edge_sequence(route_id: str, source_type: str, source_hash: str, edge_sequence: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    distance_profile_m: list[float] = []
    elevation_profile_m: list[float] = []
    surface_profile: list[str] = []
    distance_offset = 0.0
    for edge in edge_sequence:
        if not distance_profile_m:
            distance_profile_m.extend(edge["distance_profile_m"])
            elevation_profile_m.extend(edge["elevation_profile_m"])
        else:
            distance_profile_m.extend([round(distance_offset + value, 1) for value in edge["distance_profile_m"][1:]])
            elevation_profile_m.extend(edge["elevation_profile_m"][1:])
        distance_offset += float(edge["length_m"])
        surface_profile.append(edge["surface"])
    return {
        "route_id": route_id,
        "source_type": source_type,
        "source_hash": source_hash,
        "snapped_edge_sequence": [edge["edge_id"] for edge in edge_sequence],
        "elevation_profile_m": elevation_profile_m,
        "distance_profile_m": distance_profile_m,
        "grade_profile_pct": build_grade_profile(
            distance_profile_m,
            elevation_profile_m,
            int(config["deterministic_knobs"]["grade_smoothing_window"]),
        ),
        "surface_profile": surface_profile,
        "distance_m": round(distance_profile_m[-1], 1),
        "region_version": config["region_version"],
    }


def _catalog_entry(route: dict[str, Any], display_name: str, difficulty: str, start_area: str) -> dict[str, Any]:
    elevation_gain_m = 0.0
    elevations = route["elevation_profile_m"]
    for index in range(1, len(elevations)):
        elevation_gain_m += max(0.0, elevations[index] - elevations[index - 1])
    return {
        "route_id": route["route_id"],
        "display_name": display_name,
        "difficulty": difficulty,
        "start_area": start_area,
        "distance_m": route["distance_m"],
        "elevation_gain_m": round(elevation_gain_m, 1),
        "preview_edge_id": route["snapped_edge_sequence"][0],
        "region_version": route["region_version"],
    }


def _node_edge_adjacency(ride_graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in ride_graph["edges"]:
        adjacency.setdefault(edge["start_node_id"], []).append(edge)
        adjacency.setdefault(edge["end_node_id"], []).append(edge)
    return adjacency


def _largest_component_node_ids(ride_graph: dict[str, Any]) -> set[str]:
    adjacency = _node_edge_adjacency(ride_graph)
    remaining = set(adjacency)
    largest: set[str] = set()
    while remaining:
        start = remaining.pop()
        component = {start}
        queue = deque([start])
        while queue:
            node_id = queue.popleft()
            for edge in adjacency.get(node_id, []):
                neighbor_id = edge["end_node_id"] if edge["start_node_id"] == node_id else edge["start_node_id"]
                if neighbor_id in component:
                    continue
                component.add(neighbor_id)
                if neighbor_id in remaining:
                    remaining.remove(neighbor_id)
                queue.append(neighbor_id)
        if len(component) > len(largest):
            largest = component
    return largest


def _farthest_node(
    adjacency: dict[str, list[dict[str, Any]]],
    allowed_nodes: set[str],
    start_node_id: str,
) -> tuple[str, dict[str, float], dict[str, tuple[str, str]]]:
    distances: dict[str, float] = {start_node_id: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    queue: list[tuple[float, str]] = [(0.0, start_node_id)]
    while queue:
        distance, node_id = heapq.heappop(queue)
        if distance > distances.get(node_id, float("inf")):
            continue
        for edge in adjacency.get(node_id, []):
            neighbor_id = edge["end_node_id"] if edge["start_node_id"] == node_id else edge["start_node_id"]
            if neighbor_id not in allowed_nodes:
                continue
            next_distance = distance + float(edge["length_m"])
            if next_distance >= distances.get(neighbor_id, float("inf")):
                continue
            distances[neighbor_id] = next_distance
            previous[neighbor_id] = (node_id, edge["edge_id"])
            heapq.heappush(queue, (next_distance, neighbor_id))
    farthest_node_id = max(distances, key=lambda node_id: distances[node_id])
    return farthest_node_id, distances, previous


def _path_from_previous(previous: dict[str, tuple[str, str]], end_node_id: str) -> list[str]:
    edge_ids: list[str] = []
    current = end_node_id
    while current in previous:
        parent, edge_id = previous[current]
        edge_ids.append(edge_id)
        current = parent
    edge_ids.reverse()
    return edge_ids


def _fallback_starter_routes(ride_graph: dict[str, Any], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    adjacency = _node_edge_adjacency(ride_graph)
    if not adjacency:
        return [], []
    component_nodes = _largest_component_node_ids(ride_graph)
    start_node_id = sorted(component_nodes)[0]
    first_end, _, _ = _farthest_node(adjacency, component_nodes, start_node_id)
    second_end, _, previous = _farthest_node(adjacency, component_nodes, first_end)
    primary_edge_ids = _path_from_previous(previous, second_end)
    edge_lookup = {edge["edge_id"]: edge for edge in ride_graph["edges"]}
    primary_edges = [edge_lookup[edge_id] for edge_id in primary_edge_ids if edge_id in edge_lookup]
    if not primary_edges:
        return [], []

    primary_route = _route_from_edge_sequence(
        "starter_live_city_span",
        "starter_route",
        f"starter:{content_hash({'route_id': 'starter_live_city_span', 'edge_ids': primary_edge_ids})}",
        primary_edges,
        config,
    )
    secondary_slice = primary_edges[max(0, len(primary_edges) // 5) : max(2, len(primary_edges) * 4 // 5)]
    secondary_edges = secondary_slice if secondary_slice else primary_edges[: max(2, min(24, len(primary_edges)))]
    secondary_edge_ids = [edge["edge_id"] for edge in secondary_edges]
    secondary_route = _route_from_edge_sequence(
        "starter_live_river_run",
        "starter_route",
        f"starter:{content_hash({'route_id': 'starter_live_river_run', 'edge_ids': secondary_edge_ids})}",
        secondary_edges,
        config,
    )
    routes = [primary_route, secondary_route]
    catalog = [
        _catalog_entry(primary_route, "Live City Span", "moderate", "Milwaukee live OSM"),
        _catalog_entry(secondary_route, "Live River Run", "easy", "Milwaukee live OSM"),
    ]
    return routes, catalog


def _route_from_way_ids(
    route_id: str,
    display_name: str,
    difficulty: str,
    start_area: str,
    way_ids: list[str],
    ride_graph: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    way_lookup: dict[str, list[dict[str, Any]]] = {}
    for edge in ride_graph["edges"]:
        way_lookup.setdefault(edge["source_way_id"], []).append(edge)
    if any(way_id not in way_lookup for way_id in way_ids):
        return None
    edge_sequence: list[dict[str, Any]] = []
    for way_id in way_ids:
        edge_sequence.extend(sorted(way_lookup[way_id], key=lambda edge: edge["source_segment_index"]))
    route = _route_from_edge_sequence(
        route_id,
        "starter_route",
        f"starter:{content_hash({'route_id': route_id, 'way_ids': way_ids})}",
        edge_sequence,
        config,
    )
    return route, _catalog_entry(route, display_name, difficulty, start_area)


def _starter_routes(ride_graph: dict[str, Any], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if str(config.get("region_id", "")).endswith("_live"):
        return _fallback_starter_routes(ride_graph, config)

    route_specs = [
        (
            "starter_cross_city_connector",
            "Cross-City Connector",
            "moderate",
            "Wauwatosa",
            ["way/5101", "way/5102", "way/6103", "way/6101", "way/6104", "way/5106"],
        ),
        (
            "starter_lakefront_orbit",
            "Lakefront Orbit",
            "easy",
            "Milwaukee lakefront",
            ["way/5104", "way/5105"],
        ),
    ]
    routes: list[dict[str, Any]] = []
    catalog_entries: list[dict[str, Any]] = []
    for route_spec in route_specs:
        route_bundle = _route_from_way_ids(*route_spec, ride_graph, config)
        if route_bundle is None:
            continue
        route, catalog = route_bundle
        routes.append(route)
        catalog_entries.append(catalog)

    oak_leaf_route = route_from_gpx_phase2(OAKLEAF_TRACK_PATH, ride_graph, config)
    oak_leaf_route["route_id"] = "starter_oak_leaf_demo"
    routes.append(oak_leaf_route)
    catalog_entries.append(_catalog_entry(oak_leaf_route, "Oak Leaf Demo Loop", "moderate", "Milwaukee core trails"))

    sample_route = route_from_gpx_phase2(SAMPLE_TRACK_PATH, ride_graph, config)
    sample_route["route_id"] = "starter_wauwatosa_lakefront"
    routes.append(sample_route)
    catalog_entries.append(_catalog_entry(sample_route, "Wauwatosa to Lakefront", "moderate", "Wauwatosa"))

    return (
        sorted(routes, key=lambda route: route["route_id"]),
        sorted(catalog_entries, key=lambda entry: entry["route_id"]),
    )


def _root_manifest(config: dict[str, Any], prepared: dict[str, Any], starter_route_ids: list[str], source_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "phase2-region-root-v2",
        "region_id": config["region_id"],
        "corridor_id": config["corridor_id"],
        "region_version": config["region_version"],
        "bbox_wgs84": config["bbox_wgs84"],
        "aoi_id": prepared["aoi"]["id"],
        "aoi_hash": prepared["aoi"]["hash"],
        "source_versions": {artifact["source_id"]: artifact["version"] for artifact in source_manifest["artifacts"]},
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
        "build_warnings": prepared["build_warnings"],
        "starter_route_ids": starter_route_ids,
        "toolchain_versions": prepared["toolchain_versions"],
        "deterministic_build_knobs": prepared["deterministic_knobs"],
        "intermediate_schema_version": prepared["intermediate_schema_version"],
        "visual_qa": {
            "route_id": "starter_wauwatosa_lakefront",
            "camera_mode": "third_person_follow",
            "checklist": [
                "Ride across at least three 1 km tile seams.",
                "Ride across at least one 4 km stream-region boundary.",
                "Confirm terrain and road surfaces remain vertically continuous.",
            ],
        },
    }


def _attribution(
    config: dict[str, Any],
    source_manifest: dict[str, Any],
    root_manifest: dict[str, Any],
    ride_graph: dict[str, Any],
    routes: list[dict[str, Any]],
    streaming_regions: list[dict[str, Any]],
    scenery_index: dict[str, Any],
) -> dict[str, Any]:
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
            "This Milwaukee Phase 2 pack is baked from documented staged source fixtures and retains explicit rebuild provenance.",
            "ODbL-sensitive ride graph outputs must retain attribution and provenance on redistribution.",
            "NAIP remains an optional scenery enrichment source and does not affect the canonical ride graph.",
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


def package_region(region_config: str | Path, source_mode: str = SOURCE_MODE_FIXTURE) -> dict[str, Any]:
    config = load_region_config(region_config)
    paths = work_paths(config)
    prepared = prepare_sources(region_config, source_mode)
    ride_graph = build_ride_graph(region_config, source_mode)
    scenery_index = build_scenery(region_config, source_mode)
    source_manifest = _load_raw_source_manifest(region_config, source_mode)
    routes, route_catalog = _starter_routes(ride_graph, config)
    streaming_regions = _streaming_regions(config, scenery_index)
    root_manifest = _root_manifest(config, prepared, [entry["route_id"] for entry in route_catalog], source_manifest)
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
        _dump_json(build_package_dir / filename, payload)

    if paths.package.exists():
        shutil.rmtree(paths.package)
    _mkdir(paths.package)
    for filename in files:
        shutil.copy2(build_package_dir / filename, paths.package / filename)
    if (paths.package / "tiles").exists():
        shutil.rmtree(paths.package / "tiles")
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


def build_phase2_region(region_config: str | Path, source_mode: str = SOURCE_MODE_FIXTURE) -> dict[str, Any]:
    fetch_sources(region_config, source_mode)
    prepare_sources(region_config, source_mode)
    build_ride_graph(region_config, source_mode)
    build_scenery(region_config, source_mode)
    return package_region(region_config, source_mode)


def _edge_adjacency(graph: dict[str, Any]) -> dict[str, list[str]]:
    by_node: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        by_node.setdefault(edge["start_node_id"], []).append(edge["edge_id"])
        by_node.setdefault(edge["end_node_id"], []).append(edge["edge_id"])
    adjacency: dict[str, set[str]] = {}
    for edge_ids in by_node.values():
        for edge_id in edge_ids:
            adjacency.setdefault(edge_id, set()).update(other for other in edge_ids if other != edge_id)
    return {edge_id: sorted(neighbors) for edge_id, neighbors in adjacency.items()}


def _bounded_bridge_path(
    start_edge_id: str,
    end_edge_id: str,
    adjacency: dict[str, list[str]],
    max_bridge_edges: int,
    path_cache: dict[tuple[str, str], list[str] | None],
) -> list[str] | None:
    cache_key = (start_edge_id, end_edge_id)
    if cache_key in path_cache:
        return path_cache[cache_key]
    if start_edge_id == end_edge_id:
        return [start_edge_id]
    queue: deque[tuple[str, list[str]]] = deque([(start_edge_id, [start_edge_id])])
    seen = {start_edge_id}
    while queue:
        edge_id, path = queue.popleft()
        if len(path) > max_bridge_edges:
            continue
        for neighbor_id in adjacency.get(edge_id, []):
            if neighbor_id in seen:
                continue
            next_path = path + [neighbor_id]
            if neighbor_id == end_edge_id:
                path_cache[cache_key] = next_path
                return next_path
            seen.add(neighbor_id)
            queue.append((neighbor_id, next_path))
    path_cache[cache_key] = None
    return None


def _wgs84_distance_m(first: GpxPoint, second: GpxPoint) -> float:
    mean_lat = math.radians((first.latitude + second.latitude) / 2.0)
    meters_per_degree_lon = 111_320.0 * math.cos(mean_lat)
    meters_per_degree_lat = 110_540.0
    return math.hypot(
        (second.longitude - first.longitude) * meters_per_degree_lon,
        (second.latitude - first.latitude) * meters_per_degree_lat,
    )


def _decimate_gpx_points(points: list[GpxPoint], min_spacing_m: float) -> list[GpxPoint]:
    if len(points) <= 2:
        return points
    decimated = [points[0]]
    for point in points[1:-1]:
        if _wgs84_distance_m(decimated[-1], point) >= min_spacing_m:
            decimated.append(point)
    if decimated[-1] != points[-1]:
        decimated.append(points[-1])
    return decimated


def _snap_points_to_graph_phase2(points: list[GpxPoint], graph: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    threshold_m = float(config["deterministic_knobs"]["max_snap_distance_m"])
    max_bridge_edges = 10
    candidate_pool = min(8, len(graph["edges"]))
    matched_points = 0
    nearest_edge_ids: list[str] = []
    edge_lookup = {edge["edge_id"]: edge for edge in graph["edges"]}
    adjacency = _edge_adjacency(graph)
    path_cache: dict[tuple[str, str], list[str] | None] = {}

    for point in points:
        ranked = sorted(
            graph["edges"],
            key=lambda edge: (_edge_distance_m(point, edge), edge["edge_id"]),
        )[:candidate_pool]
        if ranked and _edge_distance_m(point, ranked[0]) <= threshold_m:
            matched_points += 1

        chosen = ranked[0]
        if nearest_edge_ids:
            for candidate in ranked:
                if candidate["edge_id"] == nearest_edge_ids[-1]:
                    chosen = candidate
                    break
                bridge_path = _bounded_bridge_path(
                    nearest_edge_ids[-1],
                    candidate["edge_id"],
                    adjacency,
                    max_bridge_edges,
                    path_cache,
                )
                if bridge_path is not None:
                    chosen = candidate
                    break
        if not nearest_edge_ids or nearest_edge_ids[-1] != chosen["edge_id"]:
            nearest_edge_ids.append(chosen["edge_id"])

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
        var_bridge = _bounded_bridge_path(
            snapped_edge_sequence[-1],
            edge_id,
            adjacency,
            max_bridge_edges,
            path_cache,
        )
        if var_bridge is None:
            continue
        snapped_edge_sequence.extend(var_bridge[1:])

    if len(snapped_edge_sequence) > 1 and snapped_edge_sequence[0] == snapped_edge_sequence[-1]:
        snapped_edge_sequence.pop()

    distance_profile_m: list[float] = []
    elevation_profile_m: list[float] = []
    surface_profile: list[str] = []
    distance_offset = 0.0
    for edge_id in snapped_edge_sequence:
        edge = edge_lookup[edge_id]
        if not distance_profile_m:
            distance_profile_m.extend(edge["distance_profile_m"])
            elevation_profile_m.extend(edge["elevation_profile_m"])
        else:
            distance_profile_m.extend([round(distance_offset + value, 1) for value in edge["distance_profile_m"][1:]])
            elevation_profile_m.extend(edge["elevation_profile_m"][1:])
        distance_offset += float(edge["length_m"])
        surface_profile.append(edge["surface"])

    return {
        "snapped_edge_sequence": snapped_edge_sequence,
        "elevation_profile_m": elevation_profile_m,
        "distance_profile_m": distance_profile_m,
        "grade_profile_pct": build_grade_profile(
            distance_profile_m,
            elevation_profile_m,
            int(config["deterministic_knobs"]["grade_smoothing_window"]),
        ),
        "surface_profile": surface_profile,
        "distance_m": round(distance_profile_m[-1], 1),
        "match_ratio": round(match_ratio, 3),
    }


def route_from_gpx_phase2(path: Path, graph: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    active_config = load_region_config(DEFAULT_REGION_CONFIG) if config is None else config
    points = _decimate_gpx_points(load_gpx_points(path), 40.0)
    snapped = _snap_points_to_graph_phase2(points, graph, active_config)
    route = {
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
    route["grade_profile_pct"] = _smooth_series(route["grade_profile_pct"], 3)
    return route
