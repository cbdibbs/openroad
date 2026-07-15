from __future__ import annotations

import argparse
import json
from pathlib import Path

from geo_pipeline.contracts import ValidationError, load_json, validate_region_pack_directory
from geo_pipeline.determinism import content_hash
from geo_pipeline.phase1 import (
    DEFAULT_REGION_CONFIG,
    build_phase1_region,
    build_ride_graph,
    build_scenery,
    fetch_sources,
    package_region,
    prepare_sources,
)
from geo_pipeline.phase2 import (
    DEFAULT_REGION_CONFIG as DEFAULT_PHASE2_REGION_CONFIG,
    build_phase2_region,
    route_from_gpx_phase2,
)
from geo_pipeline.sample_data import (
    DEFAULT_GPX_PATH,
    DEFAULT_REGION_DIR,
    build_sample_region_pack,
    route_from_gpx,
)


def _validate_region(path: Path) -> int:
    region = validate_region_pack_directory(path)
    manifest_hash = content_hash(region["manifest"])
    print(f"validated {path}")
    print(f"manifest_hash={manifest_hash}")
    print(f"edges={len(region['ride_graph']['edges'])}")
    print(f"routes={len(region['routes'])}")
    return 0


def _hash_file(path: Path) -> int:
    data = load_json(path)
    print(content_hash(data))
    return 0


def _build_sample_region(path: Path, gpx_path: Path) -> int:
    region = build_sample_region_pack(path, gpx_path)
    print(f"built {path}")
    print(f"region_version={region['manifest']['region_version']}")
    print(f"route_id={region['routes'][0]['route_id']}")
    return 0


def _snap_gpx(region_path: Path, gpx_path: Path, output_path: Path | None) -> int:
    region = validate_region_pack_directory(region_path)
    manifest = region["manifest"]
    route = route_from_gpx_phase2(gpx_path, region["ride_graph"]) if manifest["schema_version"].startswith("phase2-") else route_from_gpx(gpx_path, region["ride_graph"])
    encoded = json.dumps(route, indent=2, sort_keys=True)
    if output_path is None:
        print(encoded)
    else:
        output_path.write_text(encoded + "\n", encoding="utf-8")
        print(f"wrote {output_path}")
    return 0


def _fetch_sources(region_config: str) -> int:
    manifest = fetch_sources(region_config)
    print(f"fetched {region_config}")
    print(f"artifacts={len(manifest['artifacts'])}")
    return 0


def _prepare_sources(region_config: str) -> int:
    prepared = prepare_sources(region_config)
    print(f"prepared {region_config}")
    print(f"osm_features={len(prepared['osm_features'])}")
    return 0


def _build_ride_graph(region_config: str) -> int:
    ride_graph = build_ride_graph(region_config)
    print(f"built ride graph for {region_config}")
    print(f"edges={len(ride_graph['edges'])}")
    return 0


def _build_scenery(region_config: str) -> int:
    scenery = build_scenery(region_config)
    print(f"built scenery for {region_config}")
    print(f"tiles={len(scenery['tiles'])}")
    return 0


def _package_region(region_config: str) -> int:
    region = package_region(region_config)
    print(f"packaged {region_config}")
    print(f"region_version={region['manifest']['region_version']}")
    return 0


def _build_phase1_region(region_config: str) -> int:
    region = build_phase1_region(region_config)
    print(f"built phase1 region {region_config}")
    print(f"region_version={region['manifest']['region_version']}")
    return 0


def _build_phase2_region(region_config: str) -> int:
    region = build_phase2_region(region_config)
    print(f"built phase2 region {region_config}")
    print(f"region_version={region['root_manifest']['region_version']}")
    print(f"starter_routes={len(region['route_catalog'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="procedural-trainer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_region = subparsers.add_parser("validate-region", help="validate a region pack")
    validate_region.add_argument("path", type=Path)

    fetch_parser = subparsers.add_parser("fetch-sources", help="fetch or receipt raw source artifacts")
    fetch_parser.add_argument("region_config", nargs="?", default=DEFAULT_REGION_CONFIG)

    prepare_parser = subparsers.add_parser("prepare-sources", help="prepare staged corridor inputs")
    prepare_parser.add_argument("region_config", nargs="?", default=DEFAULT_REGION_CONFIG)

    ride_graph_parser = subparsers.add_parser("build-ride-graph", help="build ride graph from staged inputs")
    ride_graph_parser.add_argument("region_config", nargs="?", default=DEFAULT_REGION_CONFIG)

    scenery_parser = subparsers.add_parser("build-scenery", help="build scenery from staged inputs")
    scenery_parser.add_argument("region_config", nargs="?", default=DEFAULT_REGION_CONFIG)

    package_parser = subparsers.add_parser("package-region", help="write a packaged region pack")
    package_parser.add_argument("region_config", nargs="?", default=DEFAULT_REGION_CONFIG)

    phase1_parser = subparsers.add_parser("build-phase1-region", help="run the full Phase 1 region build")
    phase1_parser.add_argument("region_config", nargs="?", default=DEFAULT_REGION_CONFIG)

    phase2_parser = subparsers.add_parser("build-phase2-region", help="run the full Phase 2 region build")
    phase2_parser.add_argument("region_config", nargs="?", default=DEFAULT_PHASE2_REGION_CONFIG)

    hash_json = subparsers.add_parser("hash-json", help="hash a JSON file canonically")
    hash_json.add_argument("path", type=Path)

    build_region = subparsers.add_parser(
        "build-sample-region", help="build the deterministic Milwaukee Phase 1 sample region pack"
    )
    build_region.add_argument("path", nargs="?", default=DEFAULT_REGION_DIR, type=Path)
    build_region.add_argument("--gpx", default=DEFAULT_GPX_PATH, type=Path)

    snap_gpx = subparsers.add_parser(
        "snap-gpx", help="snap a GPX file to the canonical ride graph for a region pack"
    )
    snap_gpx.add_argument("region_path", type=Path)
    snap_gpx.add_argument("gpx_path", type=Path)
    snap_gpx.add_argument("--output", type=Path)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "validate-region":
            return _validate_region(args.path)
        if args.command == "fetch-sources":
            return _fetch_sources(args.region_config)
        if args.command == "prepare-sources":
            return _prepare_sources(args.region_config)
        if args.command == "build-ride-graph":
            return _build_ride_graph(args.region_config)
        if args.command == "build-scenery":
            return _build_scenery(args.region_config)
        if args.command == "package-region":
            return _package_region(args.region_config)
        if args.command == "build-phase1-region":
            return _build_phase1_region(args.region_config)
        if args.command == "build-phase2-region":
            return _build_phase2_region(args.region_config)
        if args.command == "hash-json":
            return _hash_file(args.path)
        if args.command == "build-sample-region":
            return _build_sample_region(args.path, args.gpx)
        if args.command == "snap-gpx":
            return _snap_gpx(args.region_path, args.gpx_path, args.output)
    except ValidationError as exc:
        print(f"validation error: {exc}")
        return 1

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
