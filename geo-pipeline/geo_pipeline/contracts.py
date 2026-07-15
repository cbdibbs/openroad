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
        ],
        "RegionTileManifest",
    )
    for field in ["schema_version", "region_id", "corridor_id"]:
        _expect_type(data[field], str, field)
    _expect_type(data["tile_id"], str, "tile_id")
    _expect_type(data["region_version"], str, "region_version")
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
        for field in ["geometry_wgs84", "geometry_m", "elevation_profile_m"]:
            _expect_type(edge[field], list, f"edges[{index}].{field}")
        if len(edge["geometry_wgs84"]) != len(edge["geometry_m"]):
            raise ValidationError("RideGraphPack geometry_wgs84 and geometry_m must align")
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
            "surface_profile",
            "distance_m",
            "region_version",
        ],
        "RouteDefinition",
    )
    for field in ["route_id", "source_type", "source_hash", "region_version"]:
        _expect_type(data[field], str, field)
    _expect_type(data["snapped_edge_sequence"], list, "snapped_edge_sequence")
    _expect_type(data["elevation_profile_m"], list, "elevation_profile_m")
    _expect_type(data["surface_profile"], list, "surface_profile")
    if not isinstance(data["distance_m"], (int, float)):
        raise ValidationError("distance_m must be numeric")
    if not data["snapped_edge_sequence"]:
        raise ValidationError("snapped_edge_sequence must not be empty")
    if len(data["surface_profile"]) != len(data["snapped_edge_sequence"]):
        raise ValidationError("surface_profile must align with snapped_edge_sequence")
    if len(data["elevation_profile_m"]) < 2:
        raise ValidationError("elevation_profile_m must contain at least two samples")


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
        ],
        "SceneryPack",
    )
    for field in ["region_id", "corridor_id", "region_version"]:
        _expect_type(data[field], str, field)
    for field in ["terrain_chunks", "road_segments", "biome_patches"]:
        _expect_type(data[field], list, field)
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
            ["name", "license", "version", "used_for", "attribution"],
            f"sources[{index}]",
        )
        for field in ["name", "license", "version", "attribution"]:
            _expect_type(source[field], str, f"sources[{index}].{field}")
        _expect_type(source["used_for"], list, f"sources[{index}].used_for")


def validate_region_pack_directory(region_dir: Path) -> dict[str, Any]:
    manifest_path = region_dir / "manifest.json"
    manifest = load_json(manifest_path)
    validate_region_tile_manifest(manifest)

    ride_graph_path = region_dir / manifest["ride_graph_asset"]
    scenery_path = region_dir / manifest["scenery_asset"]
    routes_path = region_dir / manifest["route_definitions_asset"]
    attribution_path = region_dir / manifest["attribution_asset"]

    ride_graph = load_json(ride_graph_path)
    scenery = load_json(scenery_path)
    attribution = load_json(attribution_path)
    routes = load_json(routes_path)

    validate_ride_graph_pack(ride_graph)
    validate_scenery_pack(scenery)
    validate_attribution_pack(attribution)

    if not isinstance(routes, list):
        raise ValidationError("routes.json must be a list")
    edge_ids = {edge["edge_id"] for edge in ride_graph["edges"]}
    for route in routes:
        validate_route_definition(route)
        if route["region_version"] != manifest["region_version"]:
            raise ValidationError("route region_version must match manifest region_version")
        if not set(route["snapped_edge_sequence"]) <= edge_ids:
            raise ValidationError("route snapped_edge_sequence contains unknown edge ids")

    for payload_name, payload in [
        ("ride_graph", ride_graph),
        ("scenery", scenery),
        ("attribution", attribution),
    ]:
        if payload["region_id"] != manifest["region_id"]:
            raise ValidationError(f"{payload_name} region_id must match manifest region_id")
        if payload["region_version"] != manifest["region_version"]:
            raise ValidationError(f"{payload_name} region_version must match manifest region_version")
        if payload_name != "attribution" and payload["corridor_id"] != manifest["corridor_id"]:
            raise ValidationError(f"{payload_name} corridor_id must match manifest corridor_id")

    road_segment_edge_ids = {segment["edge_id"] for segment in scenery["road_segments"]}
    if not road_segment_edge_ids <= edge_ids:
        raise ValidationError("scenery road_segments reference unknown edge ids")

    expected_hash = region_pack_hash(manifest, ride_graph, scenery, routes, attribution)
    if attribution["region_hash"] != expected_hash:
        raise ValidationError("attribution region_hash does not match pack content")

    return {
        "manifest": manifest,
        "ride_graph": ride_graph,
        "scenery": scenery,
        "attribution": attribution,
        "routes": routes,
    }
