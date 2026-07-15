from __future__ import annotations

import argparse
import json
from pathlib import Path

from geo_pipeline.contracts import ValidationError, load_json, validate_region_pack_directory
from geo_pipeline.determinism import content_hash
from geo_pipeline.sample_data import (
    DEFAULT_GPX_PATH,
    DEFAULT_REGION_DIR,
    build_sample_region_pack,
    route_from_gpx,
    sample_ride_graph,
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
    route = route_from_gpx(gpx_path, region["ride_graph"])
    encoded = json.dumps(route, indent=2, sort_keys=True)
    if output_path is None:
        print(encoded)
    else:
        output_path.write_text(encoded + "\n", encoding="utf-8")
        print(f"wrote {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="procedural-trainer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_region = subparsers.add_parser("validate-region", help="validate a region pack")
    validate_region.add_argument("path", type=Path)

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
