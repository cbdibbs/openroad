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
            "tile_id",
            "bbox_wgs84",
            "region_version",
            "source_versions",
            "ride_graph_asset",
            "terrain_asset",
            "building_asset",
            "biome_asset",
            "attribution_asset",
        ],
        "RegionTileManifest",
    )
    _expect_type(data["tile_id"], str, "tile_id")
    _expect_type(data["region_version"], str, "region_version")
    _expect_type(data["source_versions"], dict, "source_versions")
    _expect_type(data["bbox_wgs84"], list, "bbox_wgs84")
    if len(data["bbox_wgs84"]) != 4:
        raise ValidationError("bbox_wgs84 must contain [west, south, east, north]")
    for index, value in enumerate(data["bbox_wgs84"]):
        if not isinstance(value, (int, float)):
            raise ValidationError(f"bbox_wgs84[{index}] must be numeric")
    for field in [
        "ride_graph_asset",
        "terrain_asset",
        "building_asset",
        "biome_asset",
        "attribution_asset",
    ]:
        _expect_type(data[field], str, field)


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
    if len(data["surface_profile"]) != len(data["snapped_edge_sequence"]):
        raise ValidationError("surface_profile must align with snapped_edge_sequence")


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
    attribution_path = region_dir / "attribution.json"
    routes_path = region_dir / "routes.json"

    manifest = load_json(manifest_path)
    attribution = load_json(attribution_path)
    routes = load_json(routes_path)

    validate_region_tile_manifest(manifest)
    validate_attribution_pack(attribution)

    if not isinstance(routes, list):
        raise ValidationError("routes.json must be a list")
    for route in routes:
        validate_route_definition(route)
        if route["region_version"] != manifest["region_version"]:
            raise ValidationError("route region_version must match manifest region_version")

    if manifest["attribution_asset"] != "attribution.json":
        raise ValidationError("manifest attribution_asset must point to attribution.json")

    expected_hash = region_pack_hash(manifest, routes, attribution)
    if attribution["region_hash"] != expected_hash:
        raise ValidationError("attribution region_hash does not match pack content")

    return {
        "manifest": manifest,
        "attribution": attribution,
        "routes": routes,
    }
