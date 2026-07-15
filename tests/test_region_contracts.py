from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from geo_pipeline.contracts import ValidationError, load_json, validate_region_pack_directory
from geo_pipeline.determinism import content_hash
from geo_pipeline.sample_data import DEFAULT_GPX_PATH, build_sample_region_pack, route_from_gpx


ROOT = Path(__file__).resolve().parents[1]
REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_demo_region_pack"


class RegionContractTests(unittest.TestCase):
    def test_sample_region_pack_validates(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        self.assertEqual(region["manifest"]["region_version"], "milwaukee-v1.0.0")
        self.assertEqual(region["routes"][0]["route_id"], "oak_leaf_demo_loop")
        self.assertEqual(region["ride_graph"]["graph_profile"], "phase1-corridor-v1")

    def test_manifest_hash_is_deterministic(self) -> None:
        manifest = load_json(REGION_DIR / "manifest.json")
        first = content_hash(manifest)
        second = content_hash(load_json(REGION_DIR / "manifest.json"))
        self.assertEqual(first, second)

    def test_attribution_has_required_sources(self) -> None:
        attribution = load_json(REGION_DIR / "attribution.json")
        source_names = {entry["name"] for entry in attribution["sources"]}
        self.assertTrue(
            {"OpenStreetMap", "USGS 3DEP", "USDA NAIP", "ESA WorldCover"} <= source_names
        )

    def test_route_surface_alignment_is_enforced(self) -> None:
        bad_route = load_json(REGION_DIR / "routes.json")[0]
        bad_route["surface_profile"] = ["asphalt"]

        from geo_pipeline.contracts import validate_route_definition

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

    def test_gpx_snap_is_deterministic_for_sample_corridor(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        first = route_from_gpx(DEFAULT_GPX_PATH, region["ride_graph"])
        second = route_from_gpx(DEFAULT_GPX_PATH, region["ride_graph"])

        self.assertEqual(first, second)
        self.assertEqual(
            first["snapped_edge_sequence"],
            ["osm_edge_1001", "osm_edge_1002", "osm_edge_1008", "osm_edge_1015"],
        )
        self.assertGreaterEqual(len(first["elevation_profile_m"]), 5)


if __name__ == "__main__":
    unittest.main()
