from __future__ import annotations

import unittest
from pathlib import Path

from geo_pipeline.contracts import ValidationError, load_json, validate_region_pack_directory
from geo_pipeline.determinism import content_hash


ROOT = Path(__file__).resolve().parents[1]
REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_demo_region_pack"


class RegionContractTests(unittest.TestCase):
    def test_sample_region_pack_validates(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        self.assertEqual(region["manifest"]["region_version"], "milwaukee-v0.1.0")
        self.assertEqual(region["routes"][0]["route_id"], "oak_leaf_demo_loop")

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


if __name__ == "__main__":
    unittest.main()
