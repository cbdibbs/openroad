from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from geo_pipeline.determinism import region_pack_hash


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
        joined = ", ".join(sorted(missing))
        raise ValidationError(f"{context} missing required fields: {joined}")


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
    for field in ["schema_version", "region_id", "corridor_id", "tile_id", "region_version"]:
        _expect_type(data[field], str, field)
    _expect_type(data["source_versions"], dict, "source_versions")
    _expect_type(data["compatible_clients"], list, "compatible_clients")
    _expect_type(data["bbox_wgs84"], list, "bbox_wgs84")
    if len(data["bbox_wgs84"]) != 4:
        raise ValidationError("bbox_wgs84 must contain [west, south, east, north]")
    for index, value in enumerate(data["bbox_wgs84"]):
        if not isinstance(value, (int, float)):
            raise ValidationError(f"bbox_wgs84[{index}] must be numeric")
    for field in [
        "ride_graph_asset",
        "scenery_asset",
        "route_definitions_asset",
        "attribution_asset",
        "source_manifest_asset",
    ]:
        _expect_type(data[field], str, field)


def validate_ride_graph_pack(data: dict[str, Any]) -> None:
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
    _expect_type(data["nodes"], list, "nodes")
    _expect_type(data["edges"], list, "edges")
    if not data["nodes"] or not data["edges"]:
        raise ValidationError("RideGraphPack must contain nodes and edges")

    node_ids: set[str] = set()
    for index, node in enumerate(data["nodes"]):
        _expect_type(node, dict, f"nodes[{index}]")
        _require_fields(node, ["node_id", "point_wgs84", "point_m", "junction_kind"], f"nodes[{index}]")
        node_ids.add(node["node_id"])
        _expect_type(node["node_id"], str, f"nodes[{index}].node_id")
        _expect_type(node["point_wgs84"], list, f"nodes[{index}].point_wgs84")
        _expect_type(node["point_m"], list, f"nodes[{index}].point_m")
        if len(node["point_wgs84"]) != 2 or len(node["point_m"]) != 2:
            raise ValidationError("RideGraphPack node points must have two coordinates")

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
        for field in [
            "edge_id",
            "osm_way_id",
            "start_node_id",
            "end_node_id",
            "bike_access",
            "surface",
        ]:
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
    for field in ["snapped_edge_sequence", "elevation_profile_m", "distance_profile_m", "grade_profile_pct", "surface_profile"]:
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
    for index, segment in enumerate(data["road_segments"]):
        _expect_type(segment, dict, f"road_segments[{index}]")
        _require_fields(segment, ["edge_id", "width_m", "material"], f"road_segments[{index}]")
    for index, biome in enumerate(data["biome_patches"]):
        _expect_type(biome, dict, f"biome_patches[{index}]")
        _require_fields(
            biome,
            ["biome_id", "landcover_class", "polygon_m", "color_hint"],
            f"biome_patches[{index}]",
        )


def validate_source_manifest(data: dict[str, Any]) -> None:
    _require_fields(
        data,
        ["schema_version", "region_id", "corridor_id", "region_version", "generated_at", "artifacts"],
        "SourceManifest",
    )
    for field in ["schema_version", "region_id", "corridor_id", "region_version", "generated_at"]:
        _expect_type(data[field], str, field)
    _expect_type(data["artifacts"], list, "artifacts")
    if not data["artifacts"]:
        raise ValidationError("SourceManifest artifacts must not be empty")
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
                "local_filename",
            ],
            f"artifacts[{index}]",
        )
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
            "local_filename",
        ]:
            _expect_type(artifact[field], str, f"artifacts[{index}].{field}")


def validate_attribution_pack(data: dict[str, Any]) -> None:
    _require_fields(
        data,
        [
            "region_id",
            "region_version",
            "build_date",
            "region_hash",
            "sources",
            "notices",
        ],
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


def validate_region_pack_directory(region_dir: Path) -> dict[str, Any]:
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

    if not isinstance(routes, list):
        raise ValidationError("routes.json must be a list")
    edge_ids = {edge["edge_id"] for edge in ride_graph["edges"]}
    for route in routes:
        validate_route_definition(route)
        unknown = [edge_id for edge_id in route["snapped_edge_sequence"] if edge_id not in edge_ids]
        if unknown:
            raise ValidationError(f"RouteDefinition references unknown edges: {', '.join(sorted(unknown))}")

    attribution_by_source = {source["source_id"]: source for source in attribution["sources"]}
    manifest_by_source = {artifact["source_id"]: artifact for artifact in source_manifest["artifacts"]}
    if set(attribution_by_source) != set(manifest_by_source):
        raise ValidationError("AttributionPack sources must match SourceManifest artifacts")
    for source_id, source in attribution_by_source.items():
        artifact = manifest_by_source[source_id]
        if source["version"] != artifact["version"] or source["name"] != artifact["name"]:
            raise ValidationError(f"AttributionPack source mismatch for {source_id}")

    packaged_files = {path.name for path in region_dir.iterdir() if path.is_file()}
    if any(name.lower().endswith((".tif", ".tiff", ".jpg", ".jpeg", ".png")) and "naip" in name.lower() for name in packaged_files):
        raise ValidationError("raw NAIP imagery must not be packaged in the region pack")

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
