from __future__ import annotations

import argparse
import re
from pathlib import Path


def stamp_version(path: Path, version: str) -> None:
    content = path.read_text(encoding="utf-8")
    updated = re.sub(
        r'^(application/(?:short_version|version)="?)([^"]+)("?)$',
        lambda match: f"{match.group(1)}{version}{match.group(3)}",
        content,
        flags=re.MULTILINE,
    )
    path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--preset",
        type=Path,
        default=Path("game-client/godot/export_presets.cfg"),
    )
    args = parser.parse_args()
    stamp_version(args.preset, args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
