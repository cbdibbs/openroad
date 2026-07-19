from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGION_DIR = ROOT / "region-data" / "milwaukee" / "mke_phase2_region_pack"
REGION_MANIFEST = REGION_DIR / "region_manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copytree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True)


def package_release(version: str, macos_app: Path, output_dir: Path) -> list[Path]:
    region_manifest = json.loads(REGION_MANIFEST.read_text(encoding="utf-8"))
    region_version = region_manifest["region_version"]
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[Path] = []
    with tempfile.TemporaryDirectory(dir=output_dir) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        bundle_root = temp_dir / f"procedural-trainer-macos-v{version}"
        bundle_root.mkdir()

        _copytree(macos_app, bundle_root / macos_app.name)
        _copytree(REGION_DIR, bundle_root / "region-data" / "milwaukee" / REGION_DIR.name)
        geo_pipeline_root = bundle_root / "geo-pipeline"
        geo_pipeline_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "geo-pipeline" / "run_geo_pipeline_cli.py", geo_pipeline_root / "run_geo_pipeline_cli.py")
        _copytree(ROOT / "geo-pipeline" / "geo_pipeline", geo_pipeline_root / "geo_pipeline")
        sample_tracks_dir = bundle_root / "sample-tracks"
        sample_tracks_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "sample-tracks" / "Wauwatosa_to_Lakefront.gpx", sample_tracks_dir / "Wauwatosa_to_Lakefront.gpx")
        shutil.copy2(ROOT / "LICENSE", bundle_root / "LICENSE")
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", bundle_root / "THIRD_PARTY_NOTICES.md")

        release_notes = bundle_root / "README_RELEASE.txt"
        release_notes.write_text(
            "Procedural Trainer macOS release\n"
            "\n"
            "Contents\n"
            "- Procedural Trainer.app\n"
            "- region-data/milwaukee/mke_phase2_region_pack\n"
            "- sample-tracks/Wauwatosa_to_Lakefront.gpx\n"
            "- geo-pipeline/ for GPX snapping support\n"
            "\n"
            "Notes\n"
            "- Starter routes work out of the box from the bundled Milwaukee Phase 2 pack.\n"
            "- GPX import shells out to python3 and the bundled geo-pipeline CLI, so local Python 3 is still required for imported routes.\n"
            "- Region data remains separately licensed from the repository MIT code; see THIRD_PARTY_NOTICES.md and the bundled attribution manifests.\n",
            encoding="utf-8",
        )

        app_zip_base = output_dir / f"procedural-trainer-macos-v{version}"
        app_zip = Path(shutil.make_archive(str(app_zip_base), "zip", temp_dir, bundle_root.name))
        artifacts.append(app_zip)

    region_zip_base = output_dir / f"milwaukee-phase2-region-pack-{region_version}"
    region_zip = Path(shutil.make_archive(str(region_zip_base), "zip", REGION_DIR.parent, REGION_DIR.name))
    artifacts.append(region_zip)

    manifest_path = output_dir / "release-bundle-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "app_version": version,
                "region_version": region_version,
                "artifacts": [path.name for path in artifacts],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts.append(manifest_path)

    checksums_path = output_dir / "SHA256SUMS.txt"
    checksums_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in artifacts),
        encoding="utf-8",
    )
    artifacts.append(checksums_path)
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--macos-app", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    artifacts = package_release(args.version, args.macos_app, args.output_dir)
    for artifact in artifacts:
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
