extends Node3D

const RegionPackLoader = preload("res://addons/procedural_trainer/region_pack_loader.gd")

@export var region_pack_dir := "region-data/milwaukee/mke_phase2_region_pack"
@export var active_route_id := "starter_cross_city_connector"
@export var default_gpx_path := "sample-tracks/Wauwatosa_to_Lakefront.gpx"
@export var world_scale := 0.18
@export var elevation_scale := 0.24
@export var python_executable := "python3"
@export var snap_output_dir := ""
@export var rider_mass_kg := 82.0
@export var baseline_power_w := 180.0
@export var baseline_cadence_rpm := 90.0
@export var max_brake_pct := 100.0
@export var enable_low_poly_shading := true

const POWER_STEP_W := 25.0
const CADENCE_STEP_RPM := 5.0
const BRAKE_STEP_PCT := 10.0
const ROAD_SURFACE_CLEARANCE_M := 0.02
const CAMERA_FORWARD_OFFSET_M := 0.85
const CAMERA_HEIGHT_M := 1.55
const CAMERA_LOOKAHEAD_M := 32.0
const CAMERA_LOOK_LIFT_M := 1.35
const CAMERA_LERP_RATE := 10.0
const CAMERA_ROLL_DAMPING := 0.08
const COARSE_STREAM_REAR_M := 180.0
const COARSE_STREAM_FORWARD_M := 900.0
const COARSE_STREAM_BUFFER_M := 240.0
const DETAIL_STREAM_REAR_M := 45.0
const DETAIL_STREAM_FORWARD_M := 360.0
const DETAIL_STREAM_BUFFER_M := 120.0
const DETAIL_SAMPLE_STEP_M := 90.0
const COARSE_SAMPLE_STEP_M := 150.0
const TILE_CACHE_LIMIT := 8
const HUD_REFRESH_INTERVAL_S := 0.15

var _pack: Dictionary = {}
var _loader := RegionPackLoader.new()
var _region_dir := ""
var _route: Dictionary = {}
var _route_points: Array[Vector3] = []
var _route_distances_m: Array[float] = []
var _route_total_distance_m := 0.0
var _route_progress_m := 0.0
var _current_speed_mps := 0.0
var _simulated_power_w := baseline_power_w
var _simulated_cadence_rpm := baseline_cadence_rpm
var _brake_pct := 0.0
var _paused := false
var _overlay_visible := true
var _import_status := ""
var _selected_route_index := 0
var _loaded_tiles := {}
var _loaded_region_ids: Array[String] = []
var _runtime_errors: Array[String] = []
var _headless_test_enabled := false
var _headless_test_completed := false
var _headless_test_results_path := ""
var _headless_test_good_gpx := ""
var _headless_test_bad_gpx := ""
var _headless_test_state := "idle"
var _headless_test_failures: Array[String] = []
var _headless_test_progress_samples: Array[float] = []
var _headless_test_seen_regions: Array[String] = []
var _headless_test_detail_snapshots: Array[String] = []
var _headless_test_last_progress_m := -1.0
var _headless_test_elapsed_s := 0.0
var _camera_initialized := false
var _edge_lookup := {}
var _route_edge_segments := []
var _tile_rects := {}
var _tile_centers_m := {}
var _tile_pack_cache := {}
var _tile_cache_order: Array[String] = []
var _material_cache := {}
var _shared_mesh_cache := {}
var _hud_refresh_remaining_s := 0.0
var _route_grade_distances_m: Array[float] = []
var _route_grade_values_pct: Array[float] = []
var _max_loaded_tiles_seen := 0
var _max_detail_tiles_seen := 0
var _max_loaded_regions_seen := 0
var _max_node_count_seen := 0
var _headless_test_region_snapshots: Array[String] = []
var _headless_test_loaded_tile_snapshots: Array[String] = []

@onready var _loaded_tiles_root: Node3D = $LoadedTilesRoot
@onready var _rider: MeshInstance3D = $Rider
@onready var _camera: Camera3D = $Camera3D
@onready var _status_label: Label3D = $StatusLabel
@onready var _hud_label: Label = $CanvasLayer/HudLabel
@onready var _file_dialog: FileDialog = $ImportDialog


func _ready() -> void:
	_configure_headless_test()
	_region_dir = _loader.resolve_repo_relative_path(region_pack_dir)
	if not _load_pack():
		_finish_headless_test(1)
		return
	if _load_default_gpx_route():
		return
	if not _activate_route():
		_finish_headless_test(1)
		return


func _configure_headless_test() -> void:
	var region_override := OS.get_environment("PT_REGION_PACK_DIR").strip_edges()
	if region_override != "":
		region_pack_dir = region_override
	var gpx_override := OS.get_environment("PT_DEFAULT_GPX_PATH").strip_edges()
	if gpx_override != "":
		default_gpx_path = gpx_override
	var python_override := OS.get_environment("PT_PYTHON_EXECUTABLE").strip_edges()
	if python_override != "":
		python_executable = python_override
	_headless_test_enabled = OS.get_environment("PT_HEADLESS_ASSERT") == "1"
	if not _headless_test_enabled:
		return
	_headless_test_results_path = OS.get_environment("PT_HEADLESS_RESULTS_PATH")
	_headless_test_good_gpx = OS.get_environment("PT_HEADLESS_TEST_GPX")
	_headless_test_bad_gpx = OS.get_environment("PT_HEADLESS_BAD_GPX")
	if _headless_test_bad_gpx == "":
		_headless_test_bad_gpx = ProjectSettings.globalize_path("user://missing_phase2_test_route.gpx")
	_overlay_visible = true
	if _headless_test_good_gpx != "":
		default_gpx_path = _headless_test_good_gpx


func _load_default_gpx_route() -> bool:
	if default_gpx_path.strip_edges() == "":
		return false
	var resolved_path := _loader.resolve_repo_relative_path(default_gpx_path)
	if not FileAccess.file_exists(resolved_path):
		return false
	var matched_route := _match_baked_route_for_gpx(resolved_path)
	if not matched_route.is_empty():
		active_route_id = str(matched_route["route_id"])
		_import_status = "Loaded default sample route %s" % matched_route.get("route_id", resolved_path.get_file())
		return _activate_route(matched_route)
	return false


func _match_baked_route_for_gpx(path: String) -> Dictionary:
	var normalized_file := path.get_file().get_basename().to_lower().replace("-", "_").replace(" ", "_")
	for route in _pack.get("routes", []):
		var route_id := str(route.get("route_id", "")).to_lower()
		if route_id == normalized_file or route_id.ends_with(normalized_file):
			return route
	for entry in _pack.get("route_catalog", []):
		var display_name := str(entry.get("display_name", "")).to_lower().replace("-", "_").replace(" ", "_")
		if display_name == normalized_file:
			return _find_route(str(entry.get("route_id", "")))
	return {}


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_W:
				_simulated_power_w += POWER_STEP_W
			KEY_S:
				_simulated_power_w = max(0.0, _simulated_power_w - POWER_STEP_W)
			KEY_A:
				_brake_pct = max(0.0, _brake_pct - BRAKE_STEP_PCT)
			KEY_D:
				_brake_pct = min(max_brake_pct, _brake_pct + BRAKE_STEP_PCT)
			KEY_Q:
				_simulated_cadence_rpm = max(40.0, _simulated_cadence_rpm - CADENCE_STEP_RPM)
			KEY_E:
				_simulated_cadence_rpm = min(130.0, _simulated_cadence_rpm + CADENCE_STEP_RPM)
			KEY_SPACE:
				_brake_pct = 0.0
			KEY_R:
				_restart_route()
			KEY_P:
				_paused = not _paused
			KEY_I:
				_file_dialog.popup_centered_ratio(0.7)
			KEY_TAB:
				_overlay_visible = not _overlay_visible
				_hud_label.visible = _overlay_visible
			KEY_BRACKETLEFT:
				_select_route_delta(-1)
			KEY_BRACKETRIGHT:
				_select_route_delta(1)
			KEY_1, KEY_2, KEY_3, KEY_4:
				_select_route_by_number(int(event.keycode - KEY_1))


