class_name ProceduralTrainerRegionPackLoader
extends RefCounted

const REQUIRED_CLIENT_ID := "godot-phase1"


func resolve_repo_relative_path(path: String) -> String:
	if path.is_absolute_path():
		return path
	return ProjectSettings.globalize_path("res://%s" % path).simplify_path()


func load_region_pack(region_dir: String) -> Dictionary:
	var manifest_path := region_dir.path_join("manifest.json")
	var manifest = _read_json(manifest_path)
	if manifest.is_empty():
		return {"ok": false, "error": "manifest.json could not be loaded", "path": manifest_path}

	var manifest_error := _validate_manifest(manifest)
	if manifest_error != "":
		return {"ok": false, "error": manifest_error, "path": manifest_path}

	var ride_graph = _read_json(region_dir.path_join(str(manifest["ride_graph_asset"])))
	var scenery = _read_json(region_dir.path_join(str(manifest["scenery_asset"])))
	var routes = _read_json(region_dir.path_join(str(manifest["route_definitions_asset"])))
	var attribution = _read_json(region_dir.path_join(str(manifest["attribution_asset"])))

	if ride_graph.is_empty() or scenery.is_empty() or routes.is_empty() or attribution.is_empty():
		return {"ok": false, "error": "region pack assets could not be loaded", "path": region_dir}

	return {
		"ok": true,
		"pack": {
			"manifest": manifest,
			"ride_graph": ride_graph,
			"scenery": scenery,
			"routes": routes,
			"attribution": attribution
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


func _validate_manifest(manifest: Dictionary) -> String:
	for field in [
		"schema_version",
		"region_id",
		"corridor_id",
		"region_version",
		"compatible_clients",
		"ride_graph_asset",
		"scenery_asset",
		"route_definitions_asset",
		"attribution_asset"
	]:
		if not manifest.has(field):
			return "manifest missing required field: %s" % field

	var compatible_clients: Array = manifest["compatible_clients"]
	if REQUIRED_CLIENT_ID not in compatible_clients:
		return "manifest does not declare compatibility with %s" % REQUIRED_CLIENT_ID

	return ""
