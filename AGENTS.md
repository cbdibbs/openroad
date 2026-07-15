# AGENTS.md

## Project Intent

Procedural Trainer is intended to be a fully open-source, free desktop cycling game with:

- an engine-agnostic geospatial build pipeline
- a Godot-first client for the MVP
- versioned region-data artifacts with explicit provenance and attribution

Milwaukee is the first target region. The MVP prioritizes solo riding, GPX import, deterministic route snapping, stylized scenery, trainer resistance, and ghost playback.

## Non-Negotiable Constraints

- Keep the repo fully open-source. Do not introduce mandatory proprietary engines, SDKs, or paid data sources into the core build path.
- Preserve the separation between `game-client`, `geo-pipeline`, and `region-data`.
- Treat OSM-derived transportation data as ODbL-sensitive. Attribution and source lineage must remain explicit.
- Region packs are separate deliverables from code. Do not imply the root MIT license covers region data.
- Prefer open/publicly redistributable sources and document any new source before using it.

## Directory Guidance

- `game-client/godot/`: runtime client and integration boundaries only
- `geo-pipeline/`: ingestion, transforms, contracts, validation, and packaging helpers
- `region-data/`: versioned region packs and sample artifacts
- `docs/`: licensing, architecture, and contributor-facing policy
- `tests/`: determinism, attribution, and contract validation

## Change Priorities

1. Strengthen reproducibility and validation before adding convenience abstractions.
2. Keep schemas and packaging contracts engine-independent.
3. Favor bare-Python or low-friction tooling for local verification.
4. Add sample data and tests whenever a new contract is introduced.
5. Preserve deterministic outputs for the same source inputs wherever feasible.

## Implementation Notes For Future Agents

- Update `docs/source-policy.md` and `THIRD_PARTY_NOTICES.md` whenever adding or changing upstream data sources.
- Keep attribution machine-readable inside each region pack, not just in repo-level docs.
- If you add a new client or runtime target later, do it without moving bake logic into engine-specific code.
- Before expanding gameplay scope, keep Milwaukee and the sample-region workflow passing locally.
- Stage and commit coherent checkpoints rather than leaving large undocumented deltas.

## Verification Defaults

Use these commands unless the repo grows a better task runner:

```bash
PYTHONPATH=geo-pipeline python3 -m unittest discover -s tests
PYTHONPATH=geo-pipeline python3 -m geo_pipeline.cli validate-region region-data/milwaukee/mke_demo_region_pack
```