func _process(delta: float) -> void:
	if _route_total_distance_m <= 0.0:
		_maybe_update_overlay(delta)
		_run_headless_test(delta)
		return

	if not _paused:
		var simulation_multiplier := 12.0 if _headless_test_enabled else 1.0
		var grade_pct := _grade_at_distance(_route_progress_m)
		var resistance_factor := _resistance_factor(grade_pct)
		var target_speed := _target_speed_mps(grade_pct)
		_current_speed_mps = lerp(_current_speed_mps, target_speed, min(1.0, delta * 1.6 * simulation_multiplier))
		_route_progress_m = min(_route_total_distance_m, _route_progress_m + (_current_speed_mps * delta * simulation_multiplier))
		_rider.position = _point_at_distance_m(_route_progress_m)
		_update_follow_camera(delta)
		_update_streaming()
		_set_status("%s | %s | resistance %.2f" % [_pack["manifest"]["region_id"], _route["route_id"], resistance_factor])

	_maybe_update_overlay(delta)
	_run_headless_test(delta)


func _maybe_update_overlay(delta: float) -> void:
	if not _overlay_visible:
		return
	_hud_refresh_remaining_s -= delta
	if _hud_refresh_remaining_s > 0.0:
		return
	_hud_refresh_remaining_s = HUD_REFRESH_INTERVAL_S
	_update_overlay()


func _load_pack() -> bool:
	var result := _loader.load_region_pack(_region_dir)
	if not result.get("ok", false):
		var error_text := "Failed to load region pack: %s" % result.get("error", "unknown error")
		_record_runtime_error(error_text)
		_set_status(error_text)
		push_error(str(result))
		return false

	_pack = result["pack"]
	_edge_lookup.clear()
	_tile_rects.clear()
	_tile_centers_m.clear()
	for edge in _pack["ride_graph"].get("edges", []):
		_edge_lookup[edge["edge_id"]] = edge
	for tile in _pack.get("scenery_index", {}).get("tiles", []):
		var tile_id := str(tile["tile_id"])
		var origin: Array = tile.get("origin_m", [0.0, 0.0])
		var size: Array = tile.get("size_m", [_pack["manifest"].get("tile_size_m", 1000.0), _pack["manifest"].get("tile_size_m", 1000.0)])
		var rect := Rect2(Vector2(float(origin[0]), float(origin[1])), Vector2(float(size[0]), float(size[1])))
		_tile_rects[tile_id] = rect
		_tile_centers_m[tile_id] = rect.get_center()
	return true


func _activate_route(route_override: Dictionary = {}) -> bool:
	_route = route_override if not route_override.is_empty() else _find_route(active_route_id)
	if _route.is_empty() and not _pack.get("routes", []).is_empty():
		_route = _pack["routes"][0]
		active_route_id = str(_route["route_id"])
	if _route.is_empty():
		var error_text := "No route points available"
		_record_runtime_error(error_text)
		_set_status(error_text)
		return false

	active_route_id = str(_route.get("route_id", active_route_id))
	_sync_selected_route_index()
	_clear_loaded_tiles()
	_build_route()
	if _route_total_distance_m <= 0.0:
		var route_error := "Route %s had no distance samples" % active_route_id
		_record_runtime_error(route_error)
		_set_status(route_error)
		return false
	_build_route_runtime_metadata()
	_restart_route()
	return true


func _reload_pack_and_route(route_override: Dictionary = {}) -> void:
	if not _load_pack():
		return
	_activate_route(route_override)


func _sync_selected_route_index() -> void:
	var catalog: Array = _pack.get("route_catalog", [])
	for index in range(catalog.size()):
		if str(catalog[index]["route_id"]) == active_route_id:
			_selected_route_index = index
			return
	_selected_route_index = 0


func _restart_route() -> void:
	_route_progress_m = 0.0
	_current_speed_mps = 0.0
	_rider.position = _point_at_distance_m(0.0) if not _route_points.is_empty() else Vector3.ZERO
	_camera_initialized = false
	_update_follow_camera(0.0)
	_update_streaming()


func _build_route() -> void:
	_route_points.clear()
	_route_distances_m.clear()
	_route_total_distance_m = 0.0

	var distance_offset := 0.0
	for edge_id in _route["snapped_edge_sequence"]:
		var edge: Dictionary = _edge_lookup.get(edge_id, {})
		if edge.is_empty():
			continue
		var geometry: Array = edge["geometry_m"]
		var elevations: Array = edge["elevation_profile_m"]
		var distances: Array = edge["distance_profile_m"]
		for index in range(geometry.size()):
			if not _route_points.is_empty() and index == 0:
				continue
			_route_points.append(_to_world(geometry[index], elevations[index]))
			_route_distances_m.append(distance_offset + float(distances[index]))
		distance_offset += float(edge["length_m"])
	_route_total_distance_m = float(_route["distance_m"])


func _build_route_runtime_metadata() -> void:
	_route_edge_segments.clear()
	_route_grade_distances_m.clear()
	_route_grade_values_pct.clear()
	for distance_value in _route.get("distance_profile_m", []):
		_route_grade_distances_m.append(float(distance_value))
	for grade_value in _route.get("grade_profile_pct", []):
		_route_grade_values_pct.append(float(grade_value))
	var accumulated := 0.0
	for edge_id in _route.get("snapped_edge_sequence", []):
		var edge: Dictionary = _edge_lookup.get(edge_id, {})
		if edge.is_empty():
			continue
		var next_accumulated := accumulated + float(edge["length_m"])
		_route_edge_segments.append({
			"edge_id": str(edge_id),
			"start_m": accumulated,
			"end_m": next_accumulated,
			"stream_region_id": str(edge.get("stream_region_id", "phase1"))
		})
		accumulated = next_accumulated


func _distance_profile_index(distances: Array[float], distance_along_route_m: float) -> int:
	if distances.size() <= 1:
		return 0
	var low := 0
	var high := distances.size() - 2
	while low <= high:
		var mid := int((low + high) / 2)
		if distance_along_route_m <= distances[mid + 1]:
			if mid == 0 or distance_along_route_m > distances[mid]:
				return mid
			high = mid - 1
		else:
			low = mid + 1
	return max(0, distances.size() - 2)


func _update_streaming() -> void:
	if _pack.get("pack_version", "phase1") != "phase2":
		_build_phase1_world()
		return

	var coarse_tile_ids := _target_tile_ids_for_route_window(_route_progress_m, COARSE_STREAM_REAR_M, COARSE_STREAM_FORWARD_M, COARSE_STREAM_BUFFER_M, COARSE_SAMPLE_STEP_M)
	var detail_tile_ids := _target_tile_ids_for_route_window(_route_progress_m, DETAIL_STREAM_REAR_M, DETAIL_STREAM_FORWARD_M, DETAIL_STREAM_BUFFER_M, DETAIL_SAMPLE_STEP_M)
	var current_tile_id := _tile_id_for_point(_route_point_m_at_distance(_route_progress_m))
	if current_tile_id != "":
		coarse_tile_ids[current_tile_id] = true
		detail_tile_ids[current_tile_id] = true

	for tile_id in _loaded_tiles.keys():
		if not coarse_tile_ids.has(tile_id):
			_unload_tile(str(tile_id))

	var current_point_m := _route_point_m_at_distance(_route_progress_m)
	var sorted_target_tile_ids := coarse_tile_ids.keys()
	sorted_target_tile_ids.sort_custom(func(a: Variant, b: Variant) -> bool:
		return _tile_centers_m.get(str(a), current_point_m).distance_squared_to(current_point_m) < _tile_centers_m.get(str(b), current_point_m).distance_squared_to(current_point_m)
	)

	for tile_id_variant in sorted_target_tile_ids:
		var tile_id := str(tile_id_variant)
		if not _loaded_tiles.has(tile_id):
			_load_tile(tile_id, detail_tile_ids.has(tile_id))
		elif detail_tile_ids.has(tile_id):
			_load_tile_detail(tile_id)
		else:
			_unload_tile_detail(tile_id)

	_update_loaded_region_ids(coarse_tile_ids.keys())
	_sample_runtime_metrics()


