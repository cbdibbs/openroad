from __future__ import annotations

import argparse
from pathlib import Path

from geo_pipeline.contracts import ValidationError, load_json, validate_region_pack_directory
from geo_pipeline.determinism import content_hash


def _validate_region(path: Path) -> int:
    region = validate_region_pack_directory(path)
    manifest_hash = content_hash(region["manifest"])
    print(f"validated {path}")
    print(f"manifest_hash={manifest_hash}")
    print(f"routes={len(region['routes'])}")
    return 0


def _hash_file(path: Path) -> int:
    data = load_json(path)
    print(content_hash(data))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="procedural-trainer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_region = subparsers.add_parser("validate-region", help="validate a region pack")
    validate_region.add_argument("path", type=Path)

    hash_json = subparsers.add_parser("hash-json", help="hash a JSON file canonically")
    hash_json.add_argument("path", type=Path)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "validate-region":
            return _validate_region(args.path)
        if args.command == "hash-json":
            return _hash_file(args.path)
    except ValidationError as exc:
        print(f"validation error: {exc}")
        return 1

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
