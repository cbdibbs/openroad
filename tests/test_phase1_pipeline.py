from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Phase1CliTests(unittest.TestCase):
    def test_validate_region_json_output(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "geo-pipeline")
        validate = subprocess.run(
            [
                "python3",
                "-m",
                "geo_pipeline.cli",
                "validate-region",
                str(ROOT / "region-data" / "milwaukee" / "mke_demo_region_pack"),
                "--json",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        payload = json.loads(validate.stdout)
        self.assertEqual(payload["region_id"], "milwaukee_demo")
        self.assertEqual(payload["routes"], 1)
        self.assertGreater(payload["edges"], 1)

    def test_build_phase1_cli_and_snap_output(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "geo-pipeline")
        build = subprocess.run(
            ["python3", "-m", "geo_pipeline.cli", "build-phase1-region", "milwaukee_phase1"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertIn("built phase1 region milwaukee_phase1", build.stdout)

        output_path = ROOT / "work" / "builds" / "milwaukee_phase1" / "oak_leaf_demo_loop.route.json"
        snap = subprocess.run(
            [
                "python3",
                "-m",
                "geo_pipeline.cli",
                "snap-gpx",
                str(ROOT / "region-data" / "milwaukee" / "mke_demo_region_pack"),
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
        self.assertIn("distance_profile_m", route)


if __name__ == "__main__":
    unittest.main()