func _target_tile_ids_for_route_window(progress_m: float, rear_m: float, forward_m: float, lateral_buffer_m: float, sample_step_m: float) -> Dictionary:
	var target_tile_ids := {}
	var start_distance: float = max(0.0, progress_m - rear_m)
	var end_distance: float = min(_route_total_distance_m, progress_m + forward_m)
	if end_distance <= start_distance:
		end_distance = min(_route_total_distance_m, start_distance + sample_step_m)
	var distance_cursor: float = start_distance
	while distance_cursor <= end_distance + 0.01:
		_append_tiles_near_point(_route_point_m_at_distance(distance_cursor), lateral_buffer_m, target_tile_ids)
		distance_cursor += sample_step_m
	_append_tiles_near_point(_route_point_m_at_distance(end_distance), lateral_buffer_m, target_tile_ids)
	return target_tile_ids


func _append_tiles_near_point(point_m: Vector2, lateral_buffer_m: float, target_tile_ids: Dictionary) -> void:
	for tile_id in _tile_rects.keys():
		var rect: Rect2 = _tile_rects[tile_id]
		if rect.grow(lateral_buffer_m).has_point(point_m):
			target_tile_ids[str(tile_id)] = true


func _tile_id_for_point(point_m: Vector2) -> String:
	for tile_id in _tile_rects.keys():
		if Rect2(_tile_rects[tile_id]).has_point(point_m):
			return str(tile_id)
	return ""


func _update_loaded_region_ids(tile_ids: Array) -> void:
	var region_ids := {}
	for tile_id_variant in tile_ids:
		var tile_info: Dictionary = _pack.get("tile_index", {}).get(str(tile_id_variant), {})
		if tile_info.is_empty():
			continue
		region_ids[str(tile_info.get("stream_region_id", "phase1"))] = true
	_loaded_region_ids = []
	for region_id in region_ids.keys():
		_loaded_region_ids.append(str(region_id))
	_loaded_region_ids.sort()


func _build_phase1_world() -> void:
	if _loaded_tiles.has("phase1"):
		return
	var tile_root := Node3D.new()
	tile_root.name = "phase1"
	var coarse_root := Node3D.new()
	coarse_root.name = "CoarseRoot"
	tile_root.add_child(coarse_root)
	var detail_root := Node3D.new()
	detail_root.name = "DetailRoot"
	tile_root.add_child(detail_root)
	_loaded_tiles_root.add_child(tile_root)
	_loaded_tiles["phase1"] = {
		"root": tile_root,
		"coarse_root": coarse_root,
		"detail_root": detail_root,
		"tile_info": {"tile_id": "phase1", "stream_region_id": "phase1"},
		"detail_loaded": false
	}
	_build_tile_coarse(_loaded_tiles["phase1"], {"ride_graph": _pack["ride_graph"], "scenery": _pack["scenery"]})
	_load_tile_detail("phase1")
	_loaded_region_ids = ["phase1"]


func _load_tile(tile_id: String, load_detail: bool) -> void:
	var tile_info: Dictionary = _pack["tile_index"].get(tile_id, {})
	if tile_info.is_empty():
		return
	var tile_pack := _get_or_load_tile_pack(tile_id, tile_info)
	if tile_pack.is_empty():
		return

	var tile_root := Node3D.new()
	tile_root.name = tile_id
	var coarse_root := Node3D.new()
	coarse_root.name = "CoarseRoot"
	tile_root.add_child(coarse_root)
	var detail_root := Node3D.new()
	detail_root.name = "DetailRoot"
	tile_root.add_child(detail_root)
	_loaded_tiles_root.add_child(tile_root)

	var tile_entry := {
		"root": tile_root,
		"coarse_root": coarse_root,
		"detail_root": detail_root,
		"tile_info": tile_info,
		"detail_loaded": false
	}
	_loaded_tiles[tile_id] = tile_entry
	_build_tile_coarse(tile_entry, tile_pack)
	if load_detail:
		_load_tile_detail(tile_id)


func _get_or_load_tile_pack(tile_id: String, tile_info: Dictionary) -> Dictionary:
	if _tile_pack_cache.has(tile_id):
		_tile_cache_order.erase(tile_id)
		_tile_cache_order.append(tile_id)
		return _tile_pack_cache[tile_id]
	var result: Dictionary = _loader.load_tile_pack(_region_dir, str(tile_info["manifest_asset"]))
	if not result.get("ok", false):
		_import_status = "Tile load failed: %s" % tile_id
		_record_runtime_error(_import_status)
		return {}
	var tile_pack: Dictionary = result["tile"]
	_remember_tile_pack(tile_id, tile_pack)
	return tile_pack


func _remember_tile_pack(tile_id: String, tile_pack: Dictionary) -> void:
	_tile_pack_cache[tile_id] = tile_pack
	_tile_cache_order.erase(tile_id)
	_tile_cache_order.append(tile_id)
	while _tile_cache_order.size() > TILE_CACHE_LIMIT:
		var oldest_tile_id := _tile_cache_order[0]
		_tile_cache_order.remove_at(0)
		if not _loaded_tiles.has(oldest_tile_id):
			_tile_pack_cache.erase(oldest_tile_id)


func _load_tile_detail(tile_id: String) -> void:
	var tile_entry: Dictionary = _loaded_tiles.get(tile_id, {})
	if tile_entry.is_empty() or bool(tile_entry.get("detail_loaded", false)):
		return
	var tile_info: Dictionary = tile_entry["tile_info"]
	var tile_pack := _get_or_load_tile_pack(tile_id, tile_info)
	if tile_pack.is_empty():
		return
	_build_tile_detail(tile_entry, tile_pack)
	tile_entry["detail_loaded"] = true
	_loaded_tiles[tile_id] = tile_entry


func _unload_tile_detail(tile_id: String) -> void:
	var tile_entry: Dictionary = _loaded_tiles.get(tile_id, {})
	if tile_entry.is_empty() or not bool(tile_entry.get("detail_loaded", false)):
		return
	var detail_root: Node3D = tile_entry["detail_root"]
	for child in detail_root.get_children():
		child.queue_free()
	tile_entry["detail_loaded"] = false
	_loaded_tiles[tile_id] = tile_entry


func _unload_tile(tile_id: String) -> void:
	var tile_entry: Dictionary = _loaded_tiles.get(tile_id, {})
	if tile_entry.is_empty():
		return
	var tile_root: Node3D = tile_entry["root"]
	tile_root.queue_free()
	_loaded_tiles.erase(tile_id)


func _clear_loaded_tiles() -> void:
	for tile_id in _loaded_tiles.keys():
		_unload_tile(str(tile_id))
	_loaded_region_ids.clear()


func _build_tile_coarse(tile_entry: Dictionary, tile_pack: Dictionary) -> void:
	var coarse_root: Node3D = tile_entry["coarse_root"]
	var tile_info: Dictionary = tile_entry["tile_info"]
	_build_terrain(coarse_root, tile_info, tile_pack["scenery"])
	_build_water(coarse_root, tile_info, tile_pack["scenery"])
	_build_roads(coarse_root, tile_info, tile_pack["ride_graph"], tile_pack["scenery"])


func _build_tile_detail(tile_entry: Dictionary, tile_pack: Dictionary) -> void:
	var detail_root: Node3D = tile_entry["detail_root"]
	var tile_info: Dictionary = tile_entry["tile_info"]
	_build_biomes(detail_root, tile_info, tile_pack["scenery"])
	_build_streets(detail_root, tile_info, tile_pack["scenery"])
	_build_buildings(detail_root, tile_info, tile_pack["scenery"])
	_build_landmarks(detail_root, tile_info, tile_pack["scenery"])
	_build_props(detail_root, tile_info, tile_pack["scenery"], tile_pack["ride_graph"])


func _build_terrain(parent: Node3D, tile_info: Dictionary, scenery: Dictionary) -> void:
	var terrain_color := Color.from_string(str(scenery.get("style_hints", {}).get("terrain_tint", "#6b7d59")), Color(0.42, 0.49, 0.33))
	for chunk in scenery.get("terrain_chunks", []):
		var mesh_instance := MeshInstance3D.new()
		mesh_instance.name = "%s_Terrain" % str(tile_info.get("tile_id", "terrain"))
		mesh_instance.mesh = _build_terrain_mesh(chunk)
		mesh_instance.material_override = _make_material(terrain_color, 0.0)
		parent.add_child(mesh_instance)


