from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from geo_pipeline.determinism import content_hash, region_pack_hash


ROOT = Path(__file__).resolve().parents[2]


class ValidationError(ValueError):
    """Raised when a manifest violates the repository contracts."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _expect_type(data: Any, expected: type, field: str) -> None:
    if not isinstance(data, expected):
        raise ValidationError(f"{field} must be of type {expected.__name__}")


def _require_fields(data: dict[str, Any], fields: list[str], context: str) -> None:
    missing = [field for field in fields if field not in data]
    if missing:
        raise ValidationError(f"{context} missing required fields: {', '.join(sorted(missing))}")


def _validate_numeric_list(values: Any, expected_length: int | None, field: str) -> None:
    _expect_type(values, list, field)
    if expected_length is not None and len(values) != expected_length:
        raise ValidationError(f"{field} must contain {expected_length} entries")
    for index, value in enumerate(values):
        if not isinstance(value, (int, float)):
            raise ValidationError(f"{field}[{index}] must be numeric")


def _validate_sorted(entries: list[dict[str, Any]], key: str, context: str) -> None:
    values = [entry[key] for entry in entries]
    if values != sorted(values):
        raise ValidationError(f"{context} must be sorted by {key}")


def validate_region_tile_manifest(data: dict[str, Any]) -> None:
    _require_fields(
        data,
        [
            "schema_version",
            "region_id",
            "corridor_id",
            "tile_id",
            "bbox_wgs84",
            "region_version",
            "source_versions",
            "compatible_clients",
            "ride_graph_asset",
            "scenery_asset",
            "route_definitions_asset",
            "attribution_asset",
            "source_manifest_asset",
        ],
        "RegionTileManifest",
    )
    for field in [
        "schema_version",
        "region_id",
        "corridor_id",
        "tile_id",
        "region_version",
        "ride_graph_asset",
        "scenery_asset",
        "route_definitions_asset",
        "attribution_asset",
        "source_manifest_asset",
    ]:
        _expect_type(data[field], str, field)
    _validate_numeric_list(data["bbox_wgs84"], 4, "bbox_wgs84")
    _expect_type(data["source_versions"], dict, "source_versions")
    _expect_type(data["compatible_clients"], list, "compatible_clients")
    if "seam_hashes" in data:
        _expect_type(data["seam_hashes"], dict, "seam_hashes")


def validate_phase2_region_manifest(data: dict[str, Any]) -> None:
    _require_fields(
        data,
        [
            "schema_version",
            "region_id",
            "corridor_id",
            "region_version",
            "bbox_wgs84",
            "aoi_id",
            "aoi_hash",
            "source_versions",
            "compatible_clients",
            "tile_size_m",
            "streaming_region_size_m",
            "ride_graph_asset",
            "route_catalog_asset",
            "route_definitions_asset",
            "streaming_regions_asset",
            "scenery_index_asset",
            "attribution_asset",
            "source_manifest_asset",
            "starter_route_ids",
            "build_warnings",
            "toolchain_versions",
            "deterministic_build_knobs",
            "intermediate_schema_version",
            "visual_qa",
        ],
        "Phase2RegionManifest",
    )
    for field in [
        "schema_version",
        "region_id",
        "corridor_id",
        "region_version",
        "ride_graph_asset",
        "route_catalog_asset",
        "route_definitions_asset",
        "streaming_regions_asset",
        "scenery_index_asset",
        "attribution_asset",
        "source_manifest_asset",
        "aoi_id",
        "aoi_hash",
        "intermediate_schema_version",
    ]:
        _expect_type(data[field], str, field)
    _validate_numeric_list(data["bbox_wgs84"], 4, "bbox_wgs84")
    _expect_type(data["source_versions"], dict, "source_versions")
    _expect_type(data["compatible_clients"], list, "compatible_clients")
    _expect_type(data["starter_route_ids"], list, "starter_route_ids")
    _expect_type(data["build_warnings"], list, "build_warnings")
    _expect_type(data["toolchain_versions"], dict, "toolchain_versions")
    _expect_type(data["deterministic_build_knobs"], dict, "deterministic_build_knobs")
    _expect_type(data["visual_qa"], dict, "visual_qa")
    if not isinstance(data["tile_size_m"], (int, float)):
        raise ValidationError("tile_size_m must be numeric")
    if not isinstance(data["streaming_region_size_m"], (int, float)):
        raise ValidationError("streaming_region_size_m must be numeric")


def validate_ride_graph_pack(data: dict[str, Any], allow_empty: bool = False) -> None:
    require_source_lineage = str(data.get("graph_profile", "")).startswith("phase2")
    _require_fields(
        data,
        [
            "region_id",
            "corridor_id",
            "region_version",
            "graph_profile",
            "bbox_wgs84",
            "nodes",
            "edges",
        ],
        "RideGraphPack",
    )
    for field in ["region_id", "corridor_id", "region_version", "graph_profile"]:
        _expect_type(data[field], str, field)
    _validate_numeric_list(data["bbox_wgs84"], 4, "bbox_wgs84")
    _expect_type(data["nodes"], list, "nodes")
    _expect_type(data["edges"], list, "edges")
    if (not data["nodes"] or not data["edges"]) and not allow_empty:
        raise ValidationError("RideGraphPack must contain nodes and edges")

    node_ids: set[str] = set()
    for index, node in enumerate(data["nodes"]):
        _expect_type(node, dict, f"nodes[{index}]")
        _require_fields(node, ["node_id", "point_wgs84", "point_m", "junction_kind"], f"nodes[{index}]")
        _expect_type(node["node_id"], str, f"nodes[{index}].node_id")
        _validate_numeric_list(node["point_wgs84"], 2, f"nodes[{index}].point_wgs84")
        _validate_numeric_list(node["point_m"], 2, f"nodes[{index}].point_m")
        if "layer" in node:
            _expect_type(node["layer"], str, f"nodes[{index}].layer")
        if "tile_id" in node:
            _expect_type(node["tile_id"], str, f"nodes[{index}].tile_id")
        if "stream_region_id" in node:
            _expect_type(node["stream_region_id"], str, f"nodes[{index}].stream_region_id")
        node_ids.add(node["node_id"])

    for index, edge in enumerate(data["edges"]):
        _expect_type(edge, dict, f"edges[{index}]")
        _require_fields(
            edge,
            [
                "edge_id",
                "osm_way_id",
                "start_node_id",
                "end_node_id",
                "bike_access",
                "surface",
                "length_m",
                "geometry_wgs84",
                "geometry_m",
                "distance_profile_m",
                "elevation_profile_m",
            ],
            f"edges[{index}]",
        )
        if require_source_lineage and "source_lineage" not in edge:
            raise ValidationError(f"edges[{index}] missing required fields: source_lineage")
        for field in ["edge_id", "osm_way_id", "start_node_id", "end_node_id", "bike_access", "surface"]:
            _expect_type(edge[field], str, f"edges[{index}].{field}")
        if edge["start_node_id"] not in node_ids or edge["end_node_id"] not in node_ids:
            raise ValidationError("RideGraphPack edge references unknown node ids")
        if not isinstance(edge["length_m"], (int, float)):
            raise ValidationError("RideGraphPack edge length_m must be numeric")
        for field in ["geometry_wgs84", "geometry_m", "distance_profile_m", "elevation_profile_m"]:
            _expect_type(edge[field], list, f"edges[{index}].{field}")
        if len(edge["geometry_wgs84"]) != len(edge["geometry_m"]):
            raise ValidationError("RideGraphPack geometry_wgs84 and geometry_m must align")
        if len(edge["distance_profile_m"]) != len(edge["geometry_m"]):
            raise ValidationError("RideGraphPack distance_profile_m must align with geometry_m")
        if len(edge["elevation_profile_m"]) != len(edge["geometry_m"]):
            raise ValidationError("RideGraphPack elevation_profile_m must align with geometry_m")
        for field in ["layer", "structure", "tile_id", "stream_region_id", "source_way_id"]:
            if field in edge:
                _expect_type(edge[field], str, f"edges[{index}].{field}")
        if "source_segment_index" in edge and not isinstance(edge["source_segment_index"], int):
            raise ValidationError(f"edges[{index}].source_segment_index must be an integer")
        if "source_lineage" in edge:
            _expect_type(edge["source_lineage"], dict, f"edges[{index}].source_lineage")
            _require_fields(
                edge["source_lineage"],
                ["source_id", "source_feature_id", "source_dataset_path"],
                f"edges[{index}].source_lineage",
            )
            for field in ["source_id", "source_feature_id", "source_dataset_path"]:
                _expect_type(edge["source_lineage"][field], str, f"edges[{index}].source_lineage.{field}")


def validate_route_definition(data: dict[str, Any]) -> None:
    _require_fields(
        data,
        [
            "route_id",
            "source_type",
            "source_hash",
            "snapped_edge_sequence",
            "elevation_profile_m",
            "distance_profile_m",
            "grade_profile_pct",
            "surface_profile",
            "distance_m",
            "region_version",
        ],
        "RouteDefinition",
    )
    for field in ["route_id", "source_type", "source_hash", "region_version"]:
        _expect_type(data[field], str, field)
    for field in [
        "snapped_edge_sequence",
        "elevation_profile_m",
        "distance_profile_m",
        "grade_profile_pct",
        "surface_profile",
    ]:
        _expect_type(data[field], list, field)
    if not isinstance(data["distance_m"], (int, float)):
        raise ValidationError("distance_m must be numeric")
    if not data["snapped_edge_sequence"]:
        raise ValidationError("snapped_edge_sequence must not be empty")
    if len(data["surface_profile"]) != len(data["snapped_edge_sequence"]):
        raise ValidationError("surface_profile must align with snapped_edge_sequence")
    if len(data["elevation_profile_m"]) < 2:
        raise ValidationError("elevation_profile_m must contain at least two samples")
    if len(data["elevation_profile_m"]) != len(data["distance_profile_m"]):
        raise ValidationError("distance_profile_m must align with elevation_profile_m")
    if len(data["grade_profile_pct"]) != len(data["distance_profile_m"]):
        raise ValidationError("grade_profile_pct must align with distance_profile_m")
    if round(float(data["distance_profile_m"][-1]), 1) != round(float(data["distance_m"]), 1):
        raise ValidationError("distance_m must match the last distance_profile_m sample")


def validate_scenery_pack(data: dict[str, Any]) -> None:
    _require_fields(
        data,
        [
            "region_id",
            "corridor_id",
            "region_version",
            "terrain_chunks",
            "road_segments",
            "biome_patches",
            "style_hints",
        ],
        "SceneryPack",
    )
    for field in ["region_id", "corridor_id", "region_version"]:
        _expect_type(data[field], str, field)
    for field in ["terrain_chunks", "road_segments", "biome_patches"]:
        _expect_type(data[field], list, field)
    _expect_type(data["style_hints"], dict, "style_hints")
    if not data["terrain_chunks"]:
        raise ValidationError("SceneryPack must contain at least one terrain chunk")
    for index, chunk in enumerate(data["terrain_chunks"]):
        _expect_type(chunk, dict, f"terrain_chunks[{index}]")
        _require_fields(chunk, ["chunk_id", "origin_m", "size_m", "elevation_grid_m"], f"terrain_chunks[{index}]")
        _validate_numeric_list(chunk["origin_m"], 2, f"terrain_chunks[{index}].origin_m")
        _validate_numeric_list(chunk["size_m"], 2, f"terrain_chunks[{index}].size_m")
        _expect_type(chunk["elevation_grid_m"], list, f"terrain_chunks[{index}].elevation_grid_m")
        if "grid_resolution" in chunk and not isinstance(chunk["grid_resolution"], int):
            raise ValidationError(f"terrain_chunks[{index}].grid_resolution must be an integer")
        if "sample_spacing_m" in chunk and not isinstance(chunk["sample_spacing_m"], (int, float)):
            raise ValidationError(f"terrain_chunks[{index}].sample_spacing_m must be numeric")
        if "seam_samples_m" in chunk:
            _expect_type(chunk["seam_samples_m"], dict, f"terrain_chunks[{index}].seam_samples_m")
        if "seam_hashes" in chunk:
            _expect_type(chunk["seam_hashes"], dict, f"terrain_chunks[{index}].seam_hashes")
    for index, segment in enumerate(data["road_segments"]):
        _expect_type(segment, dict, f"road_segments[{index}]")
        _require_fields(segment, ["edge_id", "width_m", "material"], f"road_segments[{index}]")
    for index, biome in enumerate(data["biome_patches"]):
        _expect_type(biome, dict, f"biome_patches[{index}]")
        _require_fields(biome, ["biome_id", "landcover_class", "polygon_m", "color_hint"], f"biome_patches[{index}]")
    if "buildings" in data:
        _expect_type(data["buildings"], list, "buildings")
    if "prop_masks" in data:
        _expect_type(data["prop_masks"], list, "prop_masks")


def validate_source_manifest(data: dict[str, Any]) -> None:
    is_phase2 = str(data.get("schema_version", "")).startswith("phase2-")
    _require_fields(
        data,
        [
            "schema_version",
            "region_id",
            "corridor_id",
            "region_version",
            "generated_at",
            "artifacts",
        ],
        "SourceManifest",
    )
    for field in ["schema_version", "region_id", "corridor_id", "region_version", "generated_at"]:
        _expect_type(data[field], str, field)
    _expect_type(data["artifacts"], list, "artifacts")
    if not data["artifacts"]:
        raise ValidationError("SourceManifest artifacts must not be empty")
    if is_phase2:
        _validate_sorted(data["artifacts"], "source_id", "SourceManifest.artifacts")
    for index, artifact in enumerate(data["artifacts"]):
        _expect_type(artifact, dict, f"artifacts[{index}]")
        _require_fields(
            artifact,
            [
                "source_id",
                "name",
                "role",
                "fetch_url",
                "product_id",
                "version",
                "license",
                "attribution",
                "checksum_sha256",
                "retrieved_at",
            ],
            f"artifacts[{index}]",
        )
        if is_phase2:
            _require_fields(artifact, ["required", "optional", "local_cache_path"], f"artifacts[{index}]")
        else:
            _require_fields(artifact, ["local_filename"], f"artifacts[{index}]")
        for field in [
            "source_id",
            "name",
            "role",
            "fetch_url",
            "product_id",
            "version",
            "license",
            "attribution",
            "checksum_sha256",
            "retrieved_at",
        ]:
            _expect_type(artifact[field], str, f"artifacts[{index}].{field}")
        if is_phase2:
            _expect_type(artifact["local_cache_path"], str, f"artifacts[{index}].local_cache_path")
            if not isinstance(artifact["required"], bool) or not isinstance(artifact["optional"], bool):
                raise ValidationError(f"artifacts[{index}] required/optional flags must be booleans")
        else:
            _expect_type(artifact["local_filename"], str, f"artifacts[{index}].local_filename")


def validate_attribution_pack(data: dict[str, Any]) -> None:
    _require_fields(
        data,
        ["region_id", "region_version", "build_date", "region_hash", "sources", "notices"],
        "AttributionPack",
    )
    for field in ["region_id", "region_version", "build_date", "region_hash"]:
        _expect_type(data[field], str, field)
    _expect_type(data["sources"], list, "sources")
    _expect_type(data["notices"], list, "notices")
    if not data["sources"]:
        raise ValidationError("sources must not be empty")
    for index, source in enumerate(data["sources"]):
        _expect_type(source, dict, f"sources[{index}]")
        _require_fields(
            source,
            ["source_id", "name", "license", "version", "used_for", "attribution"],
            f"sources[{index}]",
        )
        for field in ["source_id", "name", "license", "version", "attribution"]:
            _expect_type(source[field], str, f"sources[{index}].{field}")
        _expect_type(source["used_for"], list, f"sources[{index}].used_for")


def _ensure_source_cache_paths(source_manifest: dict[str, Any]) -> None:
    for artifact in source_manifest["artifacts"]:
        if "local_cache_path" in artifact:
            cache_path = Path(artifact["local_cache_path"])
            if not cache_path.is_absolute():
                cache_path = ROOT / cache_path
            if artifact.get("required", False) and not cache_path.exists():
                raise ValidationError(f"required source artifact missing from local cache: {artifact['source_id']}")


def _validate_phase2_seams(region_dir: Path, scenery_index: dict[str, Any]) -> None:
    tile_by_id = {tile["tile_id"]: tile for tile in scenery_index["tiles"]}
    for tile in scenery_index["tiles"]:
        tile_x = int(tile["tile_id"].split("_")[1][1:])
        tile_y = int(tile["tile_id"].split("_")[2][1:])
        east_neighbor = tile_by_id.get(f"tile_x{tile_x + 1:02d}_y{tile_y:02d}")
        north_neighbor = tile_by_id.get(f"tile_x{tile_x:02d}_y{tile_y + 1:02d}")
        tile_scenery = load_json(region_dir / tile["manifest_asset"].replace("manifest.json", "scenery.json"))
        tile_chunk = tile_scenery["terrain_chunks"][0]
        if east_neighbor is not None:
            east_scenery = load_json(region_dir / east_neighbor["manifest_asset"].replace("manifest.json", "scenery.json"))
            east_chunk = east_scenery["terrain_chunks"][0]
            if tile_chunk["seam_samples_m"]["east"] != east_chunk["seam_samples_m"]["west"]:
                raise ValidationError(f"tile seam mismatch between {tile['tile_id']} east and {east_neighbor['tile_id']} west")
        if north_neighbor is not None:
            north_scenery = load_json(region_dir / north_neighbor["manifest_asset"].replace("manifest.json", "scenery.json"))
            north_chunk = north_scenery["terrain_chunks"][0]
            if tile_chunk["seam_samples_m"]["north"] != north_chunk["seam_samples_m"]["south"]:
                raise ValidationError(f"tile seam mismatch between {tile['tile_id']} north and {north_neighbor['tile_id']} south")


def _validate_route_edge_references(routes: list[dict[str, Any]], edge_ids: set[str]) -> None:
    for route in routes:
        validate_route_definition(route)
        unknown = [edge_id for edge_id in route["snapped_edge_sequence"] if edge_id not in edge_ids]
        if unknown:
            raise ValidationError(f"RouteDefinition references unknown edges: {', '.join(sorted(unknown))}")


def validate_region_pack_directory(region_dir: Path) -> dict[str, Any]:
    phase2_manifest_path = region_dir / "region_manifest.json"
    if phase2_manifest_path.exists():
        return validate_phase2_region_pack_directory(region_dir)

    manifest_path = region_dir / "manifest.json"
    manifest = load_json(manifest_path)
    validate_region_tile_manifest(manifest)
    ride_graph = load_json(region_dir / manifest["ride_graph_asset"])
    scenery = load_json(region_dir / manifest["scenery_asset"])
    routes = load_json(region_dir / manifest["route_definitions_asset"])
    attribution = load_json(region_dir / manifest["attribution_asset"])
    source_manifest = load_json(region_dir / manifest["source_manifest_asset"])
    validate_ride_graph_pack(ride_graph)
    validate_scenery_pack(scenery)
    validate_attribution_pack(attribution)
    validate_source_manifest(source_manifest)
    _ensure_source_cache_paths(source_manifest)
    if not isinstance(routes, list):
        raise ValidationError("routes.json must be a list")
    _validate_route_edge_references(routes, {edge["edge_id"] for edge in ride_graph["edges"]})
    attribution_by_source = {source["source_id"]: source for source in attribution["sources"]}
    manifest_by_source = {artifact["source_id"]: artifact for artifact in source_manifest["artifacts"]}
    if set(attribution_by_source) != set(manifest_by_source):
        raise ValidationError("AttributionPack sources must match SourceManifest artifacts")
    expected_hash = region_pack_hash(manifest, ride_graph, scenery, routes, attribution, source_manifest)
    if attribution["region_hash"] != expected_hash:
        raise ValidationError("AttributionPack region_hash does not match region contents")
    return {
        "manifest": manifest,
        "ride_graph": ride_graph,
        "scenery": scenery,
        "routes": routes,
        "attribution": attribution,
        "source_manifest": source_manifest,
    }


def validate_phase2_region_pack_directory(region_dir: Path) -> dict[str, Any]:
    manifest = load_json(region_dir / "region_manifest.json")
    validate_phase2_region_manifest(manifest)
    ride_graph = load_json(region_dir / manifest["ride_graph_asset"])
    route_catalog = load_json(region_dir / manifest["route_catalog_asset"])
    routes = load_json(region_dir / manifest["route_definitions_asset"])
    streaming_regions = load_json(region_dir / manifest["streaming_regions_asset"])
    scenery_index = load_json(region_dir / manifest["scenery_index_asset"])
    attribution = load_json(region_dir / manifest["attribution_asset"])
    source_manifest = load_json(region_dir / manifest["source_manifest_asset"])
    validate_ride_graph_pack(ride_graph)
    validate_attribution_pack(attribution)
    validate_source_manifest(source_manifest)
    _ensure_source_cache_paths(source_manifest)
    if not isinstance(route_catalog, list):
        raise ValidationError("route_catalog.json must be a list")
    if not isinstance(routes, list):
        raise ValidationError("routes.json must be a list")
    if not isinstance(streaming_regions, list):
        raise ValidationError("streaming_regions.json must be a list")
    if not isinstance(scenery_index, dict):
        raise ValidationError("scenery_index.json must be an object")
    _require_fields(scenery_index, ["tiles", "style_hints", "build_warnings"], "SceneryIndex")
    _expect_type(scenery_index["tiles"], list, "SceneryIndex.tiles")
    _validate_sorted(scenery_index["tiles"], "tile_id", "SceneryIndex.tiles")
    edge_ids = {edge["edge_id"] for edge in ride_graph["edges"]}
    _validate_route_edge_references(routes, edge_ids)
    route_ids = {route["route_id"] for route in routes}
    _validate_sorted(route_catalog, "route_id", "route_catalog")
    for entry in route_catalog:
        _expect_type(entry, dict, "route_catalog[]")
        _require_fields(
            entry,
            ["route_id", "display_name", "difficulty", "start_area", "distance_m", "elevation_gain_m", "preview_edge_id", "region_version"],
            "route_catalog[]",
        )
        if entry["route_id"] not in route_ids:
            raise ValidationError(f"route catalog references unknown route id {entry['route_id']}")
        if entry["preview_edge_id"] not in edge_ids:
            raise ValidationError(f"route catalog preview edge missing from ride graph: {entry['preview_edge_id']}")

    tile_manifest_assets = {tile["tile_id"]: tile["manifest_asset"] for tile in scenery_index["tiles"]}
    for tile in scenery_index["tiles"]:
        _expect_type(tile, dict, "SceneryIndex.tiles[]")
        _require_fields(tile, ["tile_id", "origin_m", "size_m", "stream_region_id", "manifest_asset", "seam_hashes"], "SceneryIndex.tiles[]")
        tile_manifest = load_json(region_dir / tile["manifest_asset"])
        validate_region_tile_manifest(tile_manifest)
        ride_graph_tile = load_json(region_dir / tile_manifest["ride_graph_asset"])
        scenery_tile = load_json(region_dir / tile_manifest["scenery_asset"])
        validate_ride_graph_pack(ride_graph_tile, allow_empty=True)
        validate_scenery_pack(scenery_tile)
        chunk = scenery_tile["terrain_chunks"][0]
        for field in ["grid_resolution", "sample_spacing_m", "seam_samples_m", "seam_hashes"]:
            if field not in chunk:
                raise ValidationError(f"phase2 terrain chunk missing required field: {field}")
        if tile_manifest.get("seam_hashes") != tile["seam_hashes"]:
            raise ValidationError(f"tile seam hashes differ between scenery index and tile manifest for {tile['tile_id']}")

    _validate_phase2_seams(region_dir, scenery_index)

    stream_region_ids: set[str] = set()
    for region in streaming_regions:
        _expect_type(region, dict, "streaming_regions[]")
        _require_fields(region, ["stream_region_id", "tile_ids", "origin_m", "size_m", "neighbor_region_ids"], "streaming_regions[]")
        stream_region_ids.add(region["stream_region_id"])
        for tile_id in region["tile_ids"]:
            if tile_id not in tile_manifest_assets:
                raise ValidationError(f"streaming region references unknown tile {tile_id}")

    if set(manifest["starter_route_ids"]) != {entry["route_id"] for entry in route_catalog}:
        raise ValidationError("starter_route_ids must match route catalog contents")

    attribution_by_source = {source["source_id"]: source for source in attribution["sources"]}
    manifest_by_source = {artifact["source_id"]: artifact for artifact in source_manifest["artifacts"]}
    if set(attribution_by_source) != set(manifest_by_source):
        raise ValidationError("AttributionPack sources must match SourceManifest artifacts")
    for edge in ride_graph["edges"]:
        if edge["source_lineage"]["source_id"] not in manifest_by_source:
            raise ValidationError(f"Ride graph edge missing traceable source artifact: {edge['edge_id']}")

    expected_hash = content_hash(
        {
            "root_manifest": manifest,
            "ride_graph": ride_graph,
            "routes": routes,
            "streaming_regions": streaming_regions,
            "scenery_index": scenery_index,
            "source_manifest": source_manifest,
            "attribution": {**attribution, "region_hash": "<computed>"},
        }
    )
    if attribution["region_hash"] != expected_hash:
        raise ValidationError("AttributionPack region_hash does not match Phase 2 region contents")

    return {
        "manifest": manifest,
        "ride_graph": ride_graph,
        "route_catalog": route_catalog,
        "routes": routes,
        "streaming_regions": streaming_regions,
        "scenery_index": scenery_index,
        "attribution": attribution,
        "source_manifest": source_manifest,
    }
    require_source_lineage = str(data.get("graph_profile", "")).startswith("phase2")
