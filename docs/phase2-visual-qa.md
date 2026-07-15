# Phase 2 Visual QA

Use this checklist when validating the Milwaukee Phase 2 acceptance pack in the Godot client.

## Route

- Route id: `starter_wauwatosa_lakefront`
- Camera mode: `third_person_follow`
- Runtime command:

```bash
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli build-phase2-region milwaukee_phase2
game-client/godot/run_local.sh
```

## Path

1. Start `starter_wauwatosa_lakefront`.
2. Ride through the first west-to-east corridor until at least three `1 km` tile seams have passed under the rider.
3. Continue until the HUD reports a change in loaded `4 km` stream regions.
4. Restart once and repeat the same segment to confirm deterministic streaming behavior.

## Acceptance Checks

- No visible vertical pop where terrain crosses tile seams.
- No visible road jump where the route crosses tile seams.
- No missing road ribbon when adjacent stream regions load or unload.
- Buildings and prop placement stay grounded on the terrain surface.
- HUD route progression continues uninterrupted while region ownership changes.