func _build_water(parent: Node3D, tile_info: Dictionary, scenery: Dictionary) -> void:
	var batch := _new_surface_batch()
	for patch in scenery.get("water_patches", []):
		var center_m := _polygon_center(patch["polygon_m"])
		var base_elevation := _scenery_height_at_point_m(scenery, center_m)
		_append_flat_polygon_to_batch(batch, patch["polygon_m"], base_elevation + 0.03)
	_commit_batch_instance(parent, "%s_Water" % str(tile_info.get("tile_id", "water")), batch, _make_material(Color(0.30, 0.58, 0.72), 0.18, false))


func _build_biomes(parent: Node3D, tile_info: Dictionary, scenery: Dictionary) -> void:
	var organic_transforms := []
	var organic_colors := []
	var plaza_transforms := []
	var plaza_colors := []
	for biome in scenery.get("biome_patches", []):
		var bounds := _polygon_bounds(biome["polygon_m"])
		var biome_color := Color.from_string(str(biome.get("color_hint", "#7aa35f")), Color(0.5, 0.7, 0.5)).darkened(0.02)
		var landcover_class := str(biome.get("landcover_class", "parkland"))
		var scatter_count: int = max(3, min(7, int(round(max(bounds.size.x, bounds.size.y) / 260.0))))
		for index in range(scatter_count):
			var sample_m := [
				bounds.position.x + (bounds.size.x * float(index + 1) / float(scatter_count + 1)),
				bounds.position.y + (bounds.size.y * float(((index * 3) % (scatter_count + 1)) + 1) / float(scatter_count + 1))
			]
			var base_elevation := _scenery_height_at_point_m(scenery, sample_m)
			var sample_position := Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale, sample_m[1] * world_scale)
			if ["urban_core", "mixed_use"].has(landcover_class):
				var plaza_size := Vector3(4.0 + float(index % 2) * 1.6, 0.35, 4.0 + float((index + 1) % 2) * 1.6)
				var plaza_transform := Transform3D(Basis.from_scale(plaza_size), sample_position + Vector3(0.0, 0.18, 0.0))
				plaza_transforms.append(plaza_transform)
				plaza_colors.append(biome_color.lightened(0.02 * float(index % 2)))
			else:
				var canopy_radius := 0.8 + float(index % 3) * 0.25
				var canopy_scale := Vector3(1.2 * canopy_radius, 0.6 * canopy_radius, 1.2 * canopy_radius)
				var canopy_transform := Transform3D(Basis.from_scale(canopy_scale), sample_position + Vector3(0.0, canopy_radius * 0.55, 0.0))
				organic_transforms.append(canopy_transform)
				organic_colors.append(biome_color.lightened(0.03 * float(index % 2)))
	_add_colored_multimesh(parent, "%s_BiomeOrganic" % str(tile_info.get("tile_id", "biome")), _shared_sphere_mesh(1.0, 2.0), _make_material(Color.WHITE, 0.0, false, true), organic_transforms, organic_colors)
	_add_colored_multimesh(parent, "%s_BiomePlaza" % str(tile_info.get("tile_id", "biome")), _shared_box_mesh(Vector3.ONE), _make_material(Color.WHITE, 0.0, false, true), plaza_transforms, plaza_colors)


func _build_roads(parent: Node3D, tile_info: Dictionary, ride_graph: Dictionary, scenery: Dictionary) -> void:
	var road_materials := {
		"asphalt": _make_material(Color(0.12, 0.12, 0.12), 0.0),
		"packed_gravel": _make_material(Color(0.42, 0.36, 0.24), 0.0)
	}
	var road_batches := {}
	for material_key in road_materials.keys():
		road_batches[material_key] = _new_surface_batch()
	var road_segment_lookup := {}
	for segment in scenery.get("road_segments", []):
		road_segment_lookup[segment["edge_id"]] = segment
	for edge in ride_graph.get("edges", []):
		var road_style: Dictionary = road_segment_lookup.get(edge["edge_id"], {"width_m": 4.0, "material": "asphalt"})
		var material_key := str(road_style.get("material", "asphalt"))
		if not road_batches.has(material_key):
			road_batches[material_key] = _new_surface_batch()
			road_materials[material_key] = road_materials["asphalt"]
		_append_road_ribbon_to_batch(road_batches[material_key], edge["geometry_m"], edge["elevation_profile_m"], float(road_style.get("width_m", 4.0)))
	for material_key in road_batches.keys():
		_commit_batch_instance(parent, "%s_Road_%s" % [str(tile_info.get("tile_id", "tile")), material_key], road_batches[material_key], road_materials[material_key])


func _build_streets(parent: Node3D, tile_info: Dictionary, scenery: Dictionary) -> void:
	var street_materials := {
		"asphalt": _make_material(Color(0.25, 0.25, 0.27), 0.0),
		"packed_gravel": _make_material(Color(0.45, 0.40, 0.32), 0.0),
		"trail": _make_material(Color(0.52, 0.48, 0.38), 0.0)
	}
	var street_batches := {}
	for material_key in street_materials.keys():
		street_batches[material_key] = _new_surface_batch()
	for segment in scenery.get("street_segments", []):
		var material_key := str(segment.get("material", "asphalt"))
		if not street_batches.has(material_key):
			street_batches[material_key] = _new_surface_batch()
			street_materials[material_key] = street_materials["asphalt"]
		_append_road_ribbon_to_batch(street_batches[material_key], segment["geometry_m"], segment["elevation_profile_m"], float(segment["width_m"]))
	for material_key in street_batches.keys():
		_commit_batch_instance(parent, "%s_Street_%s" % [str(tile_info.get("tile_id", "tile")), material_key], street_batches[material_key], street_materials[material_key])


func _build_buildings(parent: Node3D, tile_info: Dictionary, scenery: Dictionary) -> void:
	var building_batches := {}
	var building_materials := {}
	for building in scenery.get("buildings", []):
		var kind := str(building.get("kind", "default"))
		if not building_batches.has(kind):
			building_batches[kind] = _new_surface_batch()
			building_materials[kind] = _make_material(_building_color_for_kind(kind), 0.0)
		var bounds := _polygon_bounds(building["footprint_m"])
		var center_m := [bounds.position.x + (bounds.size.x / 2.0), bounds.position.y + (bounds.size.y / 2.0)]
		var base_elevation := _scenery_height_at_point_m(scenery, center_m)
		_append_extruded_polygon_to_batch(building_batches[kind], building["footprint_m"], float(building["height_m"]), base_elevation)
	for kind in building_batches.keys():
		_commit_batch_instance(parent, "%s_Buildings_%s" % [str(tile_info.get("tile_id", "tile")), str(kind)], building_batches[kind], building_materials[kind])


func _build_landmarks(parent: Node3D, tile_info: Dictionary, scenery: Dictionary) -> void:
	var transforms_by_kind := {}
	var colors_by_kind := {}
	for landmark in scenery.get("landmarks", []):
		var kind := str(landmark.get("kind", "landmark"))
		if not transforms_by_kind.has(kind):
			transforms_by_kind[kind] = []
			colors_by_kind[kind] = []
		var base_elevation := _scenery_height_at_point_m(scenery, landmark["point_m"])
		var position := Vector3(float(landmark["point_m"][0]) * world_scale, base_elevation * elevation_scale + 3.0, float(landmark["point_m"][1]) * world_scale)
		transforms_by_kind[kind].append(Transform3D(Basis.from_scale(Vector3(1.8, 6.0, 1.8)), position))
		colors_by_kind[kind].append(_landmark_color_for_kind(kind))
	for kind in transforms_by_kind.keys():
		_add_colored_multimesh(parent, "%s_Landmarks_%s" % [str(tile_info.get("tile_id", "tile")), str(kind)], _shared_box_mesh(Vector3.ONE), _make_material(Color.WHITE, 0.0, false, true), transforms_by_kind[kind], colors_by_kind[kind])


