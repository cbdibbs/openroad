from __future__ import annotations

from hashlib import sha256
from typing import Any

import json


def canonical_json_bytes(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def content_hash(data: Any) -> str:
    return sha256(canonical_json_bytes(data)).hexdigest()


def region_pack_hash(
    manifest: Any, ride_graph: Any, scenery: Any, routes: Any, attribution: Any, source_manifest: Any
) -> str:
    attribution_without_hash = dict(attribution)
    attribution_without_hash["region_hash"] = "<computed>"
    return content_hash(
        {
            "manifest": manifest,
            "ride_graph": ride_graph,
            "scenery": scenery,
            "routes": routes,
            "attribution": attribution_without_hash,
            "source_manifest": source_manifest,
        }
    )
