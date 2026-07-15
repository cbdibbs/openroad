from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from geo_pipeline.contracts import ValidationError, load_json, validate_region_pack_directory
from geo_pipeline.phase2 import DEFAULT_REGION_CONFIG, build_phase2_region, load_region_config, route_from_gpx_phase2


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "geo-pipeline" / "geo_pipeline" / "configs" / "milwaukee_phase2.json"
REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_phase2_region_pack"
OAKLEAF_TRACK = ROOT / "region-data" / "milwaukee" / "oak_leaf_demo_loop.gpx"
SAMPLE_TRACK = ROOT / "sample-tracks" / "Wauwatosa_to_Lakefront.gpx"
VISUAL_QA_DOC = ROOT / "docs" / "phase2-visual-qa.md"


def _temp_phase2_config(temp_root: Path) -> Path:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["work_dirs"] = {
        "raw": str((temp_root / "raw").relative_to(ROOT)),
        "staged": str((temp_root / "staged").relative_to(ROOT)),
        "build": str((temp_root / "build").relative_to(ROOT)),
    }
    config["package_dir"] = str((temp_root / "package").relative_to(ROOT))
    config_path = temp_root / "milwaukee_phase2.temp.json"
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return config_path


def _tile_sceneries(region_dir: Path, scenery_index: dict[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for tile in scenery_index["tiles"]:
        tile_id = tile["tile_id"]
        tile_manifest_path = region_dir / tile["manifest_asset"]
        tile_manifest = load_json(tile_manifest_path)
        result[tile_id] = load_json(region_dir / tile_manifest["scenery_asset"])
    return result


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
        self.assertEqual(region["manifest"]["schema_version"], "phase2-region-root-v2")
        self.assertEqual(region["manifest"]["compatible_clients"], ["godot-phase2"])
        self.assertEqual(region["manifest"]["aoi_id"], "milwaukee_city_core_trails_v1")
        self.assertEqual(len(region["route_catalog"]), 4)
        self.assertGreaterEqual(len(region["streaming_regions"]), 4)
        self.assertGreaterEqual(len(region["scenery_index"]["tiles"]), 1)

    def test_phase2_double_build_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as first_dir_name, tempfile.TemporaryDirectory(dir=ROOT / "work") as second_dir_name:
            first_root = Path(first_dir_name)
            second_root = Path(second_dir_name)
            first_config = _temp_phase2_config(first_root)
            second_config = _temp_phase2_config(second_root)

            first_build = build_phase2_region(first_config)
            second_build = build_phase2_region(second_config)

            self.assertEqual(first_build["root_manifest"], second_build["root_manifest"])
            self.assertEqual(first_build["route_catalog"], second_build["route_catalog"])
            self.assertEqual(
                [edge["edge_id"] for edge in first_build["ride_graph"]["edges"]],
                [edge["edge_id"] for edge in second_build["ride_graph"]["edges"]],
            )
            self.assertEqual(
                [(tile["tile_id"], tile["seam_hashes"]) for tile in first_build["scenery_index"]["tiles"]],
                [(tile["tile_id"], tile["seam_hashes"]) for tile in second_build["scenery_index"]["tiles"]],
            )

            first_config_data = load_region_config(first_config)
            second_config_data = load_region_config(second_config)
            for gpx_path in [OAKLEAF_TRACK, SAMPLE_TRACK]:
                route_first = route_from_gpx_phase2(gpx_path, first_build["ride_graph"], first_config_data)
                route_second = route_from_gpx_phase2(gpx_path, second_build["ride_graph"], second_config_data)
                self.assertEqual(route_first["snapped_edge_sequence"], route_second["snapped_edge_sequence"])
                self.assertEqual(route_first["distance_profile_m"], route_second["distance_profile_m"])

    def test_required_sources_and_edge_lineage_are_present(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        artifacts = {artifact["source_id"]: artifact for artifact in region["source_manifest"]["artifacts"]}
        for source_id in ["openstreetmap", "usgs_3dep", "esa_worldcover"]:
            self.assertTrue(artifacts[source_id]["required"])
            self.assertTrue((ROOT / artifacts[source_id]["local_cache_path"]).exists())
        for edge in region["ride_graph"]["edges"]:
            self.assertEqual(edge["source_lineage"]["source_id"], "openstreetmap")
            self.assertIn(edge["source_lineage"]["source_feature_id"], edge["osm_way_id"])

    def test_optional_source_warning_is_optional_only(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        warnings = region["manifest"]["build_warnings"]
        self.assertTrue(any("optional source usda_naip" in warning for warning in warnings))
        self.assertFalse(any("openstreetmap" in warning for warning in warnings))
        self.assertFalse(any("usgs_3dep" in warning for warning in warnings))

    def test_adjacent_tile_seams_match_exactly(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        scenery_by_tile = _tile_sceneries(REGION_DIR, region["scenery_index"])
        tiles = {tile["tile_id"]: tile for tile in region["scenery_index"]["tiles"]}
        for tile_id in sorted(tiles):
            tile_x = int(tile_id.split("_")[1][1:])
            tile_y = int(tile_id.split("_")[2][1:])
            tile_chunk = scenery_by_tile[tile_id]["terrain_chunks"][0]
            east_neighbor = tiles.get(f"tile_x{tile_x + 1:02d}_y{tile_y:02d}")
            north_neighbor = tiles.get(f"tile_x{tile_x:02d}_y{tile_y + 1:02d}")
            if east_neighbor is not None:
                east_chunk = scenery_by_tile[east_neighbor["tile_id"]]["terrain_chunks"][0]
                self.assertEqual(tile_chunk["seam_samples_m"]["east"], east_chunk["seam_samples_m"]["west"])
                self.assertEqual(tile_chunk["seam_hashes"]["east"], east_chunk["seam_hashes"]["west"])
            if north_neighbor is not None:
                north_chunk = scenery_by_tile[north_neighbor["tile_id"]]["terrain_chunks"][0]
                self.assertEqual(tile_chunk["seam_samples_m"]["north"], north_chunk["seam_samples_m"]["south"])
                self.assertEqual(tile_chunk["seam_hashes"]["north"], north_chunk["seam_hashes"]["south"])

    def test_bridge_and_underpass_stay_separate_without_false_spikes(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        bridge_edges = [edge for edge in region["ride_graph"]["edges"] if edge["source_way_id"] == "way/6101"]
        tunnel_edges = [edge for edge in region["ride_graph"]["edges"] if edge["source_way_id"] == "way/6102"]
        self.assertTrue(bridge_edges)
        self.assertTrue(tunnel_edges)
        bridge_nodes = {edge["start_node_id"] for edge in bridge_edges} | {edge["end_node_id"] for edge in bridge_edges}
        tunnel_nodes = {edge["start_node_id"] for edge in tunnel_edges} | {edge["end_node_id"] for edge in tunnel_edges}
        self.assertTrue(bridge_nodes.isdisjoint(tunnel_nodes))

        route = next(route for route in region["routes"] if route["route_id"] == "starter_cross_city_connector")
        spikes = [abs(route["elevation_profile_m"][index] - route["elevation_profile_m"][index - 1]) for index in range(1, len(route["elevation_profile_m"]))]
        self.assertLess(max(spikes), 4.0)

    def test_fixture_gpx_snaps_are_deterministic_against_checked_in_pack(self) -> None:
        region = validate_region_pack_directory(REGION_DIR)
        config = load_region_config(DEFAULT_REGION_CONFIG)
        oak_first = route_from_gpx_phase2(OAKLEAF_TRACK, region["ride_graph"], config)
        oak_second = route_from_gpx_phase2(OAKLEAF_TRACK, region["ride_graph"], config)
        sample_first = route_from_gpx_phase2(SAMPLE_TRACK, region["ride_graph"], config)
        sample_second = route_from_gpx_phase2(SAMPLE_TRACK, region["ride_graph"], config)
        self.assertEqual(oak_first["snapped_edge_sequence"], oak_second["snapped_edge_sequence"])
        self.assertEqual(sample_first["snapped_edge_sequence"], sample_second["snapped_edge_sequence"])
        self.assertGreater(sample_first["distance_m"], 10000.0)

    def test_validate_region_fails_without_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            copied_region = temp_dir / "region_copy"
            shutil.copytree(REGION_DIR, copied_region)
            (copied_region / "source_manifest.json").unlink()
            with self.assertRaises((ValidationError, FileNotFoundError)):
                validate_region_pack_directory(copied_region)

    def test_visual_qa_path_is_documented_and_headless_smoke_is_repeatable(self) -> None:
        self.assertTrue(VISUAL_QA_DOC.exists())
        visual_qa = VISUAL_QA_DOC.read_text(encoding="utf-8")
        self.assertIn("starter_wauwatosa_lakefront", visual_qa)
        self.assertIn("third_person_follow", visual_qa)
        self.assertIn("tile seams", visual_qa)

        godot_bin = shutil.which("godot4") or shutil.which("godot")
        if godot_bin is None:
            self.skipTest("Godot executable not available in this environment")

        env = dict(os.environ)
        env["GODOT_BIN"] = godot_bin
        result = subprocess.run(
            ["zsh", "game-client/godot/test_headless.sh"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