func _build_props(parent: Node3D, tile_info: Dictionary, scenery: Dictionary, ride_graph: Dictionary) -> void:
	var trunk_transforms := []
	var canopy_transforms := []
	var canopy_colors := []
	var grass_transforms := []
	var grass_colors := []
	for mask in scenery.get("prop_masks", []):
		var bounds := _polygon_bounds(mask["polygon_m"])
		var density: float = clamp(float(mask.get("density", 0.5)), 0.2, 1.0)
		var count: int = max(4, int(round(density * 8.0)))
		var prop_class := str(mask.get("prop_class", "trees"))
		for index in range(count):
			var sample_m := [
				bounds.position.x + (bounds.size.x * float(index + 1) / float(count + 1)),
				bounds.position.y + (bounds.size.y * float(((index * 2) % (count + 1)) + 1) / float(count + 1))
			]
			var base_elevation := _scenery_height_at_point_m(scenery, sample_m)
			var sample_position := Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale, sample_m[1] * world_scale)
			if prop_class == "shoreline_grass":
				grass_transforms.append(Transform3D(Basis.from_scale(Vector3(0.63 + density * 0.18, 0.19, 0.63 + density * 0.18)), sample_position + Vector3(0.0, 0.12, 0.0)))
				grass_colors.append(Color(0.78, 0.77, 0.52).darkened(0.02 * float(index % 2)))
			elif prop_class == "street_trees":
				_append_tree_instance(trunk_transforms, canopy_transforms, canopy_colors, sample_position, 1.6 + density * 0.5, 0.65 + density * 0.35, Color(0.24, 0.45, 0.22).lightened(0.01 * float(index % 3)))
			else:
				_append_tree_instance(trunk_transforms, canopy_transforms, canopy_colors, sample_position, 1.2 + density * 0.7 + float(index % 3) * 0.18, 0.75 + density * 0.55, Color(0.22, 0.47, 0.26).lightened(0.02 * float(index % 4)))

	if scenery.get("prop_masks", []).is_empty():
		_append_roadside_tree_instances(trunk_transforms, canopy_transforms, canopy_colors, tile_info, scenery, ride_graph)

	_add_plain_multimesh(parent, "%s_PropTrunks" % str(tile_info.get("tile_id", "tile")), _shared_cylinder_mesh(0.08, 0.12, 1.0), _make_material(Color(0.34, 0.24, 0.12), 0.0), trunk_transforms)
	_add_colored_multimesh(parent, "%s_PropCanopies" % str(tile_info.get("tile_id", "tile")), _shared_sphere_mesh(1.0, 2.0), _make_material(Color.WHITE, 0.0, false, true), canopy_transforms, canopy_colors)
	_add_colored_multimesh(parent, "%s_PropGrass" % str(tile_info.get("tile_id", "tile")), _shared_sphere_mesh(1.0, 1.0), _make_material(Color.WHITE, 0.0, false, true), grass_transforms, grass_colors)


func _find_route(route_id: String) -> Dictionary:
	for route in _pack.get("routes", []):
		if str(route["route_id"]) == route_id:
			return route
	return {}


func _select_route_delta(delta: int) -> void:
	var catalog: Array = _pack.get("route_catalog", [])
	if catalog.is_empty():
		return
	_selected_route_index = posmod(_selected_route_index + delta, catalog.size())
	_select_route_by_index(_selected_route_index)


func _select_route_by_number(index: int) -> void:
	var catalog: Array = _pack.get("route_catalog", [])
	if index >= 0 and index < catalog.size():
		_select_route_by_index(index)


func _select_route_by_index(index: int) -> void:
	var catalog: Array = _pack.get("route_catalog", [])
	if catalog.is_empty():
		return
	_selected_route_index = index
	active_route_id = str(catalog[index]["route_id"])
	_import_status = "Selected %s" % catalog[index]["display_name"]
	_activate_route()


func _point_at_distance_m(distance_along_route_m: float) -> Vector3:
	if _route_points.is_empty():
		return Vector3.ZERO
	if _route_points.size() == 1:
		return _route_points[0]
	var sample_index := _distance_profile_index(_route_distances_m, distance_along_route_m)
	var start_distance := float(_route_distances_m[sample_index])
	var end_distance := float(_route_distances_m[sample_index + 1])
	var span: float = max(0.001, end_distance - start_distance)
	var ratio: float = clamp((distance_along_route_m - start_distance) / span, 0.0, 1.0)
	return _route_points[sample_index].lerp(_route_points[sample_index + 1], ratio)


func _route_point_m_at_distance(distance_along_route_m: float) -> Vector2:
	var world_point := _point_at_distance_m(distance_along_route_m)
	return Vector2(world_point.x / world_scale, world_point.z / world_scale)


func _update_follow_camera(delta: float) -> void:
	var forward := _forward_direction_at_distance(_route_progress_m)
	var anchor_position := _rider.position + forward * CAMERA_FORWARD_OFFSET_M + Vector3(0.0, CAMERA_HEIGHT_M, 0.0)
	if not _camera_initialized or delta <= 0.0:
		_camera.position = anchor_position
		_camera_initialized = true
	else:
		_camera.position = _camera.position.lerp(anchor_position, min(1.0, delta * CAMERA_LERP_RATE))
	var look_target := _rider.position + forward * CAMERA_LOOKAHEAD_M + Vector3(0.0, CAMERA_LOOK_LIFT_M, 0.0)
	_camera.look_at(look_target)
	_camera.rotation.z = lerp(_camera.rotation.z, 0.0, min(1.0, delta * CAMERA_LERP_RATE * CAMERA_ROLL_DAMPING))


func _forward_direction_at_distance(distance_along_route_m: float) -> Vector3:
	if _route_points.size() < 2:
		return Vector3.FORWARD
	var look_behind := _point_at_distance_m(max(0.0, distance_along_route_m - 4.0))
	var look_ahead := _point_at_distance_m(min(_route_total_distance_m, distance_along_route_m + 18.0))
	var direction := look_ahead - look_behind
	if direction.length() < 0.001:
		return Vector3.FORWARD
	direction.y = 0.0
	return direction.normalized()


func _grade_at_distance(distance_along_route_m: float) -> float:
	if _route_grade_values_pct.is_empty() or _route_grade_distances_m.is_empty():
		return 0.0
	var sample_index := _distance_profile_index(_route_grade_distances_m, distance_along_route_m)
	return _route_grade_values_pct[min(sample_index, _route_grade_values_pct.size() - 1)]


func _edge_status_at_distance(distance_along_route_m: float) -> Dictionary:
	if _route_edge_segments.is_empty():
		return {"edge_id": "n/a", "segment_index": 0, "stream_region_id": "n/a"}
	var low := 0
	var high := _route_edge_segments.size() - 1
	while low <= high:
		var mid := int((low + high) / 2)
		var segment: Dictionary = _route_edge_segments[mid]
		if distance_along_route_m < float(segment["start_m"]):
			high = mid - 1
		elif distance_along_route_m > float(segment["end_m"]):
			low = mid + 1
		else:
			return {"edge_id": segment["edge_id"], "segment_index": mid, "stream_region_id": segment["stream_region_id"]}
	var fallback_index: int = clamp(low, 0, _route_edge_segments.size() - 1)
	var fallback_segment: Dictionary = _route_edge_segments[fallback_index]
	return {"edge_id": fallback_segment["edge_id"], "segment_index": fallback_index, "stream_region_id": fallback_segment["stream_region_id"]}


func _resistance_factor(grade_pct: float) -> float:
	return 1.0 + max(0.0, grade_pct) * 0.04 + (_brake_pct / 100.0) * 1.2


func _target_speed_mps(grade_pct: float) -> float:
	var cadence_factor: float = clamp(_simulated_cadence_rpm / baseline_cadence_rpm, 0.45, 1.35)
	var brake_factor: float = 1.0 - (_brake_pct / 100.0)
	var available_power: float = max(0.0, _simulated_power_w * cadence_factor * brake_factor)
	var grade_force: float = rider_mass_kg * 9.81 * (grade_pct / 100.0)
	var rolling_force: float = rider_mass_kg * 9.81 * 0.0045
	var aero_force: float = 14.0 + pow(max(_current_speed_mps, 0.0), 2.0) * 0.32
	var net_force: float = max(10.0, available_power / max(1.0, 6.0 + abs(grade_force * 0.05)))
	var raw_speed: float = (net_force - grade_force - rolling_force - aero_force * 0.08) / max(1.0, rider_mass_kg * 0.11)
	return clamp(raw_speed, 0.0, 18.0)


