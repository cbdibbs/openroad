from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "geo-pipeline")
    return env


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


def _run_command(name: str, command: list[str], logs_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    start = time.monotonic()
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    duration_s = round(time.monotonic() - start, 2)
    combined = _combined_output(result)
    log_path = logs_dir / f"{name}.log"
    log_path.write_text(combined, encoding="utf-8")
    return {
        "name": name,
        "command": command,
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "duration_s": duration_s,
        "log_path": str(log_path.resolve().relative_to(ROOT.resolve())),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _parse_unittest(check: dict[str, Any]) -> dict[str, Any]:
    combined = _combined_output(
        subprocess.CompletedProcess(check["command"], check["returncode"], check["stdout"], check["stderr"])
    )
    match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", combined)
    details: dict[str, Any] = {
        "status_line": "OK" if "\nOK" in combined or combined.strip().endswith("OK") else "FAILED",
    }
    if match is not None:
        details["tests_ran"] = int(match.group(1))
        details["reported_duration_s"] = float(match.group(2))
    return details


def _parse_validate_region(check: dict[str, Any]) -> dict[str, Any]:
    return json.loads(check["stdout"])


def _run_headless(logs_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    results_path = logs_dir / "headless-results.json"
    headless_env = dict(env)
    headless_env["PT_HEADLESS_RESULTS_PATH"] = str(results_path)
    check = _run_command(
        "godot-headless",
        ["zsh", "game-client/godot/test_headless.sh"],
        logs_dir,
        headless_env,
    )
    details: dict[str, Any] = {}
    if results_path.exists():
        details = json.loads(results_path.read_text(encoding="utf-8"))
    check["details"] = details
    return check


def run_suite(output_path: Path) -> dict[str, Any]:
    logs_dir = output_path.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    env = _base_env()

    checks: list[dict[str, Any]] = []

    for name, command in [
        ("bootstrap-phase1-sources", [sys.executable, "-m", "geo_pipeline.cli", "fetch-sources", "milwaukee_phase1"]),
        (
            "bootstrap-phase2-sources",
            [sys.executable, "-m", "geo_pipeline.cli", "fetch-sources", "milwaukee_phase2", "--source-mode", "fixture"],
        ),
    ]:
        bootstrap = _run_command(name, command, logs_dir, env)
        bootstrap["details"] = {"kind": "bootstrap"}
        checks.append(bootstrap)

    tests = _run_command(
        "python-unittest",
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        logs_dir,
        env,
    )
    tests["details"] = _parse_unittest(tests)
    checks.append(tests)

    for name, region_path in [
        ("validate-phase1-pack", "region-data/milwaukee/mke_demo_region_pack"),
        ("validate-phase2-pack", "region-data/milwaukee/mke_phase2_region_pack"),
    ]:
        validate = _run_command(
            name,
            [sys.executable, "-m", "geo_pipeline.cli", "validate-region", region_path, "--json"],
            logs_dir,
            env,
        )
        if validate["passed"]:
            validate["details"] = _parse_validate_region(validate)
        checks.append(validate)

    checks.append(_run_headless(logs_dir, env))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": os.environ.get("GITHUB_SHA", ""),
        "all_passed": all(check["passed"] for check in checks),
        "checks": checks,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run_suite(args.output)
    print(f"wrote {args.output}")
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
