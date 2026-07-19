class_name ProceduralTrainerRegionPackLoader
extends RefCounted

const REQUIRED_PHASE1_CLIENT_ID := "godot-phase1"
const REQUIRED_PHASE2_CLIENT_ID := "godot-phase2"
const RELEASE_ROOT_ENV := "PT_RELEASE_ROOT"


func resolve_repo_relative_path(path: String) -> String:
	if path.strip_edges() == "":
		return ""
	if path.begins_with("res://") or path.begins_with("user://"):
		return ProjectSettings.globalize_path(path).simplify_path()
	if path.is_absolute_path():
		return path.simplify_path()
	for root in _candidate_runtime_roots():
		for variant in _path_variants(path):
			var candidate := root.path_join(variant).simplify_path()
			if FileAccess.file_exists(candidate) or DirAccess.dir_exists_absolute(candidate):
				return candidate
	return ProjectSettings.globalize_path("res://%s" % path).simplify_path()


func _candidate_runtime_roots() -> Array[String]:
	var roots: Array[String] = []
	var release_root := OS.get_environment(RELEASE_ROOT_ENV).strip_edges()
	if release_root != "":
		_collect_parent_roots(release_root, roots)
	_collect_parent_roots(ProjectSettings.globalize_path("res://"), roots)
	var executable_path := OS.get_executable_path().strip_edges()
	if executable_path != "":
		_collect_parent_roots(executable_path.get_base_dir(), roots)
	return roots


func _collect_parent_roots(start_path: String, roots: Array[String]) -> void:
	var current := start_path.simplify_path()
	for _index in range(8):
		if current == "" or roots.has(current):
			break
		roots.append(current)
		var parent := current.get_base_dir().simplify_path()
		if parent == current:
			break
		current = parent


func _path_variants(path: String) -> Array[String]:
	var variants: Array[String] = []
	var current := path.strip_edges()
	while current.begins_with("./"):
		current = current.substr(2)
	if current != "":
		variants.append(current)
	var trimmed := current
	while trimmed.begins_with("../"):
		trimmed = trimmed.substr(3)
		if trimmed != "" and not variants.has(trimmed):
			variants.append(trimmed)
	return variants


func load_region_pack(region_dir: String) -> Dictionary:
	if FileAccess.file_exists(region_dir.path_join("region_manifest.json")):
		return _load_phase2_region_pack(region_dir)
	return _load_phase1_region_pack(region_dir)


func load_tile_pack(region_dir: String, manifest_asset: String) -> Dictionary:
	var manifest := _read_json(region_dir.path_join(manifest_asset))
	if manifest.is_empty():
		return {"ok": false, "error": "tile manifest could not be loaded", "path": manifest_asset}
	var ride_graph := _read_json(region_dir.path_join(str(manifest["ride_graph_asset"])))
	var scenery := _read_json(region_dir.path_join(str(manifest["scenery_asset"])))
	if ride_graph.is_empty() or scenery.is_empty():
		return {"ok": false, "error": "tile assets could not be loaded", "path": manifest_asset}
	return {"ok": true, "tile": {"manifest": manifest, "ride_graph": ride_graph, "scenery": scenery}}


func _load_phase1_region_pack(region_dir: String) -> Dictionary:
	var manifest_path := region_dir.path_join("manifest.json")
	var manifest = _read_json(manifest_path)
	if manifest.is_empty():
		return {"ok": false, "error": "manifest.json could not be loaded", "path": manifest_path}
	var manifest_error := _validate_phase1_manifest(manifest)
	if manifest_error != "":
		return {"ok": false, "error": manifest_error, "path": manifest_path}

	var ride_graph = _read_json(region_dir.path_join(str(manifest["ride_graph_asset"])))
	var scenery = _read_json(region_dir.path_join(str(manifest["scenery_asset"])))
	var routes = _read_json(region_dir.path_join(str(manifest["route_definitions_asset"])))
	var attribution = _read_json(region_dir.path_join(str(manifest["attribution_asset"])))
	var source_manifest = _read_json(region_dir.path_join(str(manifest["source_manifest_asset"])))
	if ride_graph.is_empty() or scenery.is_empty() or routes.is_empty() or attribution.is_empty() or source_manifest.is_empty():
		return {"ok": false, "error": "region pack assets could not be loaded", "path": region_dir}

	return {
		"ok": true,
		"pack": {
			"pack_version": "phase1",
			"manifest": manifest,
			"ride_graph": ride_graph,
			"scenery": scenery,
			"routes": routes,
			"route_catalog": [],
			"streaming_regions": [],
			"scenery_index": {"tiles": []},
			"tile_index": {},
			"attribution": attribution,
			"source_manifest": source_manifest
		}
	}