func _import_route_from_path(path: String, record_error: bool = true) -> bool:
	var cli_path := _loader.resolve_repo_relative_path("geo-pipeline/run_geo_pipeline_cli.py")
	if not FileAccess.file_exists(cli_path):
		_import_status = "GPX import helper missing: %s" % cli_path
		if record_error:
			_record_runtime_error(_import_status)
		_set_status(_import_status)
		return false
	var output_dir := snap_output_dir
	if output_dir == "":
		output_dir = "user://snapped_routes"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(output_dir))
	var output_path := ProjectSettings.globalize_path(output_dir).path_join("%s.route.json" % path.get_file().get_basename())
	var output: Array = []
	var exit_code := OS.execute(
		python_executable,
		PackedStringArray([cli_path, "snap-gpx", _region_dir, path, "--output", output_path]),
		output,
		true
	)
	if exit_code != 0:
		_import_status = "GPX import failed: %s" % "\n".join(output)
		if record_error:
			_record_runtime_error(_import_status)
		_set_status(_import_status)
		return false

	var file := FileAccess.open(output_path, FileAccess.READ)
	if file == null:
		_import_status = "GPX snap output missing: %s" % output_path
		if record_error:
			_record_runtime_error(_import_status)
		_set_status(_import_status)
		return false
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		_import_status = "GPX snap output was not a route definition"
		if record_error:
			_record_runtime_error(_import_status)
		_set_status(_import_status)
		return false
	_import_status = "Imported %s" % path.get_file()
	active_route_id = str(parsed["route_id"])
	return _activate_route(parsed)


func _on_import_dialog_file_selected(path: String) -> void:
	_import_route_from_path(path)


func _to_world(point_m: Array, elevation_m: float) -> Vector3:
	return Vector3(float(point_m[0]) * world_scale, elevation_m * elevation_scale, float(point_m[1]) * world_scale)


func _build_terrain_mesh(chunk: Dictionary) -> ArrayMesh:
	var grid: Array = chunk["elevation_grid_m"]
	var rows: int = grid.size()
	var columns: int = grid[0].size()
	var step_m: float = float(chunk["sample_spacing_m"])
	var origin: Array = chunk["origin_m"]
	var batch := _new_surface_batch()
	for row in range(rows - 1):
		for column in range(columns - 1):
			var a := _to_world([origin[0] + column * step_m, origin[1] + row * step_m], float(grid[row][column]))
			var b := _to_world([origin[0] + (column + 1) * step_m, origin[1] + row * step_m], float(grid[row][column + 1]))
			var c := _to_world([origin[0] + column * step_m, origin[1] + (row + 1) * step_m], float(grid[row + 1][column]))
			var d := _to_world([origin[0] + (column + 1) * step_m, origin[1] + (row + 1) * step_m], float(grid[row + 1][column + 1]))
			_add_triangle(batch, a, c, b)
			_add_triangle(batch, b, c, d)
	return _commit_surface_batch(batch)


func _new_surface_batch() -> Dictionary:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	return {"surface": surface, "vertex_count": 0}


func _add_triangle(batch: Dictionary, a: Vector3, b: Vector3, c: Vector3) -> void:
	var surface: SurfaceTool = batch["surface"]
	surface.add_vertex(a)
	surface.add_vertex(b)
	surface.add_vertex(c)
	batch["vertex_count"] = int(batch["vertex_count"]) + 3


func _append_flat_polygon_to_batch(batch: Dictionary, points_m: Array, elevation_m: float) -> void:
	if points_m.size() < 3:
		return
	var vertices: Array[Vector3] = []
	for point_m in points_m:
		vertices.append(_to_world(point_m, elevation_m))
	for index in range(1, vertices.size() - 1):
		_add_triangle(batch, vertices[0], vertices[index], vertices[index + 1])


func _append_extruded_polygon_to_batch(batch: Dictionary, points_m: Array, height_m: float, base_elevation_m: float) -> void:
	if points_m.size() < 3:
		return
	var base_ring: Array[Vector3] = []
	var top_ring: Array[Vector3] = []
	for point_m in points_m:
		var base_point := _to_world(point_m, base_elevation_m)
		base_ring.append(base_point)
		top_ring.append(base_point + Vector3(0.0, height_m * elevation_scale, 0.0))
	for index in range(1, top_ring.size() - 1):
		_add_triangle(batch, top_ring[0], top_ring[index], top_ring[index + 1])
	for index in range(base_ring.size()):
		var next_index := (index + 1) % base_ring.size()
		var a := base_ring[index]
		var b := base_ring[next_index]
		var c := top_ring[index]
		var d := top_ring[next_index]
		_add_triangle(batch, a, b, c)
		_add_triangle(batch, c, b, d)


func _append_road_ribbon_to_batch(batch: Dictionary, geometry_m: Array, elevations_m: Array, width_m: float) -> void:
	if geometry_m.size() < 2 or geometry_m.size() != elevations_m.size():
		return
	var left_points: Array[Vector3] = []
	var right_points: Array[Vector3] = []
	for index in range(geometry_m.size()):
		var current := _to_world(geometry_m[index], float(elevations_m[index]) + ROAD_SURFACE_CLEARANCE_M)
		var previous := _to_world(geometry_m[max(index - 1, 0)], float(elevations_m[max(index - 1, 0)]) + ROAD_SURFACE_CLEARANCE_M)
		var following := _to_world(geometry_m[min(index + 1, geometry_m.size() - 1)], float(elevations_m[min(index + 1, geometry_m.size() - 1)]) + ROAD_SURFACE_CLEARANCE_M)
		var tangent := following - previous
		if tangent.length() < 0.001:
			tangent = Vector3(0.0, 0.0, 1.0)
		var lateral := Vector3(-tangent.z, 0.0, tangent.x).normalized() * (width_m * world_scale * 0.5)
		left_points.append(current - lateral)
		right_points.append(current + lateral)
	for index in range(left_points.size() - 1):
		var a := left_points[index]
		var b := right_points[index]
		var c := left_points[index + 1]
		var d := right_points[index + 1]
		_add_triangle(batch, a, c, b)
		_add_triangle(batch, b, c, d)


func _commit_surface_batch(batch: Dictionary) -> ArrayMesh:
	if int(batch["vertex_count"]) == 0:
		return ArrayMesh.new()
	var surface: SurfaceTool = batch["surface"]
	if not enable_low_poly_shading:
		surface.generate_normals()
	return surface.commit()


func _commit_batch_instance(parent: Node3D, node_name: String, batch: Dictionary, material: Material) -> void:
	if int(batch["vertex_count"]) == 0:
		return
	var mesh_instance := MeshInstance3D.new()
	mesh_instance.name = node_name
	mesh_instance.mesh = _commit_surface_batch(batch)
	mesh_instance.material_override = material
	parent.add_child(mesh_instance)


func _shared_box_mesh(size: Vector3) -> BoxMesh:
	var key := "box_%0.3f_%0.3f_%0.3f" % [size.x, size.y, size.z]
	if _shared_mesh_cache.has(key):
		return _shared_mesh_cache[key]
	var mesh := BoxMesh.new()
	mesh.size = size
	_shared_mesh_cache[key] = mesh
	return mesh


func _shared_sphere_mesh(radius: float, height: float) -> SphereMesh:
	var key := "sphere_%0.3f_%0.3f" % [radius, height]
	if _shared_mesh_cache.has(key):
		return _shared_mesh_cache[key]
	var mesh := SphereMesh.new()
	mesh.radius = radius
	mesh.height = height
	mesh.radial_segments = 6
	mesh.rings = 4
	_shared_mesh_cache[key] = mesh
	return mesh


func _shared_cylinder_mesh(top_radius: float, bottom_radius: float, height: float) -> CylinderMesh:
	var key := "cylinder_%0.3f_%0.3f_%0.3f" % [top_radius, bottom_radius, height]
	if _shared_mesh_cache.has(key):
		return _shared_mesh_cache[key]
	var mesh := CylinderMesh.new()
	mesh.top_radius = top_radius
	mesh.bottom_radius = bottom_radius
	mesh.height = height
	mesh.radial_segments = 6
	mesh.rings = 1
	_shared_mesh_cache[key] = mesh
	return mesh


