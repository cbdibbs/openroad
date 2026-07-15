from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from geo_pipeline.determinism import content_hash


@dataclass(frozen=True)
class GpxPoint:
    latitude: float
    longitude: float
    elevation_m: float | None = None


def load_gpx_points(path: Path) -> list[GpxPoint]:
    tree = ElementTree.parse(path)
    root = tree.getroot()
    points: list[GpxPoint] = []

    for track_point in root.findall(".//{*}trkpt"):
        elevation_text = track_point.findtext("{*}ele")
        elevation_m = float(elevation_text) if elevation_text is not None else None
        points.append(
            GpxPoint(
                latitude=float(track_point.attrib["lat"]),
                longitude=float(track_point.attrib["lon"]),
                elevation_m=elevation_m,
            )
        )

    if not points:
        raise ValueError(f"GPX file has no track points: {path}")

    return points


def normalized_gpx_payload(points: list[GpxPoint]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for point in points:
        item: dict[str, Any] = {
            "lat": round(point.latitude, 6),
            "lon": round(point.longitude, 6),
        }
        if point.elevation_m is not None:
            item["ele"] = round(point.elevation_m, 2)
        normalized.append(item)
    return normalized


def gpx_source_hash(points: list[GpxPoint]) -> str:
    return f"gpxsha256:{content_hash(normalized_gpx_payload(points))}"
