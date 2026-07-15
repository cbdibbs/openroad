from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocsAndLayoutTests(unittest.TestCase):
    def test_repo_layout_exists(self) -> None:
        expected = [
            ROOT / "game-client" / "godot",
            ROOT / "geo-pipeline" / "geo_pipeline",
            ROOT / "region-data" / "milwaukee" / "mke_demo_region_pack",
            ROOT / "docs" / "source-policy.md",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"missing expected path: {path}")

    def test_root_readme_mentions_open_source_posture(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("open-source", readme)
        self.assertIn("Godot-first", readme)


if __name__ == "__main__":
    unittest.main()