func _add_plain_multimesh(parent: Node3D, node_name: String, mesh: Mesh, material: Material, transforms: Array) -> void:
	if transforms.is_empty():
		return
	var multimesh := MultiMesh.new()
	multimesh.transform_format = MultiMesh.TRANSFORM_3D
	multimesh.instance_count = transforms.size()
	multimesh.mesh = mesh
	for index in range(transforms.size()):
		multimesh.set_instance_transform(index, transforms[index])
	var instance := MultiMeshInstance3D.new()
	instance.name = node_name
	instance.multimesh = multimesh
	instance.material_override = material
	parent.add_child(instance)


func _add_colored_multimesh(parent: Node3D, node_name: String, mesh: Mesh, material: Material, transforms: Array, colors: Array) -> void:
	if transforms.is_empty():
		return
	var multimesh := MultiMesh.new()
	multimesh.transform_format = MultiMesh.TRANSFORM_3D
	multimesh.use_colors = colors.size() == transforms.size()
	multimesh.instance_count = transforms.size()
	multimesh.mesh = mesh
	for index in range(transforms.size()):
		multimesh.set_instance_transform(index, transforms[index])
		if multimesh.use_colors:
			multimesh.set_instance_color(index, colors[index])
	var instance := MultiMeshInstance3D.new()
	instance.name = node_name
	instance.multimesh = multimesh
	instance.material_override = material
	parent.add_child(instance)


func _append_tree_instance(trunk_transforms: Array, canopy_transforms: Array, canopy_colors: Array, base_position: Vector3, trunk_height: float, canopy_radius: float, canopy_color: Color) -> void:
	trunk_transforms.append(Transform3D(Basis.from_scale(Vector3(1.0, trunk_height, 1.0)), base_position + Vector3(0.0, trunk_height / 2.0, 0.0)))
	canopy_transforms.append(Transform3D(Basis.from_scale(Vector3(1.15 * canopy_radius, 0.9 * canopy_radius, 1.15 * canopy_radius)), base_position + Vector3(0.0, trunk_height + canopy_radius * 0.75, 0.0)))
	canopy_colors.append(canopy_color)


func _append_roadside_tree_instances(trunk_transforms: Array, canopy_transforms: Array, canopy_colors: Array, tile_info: Dictionary, scenery: Dictionary, ride_graph: Dictionary) -> void:
	var road_segments: Array = scenery.get("road_segments", [])
	if road_segments.is_empty():
		return
	var edge_lookup := {}
	for edge in ride_graph.get("edges", []):
		edge_lookup[edge["edge_id"]] = edge
	for segment in road_segments:
		var edge: Dictionary = edge_lookup.get(segment["edge_id"], {})
		if edge.is_empty():
			continue
		var geometry: Array = edge["geometry_m"]
		for index in range(0, geometry.size(), 2):
			var forward := Vector2.ZERO
			if index < geometry.size() - 1:
				forward = Vector2(float(geometry[index + 1][0] - geometry[index][0]), float(geometry[index + 1][1] - geometry[index][1]))
			elif index > 0:
				forward = Vector2(float(geometry[index][0] - geometry[index - 1][0]), float(geometry[index][1] - geometry[index - 1][1]))
			if forward.length() < 0.001:
				continue
			var lateral := Vector2(-forward.y, forward.x).normalized() * 9.0
			for side in [-1.0, 1.0]:
				var sample_m := [float(geometry[index][0]) + lateral.x * side, float(geometry[index][1]) + lateral.y * side]
				var base_elevation := _scenery_height_at_point_m(scenery, sample_m)
				_append_tree_instance(trunk_transforms, canopy_transforms, canopy_colors, Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale, sample_m[1] * world_scale), 1.3, 0.7, Color(0.24, 0.51, 0.28))


func _polygon_bounds(points: Array) -> Rect2:
	var min_x := INF
	var min_y := INF
	var max_x := -INF
	var max_y := -INF
	for point in points:
		min_x = min(min_x, float(point[0]))
		min_y = min(min_y, float(point[1]))
		max_x = max(max_x, float(point[0]))
		max_y = max(max_y, float(point[1]))
	return Rect2(Vector2(min_x, min_y), Vector2(max_x - min_x, max_y - min_y))


func _polygon_center(points: Array) -> Array:
	var total_x := 0.0
	var total_y := 0.0
	for point in points:
		total_x += float(point[0])
		total_y += float(point[1])
	var count: float = max(1.0, float(points.size()))
	return [total_x / count, total_y / count]


func _scenery_height_at_point_m(scenery: Dictionary, point_m: Array) -> float:
	var chunk: Dictionary = scenery["terrain_chunks"][0]
	var origin: Array = chunk["origin_m"]
	var grid: Array = chunk["elevation_grid_m"]
	var rows: int = grid.size()
	var columns: int = grid[0].size()
	var step_m: float = float(chunk["sample_spacing_m"])
	var local_x: float = clamp((float(point_m[0]) - float(origin[0])) / step_m, 0.0, float(columns - 1))
	var local_y: float = clamp((float(point_m[1]) - float(origin[1])) / step_m, 0.0, float(rows - 1))
	var x0: int = int(floor(local_x))
	var y0: int = int(floor(local_y))
	var x1: int = min(columns - 1, x0 + 1)
	var y1: int = min(rows - 1, y0 + 1)
	var tx: float = local_x - float(x0)
	var ty: float = local_y - float(y0)
	var z00: float = float(grid[y0][x0])
	var z10: float = float(grid[y0][x1])
	var z01: float = float(grid[y1][x0])
	var z11: float = float(grid[y1][x1])
	var top: float = lerp(z00, z10, tx)
	var bottom: float = lerp(z01, z11, tx)
	return lerp(top, bottom, ty)


func _make_material(albedo: Color, alpha: float, double_sided: bool = false, use_vertex_color: bool = false) -> StandardMaterial3D:
	var cache_key := "%0.3f_%0.3f_%0.3f_%0.3f_%s_%s_%s" % [albedo.r, albedo.g, albedo.b, alpha, str(double_sided), str(use_vertex_color), str(enable_low_poly_shading)]
	if _material_cache.has(cache_key):
		return _material_cache[cache_key]
	var material := StandardMaterial3D.new()
	material.albedo_color = Color.WHITE if use_vertex_color else Color(albedo.r, albedo.g, albedo.b, 1.0 - alpha)
	material.vertex_color_use_as_albedo = use_vertex_color
	material.roughness = 1.0
	material.cull_mode = BaseMaterial3D.CULL_DISABLED if double_sided else BaseMaterial3D.CULL_BACK
	if enable_low_poly_shading:
		material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	if alpha > 0.0:
		material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_material_cache[cache_key] = material
	return material


func _building_color_for_kind(kind: String) -> Color:
	match kind:
		"urban_core":
			return Color(0.72, 0.70, 0.67)
		"mixed_use":
			return Color(0.75, 0.68, 0.58)
		"commercial":
			return Color(0.78, 0.71, 0.62)
		"civic":
			return Color(0.69, 0.72, 0.76)
		"neighborhood":
			return Color(0.80, 0.73, 0.63)
		_:
			return Color(0.77, 0.69, 0.58)


func _landmark_color_for_kind(kind: String) -> Color:
	match kind:
		"tourism":
			return Color(0.86, 0.68, 0.34)
		"museum", "arts_centre":
			return Color(0.84, 0.56, 0.36)
		"historic":
			return Color(0.72, 0.60, 0.44)
		"university", "school":
			return Color(0.53, 0.62, 0.82)
		_:
			return Color(0.88, 0.73, 0.38)


func _record_runtime_error(error_text: String) -> void:
	if error_text == "":
		return
	if not _runtime_errors.has(error_text):
		_runtime_errors.append(error_text)


func _set_status(text: String) -> void:
	_status_label.text = text