func _load_phase2_region_pack(region_dir: String) -> Dictionary:
	var manifest_path := region_dir.path_join("region_manifest.json")
	var manifest = _read_json(manifest_path)
	if manifest.is_empty():
		return {"ok": false, "error": "region_manifest.json could not be loaded", "path": manifest_path}
	var manifest_error := _validate_phase2_manifest(manifest)
	if manifest_error != "":
		return {"ok": false, "error": manifest_error, "path": manifest_path}

	var ride_graph = _read_json(region_dir.path_join(str(manifest["ride_graph_asset"])))
	var routes = _read_json(region_dir.path_join(str(manifest["route_definitions_asset"])))
	var route_catalog = _read_json(region_dir.path_join(str(manifest["route_catalog_asset"])))
	var streaming_regions = _read_json(region_dir.path_join(str(manifest["streaming_regions_asset"])))
	var scenery_index = _read_json(region_dir.path_join(str(manifest["scenery_index_asset"])))
	var attribution = _read_json(region_dir.path_join(str(manifest["attribution_asset"])))
	var source_manifest = _read_json(region_dir.path_join(str(manifest["source_manifest_asset"])))
	if ride_graph.is_empty() or routes.is_empty() or route_catalog.is_empty() or streaming_regions.is_empty() or scenery_index.is_empty() or attribution.is_empty() or source_manifest.is_empty():
		return {"ok": false, "error": "phase2 region assets could not be loaded", "path": region_dir}

	var tile_index := {}
	for tile in scenery_index.get("tiles", []):
		tile_index[str(tile["tile_id"])] = tile

	var region_index := {}
	for region in streaming_regions:
		region_index[str(region["stream_region_id"])] = region

	return {
		"ok": true,
		"pack": {
			"pack_version": "phase2",
			"manifest": manifest,
			"ride_graph": ride_graph,
			"routes": routes,
			"route_catalog": route_catalog,
			"streaming_regions": streaming_regions,
			"streaming_region_index": region_index,
			"scenery_index": scenery_index,
			"tile_index": tile_index,
			"attribution": attribution,
			"source_manifest": source_manifest
		}
	}


func _read_json(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		return {}
	var handle := FileAccess.open(path, FileAccess.READ)
	if handle == null:
		return {}
	var parsed = JSON.parse_string(handle.get_as_text())
	if parsed == null:
		return {}
	return parsed


func _validate_phase1_manifest(manifest: Dictionary) -> String:
	for field in [
		"schema_version",
		"region_id",
		"corridor_id",
		"region_version",
		"compatible_clients",
		"ride_graph_asset",
		"scenery_asset",
		"route_definitions_asset",
		"attribution_asset",
		"source_manifest_asset"
	]:
		if not manifest.has(field):
			return "manifest missing required field: %s" % field
	var compatible_clients: Array = manifest["compatible_clients"]
	if REQUIRED_PHASE1_CLIENT_ID not in compatible_clients:
		return "manifest does not declare compatibility with %s" % REQUIRED_PHASE1_CLIENT_ID
	return ""


func _validate_phase2_manifest(manifest: Dictionary) -> String:
	for field in [
		"schema_version",
		"region_id",
		"corridor_id",
		"region_version",
		"compatible_clients",
		"ride_graph_asset",
		"route_catalog_asset",
		"route_definitions_asset",
		"streaming_regions_asset",
		"scenery_index_asset",
		"attribution_asset",
		"source_manifest_asset",
		"starter_route_ids"
	]:
		if not manifest.has(field):
			return "region manifest missing required field: %s" % field
	var compatible_clients: Array = manifest["compatible_clients"]
	if REQUIRED_PHASE2_CLIENT_ID not in compatible_clients:
		return "region manifest does not declare compatibility with %s" % REQUIRED_PHASE2_CLIENT_ID
	return ""
