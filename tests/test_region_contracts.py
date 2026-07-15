from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from geo_pipeline.contracts import ValidationError, load_json, validate_region_pack_directory, validate_route_definition
from geo_pipeline.determinism import content_hash
from geo_pipeline.phase1 import (
    DEFAULT_GPX_PATH,
    DEFAULT_REGION_CONFIG,
    bike_access_for_tags,
    build_grade_profile,
    build_phase1_region,
    build_ride_graph,
    fetch_sources,
    load_region_config,
    route_from_gpx,
    stable_edge_id,
)
from geo_pipeline.sample_data import build_sample_region_pack


ROOT = Path(__file__).resolve().parents[1]
REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_demo_region_pack"


class RegionContractTests(unittest.TestCase):
    def test_sample_region_pack_validates(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        self.assertEqual(region["manifest"]["region_version"], "milwaukee-v1.1.0")
        self.assertEqual(region["routes"][0]["route_id"], "oak_leaf_demo_loop")
        self.assertEqual(region["ride_graph"]["graph_profile"], "phase1-corridor-v1")
        self.assertEqual(region["manifest"]["source_manifest_asset"], "source_manifest.json")

    def test_manifest_hash_is_deterministic(self) -> None:
        manifest = load_json(REGION_DIR / "manifest.json")
        first = content_hash(manifest)
        second = content_hash(load_json(REGION_DIR / "manifest.json"))
        self.assertEqual(first, second)

    def test_attribution_has_required_sources(self) -> None:
        attribution = load_json(REGION_DIR / "attribution.json")
        source_names = {entry["name"] for entry in attribution["sources"]}
        self.assertTrue({"OpenStreetMap", "USGS 3DEP", "USDA NAIP", "ESA WorldCover"} <= source_names)

    def test_route_profile_alignment_is_enforced(self) -> None:
        bad_route = load_json(REGION_DIR / "routes.json")[0]
        bad_route["grade_profile_pct"] = [1.0]
        with self.assertRaises(ValidationError):
            validate_route_definition(bad_route)

    def test_build_sample_region_pack_matches_checked_in_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            built = build_sample_region_pack(Path(temp_dir))
            checked_in = validate_region_pack_directory(REGION_DIR)
        self.assertEqual(built["manifest"], checked_in["manifest"])
        self.assertEqual(built["ride_graph"], checked_in["ride_graph"])
        self.assertEqual(built["scenery"], checked_in["scenery"])
        self.assertEqual(built["routes"], checked_in["routes"])
        self.assertEqual(built["attribution"], checked_in["attribution"])
        self.assertEqual(built["source_manifest"], checked_in["source_manifest"])

    def test_gpx_snap_is_deterministic_for_sample_corridor(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        config = load_region_config(DEFAULT_REGION_CONFIG)
        first = route_from_gpx(DEFAULT_GPX_PATH, region["ride_graph"], config)
        second = route_from_gpx(DEFAULT_GPX_PATH, region["ride_graph"], config)
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first["elevation_profile_m"]), 5)
        self.assertEqual(len(first["distance_profile_m"]), len(first["grade_profile_pct"]))

    def test_source_manifest_records_checksums(self) -> None:
        manifest = fetch_sources(DEFAULT_REGION_CONFIG)
        self.assertEqual(len(manifest["artifacts"]), 4)
        for artifact in manifest["artifacts"]:
            self.assertEqual(len(artifact["checksum_sha256"]), 64)
            self.assertTrue(artifact["local_filename"].startswith("work/raw/milwaukee_phase1/"))

    def test_bikeability_filter_rules(self) -> None:
        self.assertEqual(bike_access_for_tags({"highway": "cycleway", "bicycle": "designated"}), "designated")
        self.assertEqual(bike_access_for_tags({"highway": "path"}), "permitted")
        self.assertIsNone(bike_access_for_tags({"highway": "motorway"}))
        self.assertIsNone(bike_access_for_tags({"highway": "footway", "bicycle": "no"}))

    def test_stable_edge_id_is_deterministic(self) -> None:
        geometry = [[0.0, 0.0], [5.12345, 8.99999]]
        self.assertEqual(stable_edge_id("way/1001", geometry), stable_edge_id("way/1001", geometry))

    def test_grade_smoothing_is_deterministic(self) -> None:
        profile = build_grade_profile([0.0, 10.0, 20.0, 30.0], [0.0, 1.0, 3.0, 4.5], 3)
        self.assertEqual(profile, build_grade_profile([0.0, 10.0, 20.0, 30.0], [0.0, 1.0, 3.0, 4.5], 3))
        self.assertEqual(len(profile), 4)

    def test_build_phase1_region_produces_valid_pack(self) -> None:
        build_phase1_region(DEFAULT_REGION_CONFIG)
        region = validate_region_pack_directory(REGION_DIR)
        self.assertEqual(region["manifest"]["corridor_id"], "oak_leaf_demo")

    def test_no_raw_naip_is_packaged(self) -> None:
        packaged_names = {path.name for path in REGION_DIR.iterdir() if path.is_file()}
        self.assertFalse(any(name.lower().endswith((".tif", ".tiff", ".jpg", ".jpeg")) for name in packaged_names))


if __name__ == "__main__":
    unittest.main()
