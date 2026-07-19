from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _status(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _details_for(check: dict[str, Any]) -> str:
    details = check.get("details", {})
    name = check["name"]
    if name == "python-unittest":
        tests_ran = details.get("tests_ran", "?")
        return f"{tests_ran} tests"
    if name.startswith("validate-"):
        return f"edges={details.get('edges', '?')}, routes={details.get('routes', '?')}"
    if name == "godot-headless":
        return (
            f"loaded_snapshots={len(details.get('loaded_region_snapshots', []))}, "
            f"stream_regions={details.get('stream_region_count', '?')}, "
            f"progress_samples={len(details.get('progress_samples_m', []))}"
        )
    return ""


def _failure_block(checks: list[dict[str, Any]]) -> str:
    failures: list[str] = []
    for check in checks:
        if check["passed"]:
            continue
        combined = ((check.get("stdout") or "") + "\n" + (check.get("stderr") or "")).strip()
        tail = "\n".join(combined.splitlines()[-20:])
        failures.append(f"### {check['name']}\n\n```text\n{tail}\n```")
    return "\n\n".join(failures)


def render(summary: dict[str, Any]) -> str:
    overall = _status(summary["all_passed"])
    lines = [
        "<!-- procedural-trainer-ci-comment -->",
        f"## Procedural Trainer CI: {overall}",
        "",
        "| Check | Status | Duration | Details |",
        "| --- | --- | ---: | --- |",
    ]
    for check in summary["checks"]:
        lines.append(
            f"| `{check['name']}` | {_status(check['passed'])} | {check['duration_s']:.2f}s | {_details_for(check)} |"
        )
    headless = next((check for check in summary["checks"] if check["name"] == "godot-headless"), None)
    if headless is not None and headless.get("details"):
        details = headless["details"]
        runtime_errors = details.get("runtime_errors", [])
        lines.extend(
            [
                "",
                "### Headless Smoke",
                "",
                f"- Active route: `{details.get('active_route_id', 'unknown')}`",
                f"- Stream regions seen: `{details.get('stream_region_count', 0)}`",
                f"- Loaded region snapshots: `{len(details.get('loaded_region_snapshots', []))}`",
                f"- Runtime errors: `{len(runtime_errors)}`",
            ]
        )
    if not summary["all_passed"]:
        lines.extend(["", "### Failures", "", _failure_block(summary["checks"])])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    markdown = render(summary)
    if args.output is None:
        print(markdown, end="")
    else:
        args.output.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
