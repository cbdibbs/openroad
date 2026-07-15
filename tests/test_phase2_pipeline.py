from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

from geo_pipeline.contracts import load_json, validate_region_pack_directory
from geo_pipeline.phase2 import DEFAULT_REGION_CONFIG, build_phase2_region


ROOT = Path(__file__).resolve().parents[1]
REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_phase2_region_pack"
SAMPLE_TRACK = ROOT / "sample-tracks" / "Wauwatosa_to_Lakefront.gpx"


class Phase2PipelineTests(unittest.TestCase):
    def test_build_phase2_cli_and_validate_output(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "geo-pipeline")
        build = subprocess.run(
            ["python3", "-m", "geo_pipeline.cli", "build-phase2-region", DEFAULT_REGION_CONFIG],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertIn("built phase2 region milwaukee_phase2", build.stdout)

        validate = subprocess.run(
            ["python3", "-m", "geo_pipeline.cli", "validate-region", str(REGION_DIR)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertIn("validated", validate.stdout)
        self.assertIn("routes=4", validate.stdout)

    def test_phase2_region_contracts_validate(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        self.assertEqual(region["manifest"]["schema_version"], "phase2-region-root-v1")
        self.assertEqual(region["manifest"]["compatible_clients"], ["godot-phase2"])
        self.assertEqual(len(region["route_catalog"]), 4)
        self.assertGreaterEqual(len(region["streaming_regions"]), 4)
        self.assertGreaterEqual(len(region["scenery_index"]["tiles"]), 1)

    def test_phase2_build_is_deterministic_for_checked_in_artifact(self) -> None:
        built = build_phase2_region(DEFAULT_REGION_CONFIG)
        checked_in = validate_region_pack_directory(REGION_DIR)
        self.assertEqual(built["root_manifest"], checked_in["manifest"])
        self.assertEqual(built["ride_graph"], checked_in["ride_graph"])
        self.assertEqual(built["routes"], checked_in["routes"])
        self.assertEqual(built["route_catalog"], checked_in["route_catalog"])
        self.assertEqual(built["streaming_regions"], checked_in["streaming_regions"])
        self.assertEqual(built["scenery_index"], checked_in["scenery_index"])

    def test_optional_source_degradation_is_visible(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        warnings = region["manifest"]["build_warnings"]
        self.assertTrue(any("optional source usda_naip" in warning for warning in warnings))
        source_manifest = load_json(REGION_DIR / "source_manifest.json")
        self.assertTrue(any(artifact.get("optional") for artifact in source_manifest["artifacts"]))

    def test_streaming_regions_reference_known_tiles(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        known_tiles = {tile["tile_id"] for tile in region["scenery_index"]["tiles"]}
        for stream_region in region["streaming_regions"]:
            self.assertTrue(set(stream_region["tile_ids"]) <= known_tiles)

    def test_starter_routes_span_multiple_stream_regions(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        edge_lookup = {edge["edge_id"]: edge for edge in region["ride_graph"]["edges"]}
        crossed = False
        for route in region["routes"]:
            region_ids = {edge_lookup[edge_id].get("stream_region_id") for edge_id in route["snapped_edge_sequence"]}
            if len(region_ids) > 1:
                crossed = True
        self.assertTrue(crossed)

    def test_bridge_and_underpass_are_kept_separate(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        ways = {edge["osm_way_id"]: edge for edge in region["ride_graph"]["edges"]}
        self.assertEqual(ways["way/bridge-3001"]["structure"], "bridge")
        self.assertEqual(ways["way/tunnel-3002"]["structure"], "underpass")
        self.assertNotEqual(ways["way/bridge-3001"]["start_node_id"], ways["way/tunnel-3002"]["start_node_id"])

    def test_gpx_snap_works_against_phase2_pack(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "geo-pipeline")
        output_path = ROOT / "work" / "builds" / "milwaukee_phase2" / "oak_leaf_demo_loop.phase2.route.json"
        snap = subprocess.run(
            [
                "python3",
                "-m",
                "geo_pipeline.cli",
                "snap-gpx",
                str(REGION_DIR),
                str(ROOT / "region-data" / "milwaukee" / "oak_leaf_demo_loop.gpx"),
                "--output",
                str(output_path),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertIn("wrote", snap.stdout)
        route = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertIn("grade_profile_pct", route)
        self.assertEqual(route["region_version"], "milwaukee-v2.0.0")

    def test_sample_track_snaps_and_is_baked_as_starter_route(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "geo-pipeline")
        output_path = ROOT / "work" / "builds" / "milwaukee_phase2" / "wauwatosa_to_lakefront.fixture.route.json"
        snap = subprocess.run(
            [
                "python3",
                "-m",
                "geo_pipeline.cli",
                "snap-gpx",
                str(REGION_DIR),
                str(SAMPLE_TRACK),
                "--output",
                str(output_path),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertIn("wrote", snap.stdout)
        route = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertGreater(route["distance_m"], 1000.0)

        region = validate_region_pack_directory(REGION_DIR)
        baked_ids = {entry["route_id"] for entry in region["route_catalog"]}
        self.assertIn("starter_wauwatosa_lakefront", baked_ids)


if __name__ == "__main__":
    unittest.main()
