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
            ROOT / "region-data" / "milwaukee" / "oak_leaf_demo_loop.gpx",
            ROOT / "docs" / "source-policy.md",
            ROOT / "docs" / "roadmap.md",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"missing expected path: {path}")

    def test_root_readme_mentions_open_source_posture(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("open-source", readme)
        self.assertIn("Godot-first", readme)
        self.assertIn("build-phase1-region", readme)

    def test_roadmap_covers_remaining_phases(self) -> None:
        roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
        for phase in [
            "Phase 1: Milwaukee Technical Proof",
            "Phase 2: Canonical Route And World Packs",
            "Phase 3: Trainer Loop And Ghosts",
            "Phase 4: Open Distribution Workflow",
        ]:
            self.assertIn(phase, roadmap)


if __name__ == "__main__":
    unittest.main()
