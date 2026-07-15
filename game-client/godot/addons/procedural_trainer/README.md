# Procedural Trainer Godot Addon

This addon namespace is reserved for:

- region-pack manifest loading
- content-version compatibility checks
- route and scenery asset discovery
- trainer/native bridge integration hooks

Game logic should consume region packs through these boundaries rather than hardcoding source-specific assumptions.

The Phase 1 implementation adds `region_pack_loader.gd` as the first client boundary for:

- manifest compatibility checks against `compatible_clients`
- JSON asset discovery for ride graph, scenery, routes, and attribution
- filesystem-based region-pack loading without moving bake logic into Godot