func _update_overlay() -> void:
	var edge_status := _edge_status_at_distance(_route_progress_m)
	var grade_pct := _grade_at_distance(_route_progress_m)
	var resistance_factor := _resistance_factor(grade_pct)
	var route_label: String = str(_route.get("route_id", active_route_id))
	var available_routes: Array = _pack.get("route_catalog", [])
	var selected_label := route_label
	if _selected_route_index < available_routes.size():
		selected_label = str(available_routes[_selected_route_index]["display_name"])
	var detail_tiles := 0
	for tile_entry in _loaded_tiles.values():
		if bool(tile_entry.get("detail_loaded", false)):
			detail_tiles += 1
	_hud_label.text = "\n".join([
		"route: %s" % route_label,
		"selected: %s" % selected_label,
		"progress: %.1f / %.1f m" % [_route_progress_m, _route_total_distance_m],
		"grade: %.2f%%" % grade_pct,
		"speed: %.2f m/s" % _current_speed_mps,
		"power: %.0f W" % _simulated_power_w,
		"cadence: %.0f rpm" % _simulated_cadence_rpm,
		"brake: %.0f%%" % _brake_pct,
		"resistance: %.2f" % resistance_factor,
		"stream region: %s" % str(edge_status.get("stream_region_id", "n/a")),
		"loaded regions: %s" % ", ".join(_loaded_region_ids),
		"loaded tiles: %d coarse / %d detail" % [_loaded_tiles.size(), detail_tiles],
		"camera: over-bars 66deg fov",
		"keys: [ ] or 1/2/3/4 routes  W/S power  A/D brake  Q/E cadence",
		"R restart  P pause  I import GPX  Tab overlay",
		_import_status
	]).strip_edges()


func _headless_assert(condition: bool, failure_message: String) -> void:
	if condition:
		return
	if not _headless_test_failures.has(failure_message):
		_headless_test_failures.append(failure_message)


func _sample_runtime_metrics() -> void:
	var detail_tiles := 0
	for tile_entry in _loaded_tiles.values():
		if bool(tile_entry.get("detail_loaded", false)):
			detail_tiles += 1
	_max_loaded_tiles_seen = max(_max_loaded_tiles_seen, _loaded_tiles.size())
	_max_detail_tiles_seen = max(_max_detail_tiles_seen, detail_tiles)
	_max_loaded_regions_seen = max(_max_loaded_regions_seen, _loaded_region_ids.size())
	_max_node_count_seen = max(_max_node_count_seen, int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)))
	var coarse_snapshot := PackedStringArray(_loaded_tiles.keys())
	coarse_snapshot.sort()
	var coarse_snapshot_key := ",".join(coarse_snapshot)
	if _headless_test_loaded_tile_snapshots.is_empty() or _headless_test_loaded_tile_snapshots[-1] != coarse_snapshot_key:
		_headless_test_loaded_tile_snapshots.append(coarse_snapshot_key)
	var region_snapshot_key := ",".join(_loaded_region_ids)
	if _headless_test_region_snapshots.is_empty() or _headless_test_region_snapshots[-1] != region_snapshot_key:
		_headless_test_region_snapshots.append(region_snapshot_key)
	var detail_snapshot := []
	for tile_id in coarse_snapshot:
		var tile_entry: Dictionary = _loaded_tiles.get(tile_id, {})
		if bool(tile_entry.get("detail_loaded", false)):
			detail_snapshot.append(str(tile_id))
	var detail_snapshot_key := ",".join(detail_snapshot)
	if _headless_test_detail_snapshots.is_empty() or _headless_test_detail_snapshots[-1] != detail_snapshot_key:
		_headless_test_detail_snapshots.append(detail_snapshot_key)


func _run_headless_test(delta: float) -> void:
	if not _headless_test_enabled or _headless_test_completed:
		return
	_headless_test_elapsed_s += delta
	_sample_runtime_metrics()
	if _headless_test_elapsed_s >= 20.0:
		_headless_assert(false, "headless runtime assertions timed out")
		_finish_headless_test(1)
		return
	if not _loaded_region_ids.is_empty():
		for region_id in _loaded_region_ids:
			if not _headless_test_seen_regions.has(region_id):
				_headless_test_seen_regions.append(region_id)
	if _headless_test_state == "ride" and _route_progress_m + 0.01 < _headless_test_last_progress_m:
		_headless_assert(false, "route progress regressed during headless playback")
	_headless_test_last_progress_m = _route_progress_m
	if _headless_test_progress_samples.size() < 32:
		_headless_test_progress_samples.append(snappedf(_route_progress_m, 0.01))

	match _headless_test_state:
		"idle":
			_headless_assert(_pack.get("pack_version", "") == "phase2", "expected Phase 2 pack in headless test")
			_headless_assert(not _route.is_empty(), "expected an active route in headless test")
			_headless_assert(_route_total_distance_m > 0.0, "expected route distance in headless test")
			_headless_assert(not _loaded_region_ids.is_empty(), "expected at least one loaded stream region")
			_headless_test_state = "ride"
		"ride":
			_route_progress_m = min(_route_total_distance_m, _route_progress_m + 420.0)
			_rider.position = _point_at_distance_m(_route_progress_m)
			_update_follow_camera(0.0)
			_update_streaming()
			if _route_progress_m >= 3200.0 and (_headless_test_seen_regions.size() >= 2 or _headless_test_loaded_tile_snapshots.size() >= 2):
				_headless_test_state = "restart"
		"restart":
			_restart_route()
			_headless_test_state = "verify_restart"
		"verify_restart":
			_headless_assert(_route_progress_m <= 10.0, "route restart did not reset progress")
			if _pack.get("route_catalog", []).size() > 1:
				_select_route_by_index(1)
				_headless_test_state = "verify_route_switch"
			else:
				_headless_test_state = "import_good"
		"verify_route_switch":
			_headless_assert(active_route_id == str(_pack["route_catalog"][1]["route_id"]), "route switch did not activate expected route")
			_headless_assert(_route_progress_m <= 10.0, "route switch did not restart progress")
			_headless_test_state = "import_good"
		"import_good":
			if _headless_test_good_gpx == "":
				_headless_test_state = "import_bad"
			else:
				_headless_assert(_import_route_from_path(_headless_test_good_gpx), "expected headless GPX import to succeed")
				_headless_assert(str(_route.get("source_type", "")) == "gpx_import", "expected imported route to be tagged as gpx_import")
				_headless_test_state = "import_bad"
		"import_bad":
			var route_before_bad_import := active_route_id
			_headless_assert(not _import_route_from_path(_headless_test_bad_gpx, false), "expected missing GPX import to fail")
			_headless_assert(active_route_id == route_before_bad_import, "failed GPX import changed the active route")
			_finish_headless_test(0)


func _finish_headless_test(success_exit_code: int) -> void:
	if not _headless_test_enabled or _headless_test_completed:
		return
	_headless_test_completed = true
	var failures := []
	failures.append_array(_headless_test_failures)
	failures.append_array(_runtime_errors)
	var payload := {
		"ok": failures.is_empty(),
		"active_route_id": active_route_id,
		"failures": failures,
		"loaded_region_snapshots": _headless_test_region_snapshots,
		"loaded_tile_snapshots": _headless_test_loaded_tile_snapshots,
		"detail_tile_snapshots": _headless_test_detail_snapshots,
		"max_loaded_tiles": _max_loaded_tiles_seen,
		"max_detail_tiles": _max_detail_tiles_seen,
		"max_loaded_regions": _max_loaded_regions_seen,
		"max_node_count": _max_node_count_seen,
		"progress_samples_m": _headless_test_progress_samples,
		"route_id": str(_route.get("route_id", "")),
		"runtime_errors": _runtime_errors,
		"seen_regions": _headless_test_seen_regions,
		"stream_region_count": _headless_test_seen_regions.size(),
		"used_first_person_camera": true
	}
	if _headless_test_results_path != "":
		DirAccess.make_dir_recursive_absolute(_headless_test_results_path.get_base_dir())
		var handle := FileAccess.open(_headless_test_results_path, FileAccess.WRITE)
		if handle != null:
			handle.store_string(JSON.stringify(payload, "\t") + "\n")
	get_tree().quit(success_exit_code if failures.is_empty() else 1)
