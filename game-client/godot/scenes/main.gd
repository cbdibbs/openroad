extends Node3D

const RegionPackLoader = preload("res://addons/procedural_trainer/region_pack_loader.gd")

@export var region_pack_dir := "../../region-data/milwaukee/mke_phase2_live_region_pack"
@export var active_route_id := "starter_cross_city_connector"
@export var default_gpx_path := "../../sample-tracks/Wauwatosa_to_Lakefront.gpx"
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
const CAMERA_DISTANCE_M := 18.0
const CAMERA_HEIGHT_M := 7.5
const CAMERA_LOOKAHEAD_M := 20.0
const CAMERA_LERP_RATE := 4.5

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
var _loaded_tile_nodes := {}
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
var _headless_test_loaded_snapshots: Array[String] = []
var _headless_test_last_progress_m := -1.0
var _headless_test_elapsed_s := 0.0
var _camera_initialized := false

@onready var _terrain_root: Node3D = $TerrainRoot
@onready var _water_root: Node3D = $WaterRoot
@onready var _biome_root: Node3D = $BiomeRoot
@onready var _street_root: Node3D = $StreetRoot
@onready var _road_root: Node3D = $RoadRoot
@onready var _building_root: Node3D = $BuildingRoot
@onready var _landmark_root: Node3D = $LandmarkRoot
@onready var _prop_root: Node3D = $PropRoot
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
		_update_overlay()
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

	_update_overlay()
	_run_headless_test(delta)


func _load_pack() -> bool:
	var result := _loader.load_region_pack(_region_dir)
	if not result.get("ok", false):
		var error_text := "Failed to load region pack: %s" % result.get("error", "unknown error")
		_record_runtime_error(error_text)
		_set_status(error_text)
		push_error(str(result))
		return false

	_pack = result["pack"]
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

	var edge_lookup := {}
	for edge in _pack["ride_graph"]["edges"]:
		edge_lookup[edge["edge_id"]] = edge

	var distance_offset := 0.0
	for edge_id in _route["snapped_edge_sequence"]:
		var edge: Dictionary = edge_lookup[edge_id]
		var geometry: Array = edge["geometry_m"]
		var elevations: Array = edge["elevation_profile_m"]
		var distances: Array = edge["distance_profile_m"]
		for index in range(geometry.size()):
			if not _route_points.is_empty() and index == 0:
				continue
			_route_points.append(_to_world(geometry[index], elevations[index]))
			_route_distances_m.append(distance_offset + distances[index])
		distance_offset += edge["length_m"]
	_route_total_distance_m = float(_route["distance_m"])


func _update_streaming() -> void:
	if _pack.get("pack_version", "phase1") != "phase2":
		_build_phase1_world()
		return

	var point_m := _route_point_m_at_distance(_route_progress_m)
	var current_region_id := _stream_region_id_for_point(point_m)
	if current_region_id == "":
		if not _loaded_region_ids.is_empty():
			current_region_id = _loaded_region_ids[0]
		else:
			return
	var target_region_ids: Array[String] = [current_region_id]
	var region_index: Dictionary = _pack.get("streaming_region_index", {})
	var current_region: Dictionary = region_index.get(current_region_id, {})
	for neighbor_id in current_region.get("neighbor_region_ids", []):
		target_region_ids.append(str(neighbor_id))
	target_region_ids.sort()
	if target_region_ids == _loaded_region_ids:
		return

	var target_tile_ids := {}
	for region_id in target_region_ids:
		var stream_region: Dictionary = region_index.get(region_id, {})
		for tile_id in stream_region.get("tile_ids", []):
			target_tile_ids[str(tile_id)] = true

	for tile_id in _loaded_tile_nodes.keys():
		if not target_tile_ids.has(tile_id):
			_unload_tile(str(tile_id))

	for tile_id in target_tile_ids.keys():
		if not _loaded_tile_nodes.has(tile_id):
			_load_tile(str(tile_id))

	_loaded_region_ids = target_region_ids


func _build_phase1_world() -> void:
	if not _loaded_tile_nodes.is_empty():
		return
	var tile_id := "phase1"
	_loaded_tile_nodes[tile_id] = true
	_build_tile_visuals({"tile_id": tile_id}, {"ride_graph": _pack["ride_graph"], "scenery": _pack["scenery"]})


func _load_tile(tile_id: String) -> void:
	var tile_info: Dictionary = _pack["tile_index"].get(tile_id, {})
	if tile_info.is_empty():
		return
	var result: Dictionary = _loader.load_tile_pack(_region_dir, str(tile_info["manifest_asset"]))
	if not result.get("ok", false):
		_import_status = "Tile load failed: %s" % tile_id
		_record_runtime_error(_import_status)
		return
	_loaded_tile_nodes[tile_id] = true
	_build_tile_visuals(tile_info, result["tile"])


func _unload_tile(tile_id: String) -> void:
	var roots: Array[Node3D] = [_terrain_root, _water_root, _biome_root, _street_root, _road_root, _building_root, _landmark_root, _prop_root]
	for root in roots:
		for child in root.get_children():
			if child.has_meta("tile_id") and str(child.get_meta("tile_id")) == tile_id:
				child.queue_free()
	_loaded_tile_nodes.erase(tile_id)


func _clear_loaded_tiles() -> void:
	for tile_id in _loaded_tile_nodes.keys():
		_unload_tile(str(tile_id))
	_loaded_region_ids.clear()


func _build_tile_visuals(tile_info: Dictionary, tile_pack: Dictionary) -> void:
	_build_terrain(tile_info, tile_pack["scenery"])
	_build_water(tile_info, tile_pack["scenery"])
	_build_biomes(tile_info, tile_pack["scenery"])
	_build_streets(tile_info, tile_pack["scenery"])
	_build_roads(tile_info, tile_pack["ride_graph"], tile_pack["scenery"])
	_build_buildings(tile_info, tile_pack["scenery"])
	_build_landmarks(tile_info, tile_pack["scenery"])
	_build_props(tile_info, tile_pack["scenery"])


func _build_terrain(tile_info: Dictionary, scenery: Dictionary) -> void:
	var terrain_color := Color.from_string(str(scenery.get("style_hints", {}).get("terrain_tint", "#6b7d59")), Color(0.42, 0.49, 0.33))
	for chunk in scenery["terrain_chunks"]:
		var mesh_instance := MeshInstance3D.new()
		mesh_instance.mesh = _build_terrain_mesh(chunk)
		mesh_instance.material_override = _make_material(terrain_color, 0.0)
		mesh_instance.set_meta("tile_id", tile_info["tile_id"])
		_terrain_root.add_child(mesh_instance)


func _build_water(tile_info: Dictionary, scenery: Dictionary) -> void:
	for patch in scenery.get("water_patches", []):
		var mesh_instance := MeshInstance3D.new()
		var center_m := _polygon_center(patch["polygon_m"])
		var base_elevation := _scenery_height_at_point_m(scenery, center_m)
		mesh_instance.mesh = _build_flat_polygon_mesh(patch["polygon_m"], base_elevation + 0.03)
		mesh_instance.material_override = _make_material(Color(0.30, 0.58, 0.72), 0.18)
		mesh_instance.set_meta("tile_id", tile_info["tile_id"])
		_water_root.add_child(mesh_instance)


func _build_biomes(tile_info: Dictionary, scenery: Dictionary) -> void:
	for biome in scenery.get("biome_patches", []):
		var bounds := _polygon_bounds(biome["polygon_m"])
		var biome_color := Color.from_string(biome["color_hint"], Color(0.5, 0.7, 0.5)).darkened(0.02)
		var landcover_class := str(biome.get("landcover_class", "parkland"))
		var scatter_count: int = max(3, min(7, int(round(max(bounds.size.x, bounds.size.y) / 260.0))))
		for index in range(scatter_count):
			var sample_m := [
				bounds.position.x + (bounds.size.x * float(index + 1) / float(scatter_count + 1)),
				bounds.position.y + (bounds.size.y * float(((index * 3) % (scatter_count + 1)) + 1) / float(scatter_count + 1))
			]
			var base_elevation := _scenery_height_at_point_m(scenery, sample_m)
			var shrub := MeshInstance3D.new()
			if ["urban_core", "mixed_use"].has(landcover_class):
				var plaza := BoxMesh.new()
				plaza.size = Vector3(4.0 + float(index % 2) * 1.6, 0.35, 4.0 + float((index + 1) % 2) * 1.6)
				shrub.mesh = plaza
				shrub.position = Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale + 0.18, sample_m[1] * world_scale)
				shrub.material_override = _make_material(biome_color.lightened(0.02 * float(index % 2)), 0.0)
			else:
				var canopy := SphereMesh.new()
				canopy.radius = 0.8 + float(index % 3) * 0.25
				canopy.height = canopy.radius * 2.0
				shrub.mesh = canopy
				shrub.position = Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale + canopy.radius * 0.55, sample_m[1] * world_scale)
				shrub.scale = Vector3(1.2, 0.6, 1.2)
				shrub.material_override = _make_material(biome_color.lightened(0.03 * float(index % 2)), 0.0)
			shrub.set_meta("tile_id", tile_info["tile_id"])
			_biome_root.add_child(shrub)


func _build_roads(tile_info: Dictionary, ride_graph: Dictionary, scenery: Dictionary) -> void:
	var road_materials := {
		"asphalt": _make_material(Color(0.12, 0.12, 0.12), 0.0),
		"packed_gravel": _make_material(Color(0.42, 0.36, 0.24), 0.0)
	}
	var road_segment_lookup := {}
	for segment in scenery["road_segments"]:
		road_segment_lookup[segment["edge_id"]] = segment

	for edge in ride_graph["edges"]:
		var road_style: Dictionary = road_segment_lookup.get(edge["edge_id"], {"width_m": 4.0, "material": "asphalt"})
		var road_piece := MeshInstance3D.new()
		road_piece.mesh = _build_road_ribbon_mesh(edge["geometry_m"], edge["elevation_profile_m"], float(road_style["width_m"]))
		road_piece.material_override = road_materials.get(str(road_style["material"]), road_materials["asphalt"])
		road_piece.set_meta("tile_id", tile_info["tile_id"])
		_road_root.add_child(road_piece)


func _build_streets(tile_info: Dictionary, scenery: Dictionary) -> void:
	var street_materials := {
		"asphalt": _make_material(Color(0.25, 0.25, 0.27), 0.0),
		"packed_gravel": _make_material(Color(0.45, 0.40, 0.32), 0.0),
		"trail": _make_material(Color(0.52, 0.48, 0.38), 0.0)
	}
	for segment in scenery.get("street_segments", []):
		var street_piece := MeshInstance3D.new()
		street_piece.mesh = _build_road_ribbon_mesh(segment["geometry_m"], segment["elevation_profile_m"], float(segment["width_m"]))
		street_piece.material_override = street_materials.get(str(segment.get("material", "asphalt")), street_materials["asphalt"])
		street_piece.set_meta("tile_id", tile_info["tile_id"])
		_street_root.add_child(street_piece)


func _build_buildings(tile_info: Dictionary, scenery: Dictionary) -> void:
	for building in scenery.get("buildings", []):
		var mesh_instance := MeshInstance3D.new()
		var bounds := _polygon_bounds(building["footprint_m"])
		var center_m := [bounds.position.x + (bounds.size.x / 2.0), bounds.position.y + (bounds.size.y / 2.0)]
		var base_elevation := _scenery_height_at_point_m(scenery, center_m)
		mesh_instance.mesh = _build_extruded_polygon_mesh(building["footprint_m"], float(building["height_m"]), base_elevation)
		mesh_instance.material_override = _make_material(_building_color_for_kind(str(building.get("kind", "default"))), 0.0)
		mesh_instance.set_meta("tile_id", tile_info["tile_id"])
		_building_root.add_child(mesh_instance)


func _build_landmarks(tile_info: Dictionary, scenery: Dictionary) -> void:
	for landmark in scenery.get("landmarks", []):
		var marker := MeshInstance3D.new()
		var marker_mesh := BoxMesh.new()
		marker_mesh.size = Vector3(1.8, 6.0, 1.8)
		marker.mesh = marker_mesh
		var base_elevation := _scenery_height_at_point_m(scenery, landmark["point_m"])
		marker.position = Vector3(
			float(landmark["point_m"][0]) * world_scale,
			base_elevation * elevation_scale + marker_mesh.size.y / 2.0,
			float(landmark["point_m"][1]) * world_scale
		)
		marker.material_override = _make_material(_landmark_color_for_kind(str(landmark.get("kind", "landmark"))), 0.0)
		marker.set_meta("tile_id", tile_info["tile_id"])
		_landmark_root.add_child(marker)


func _build_props(tile_info: Dictionary, scenery: Dictionary) -> void:
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
			if prop_class == "street_trees":
				var street_tree := _create_tree_cluster(
					Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale, sample_m[1] * world_scale),
					1.6 + density * 0.5,
					0.65 + density * 0.35,
					Color(0.24, 0.45, 0.22).lightened(0.01 * float(index % 3)),
					tile_info["tile_id"]
				)
				_prop_root.add_child(street_tree)
			elif prop_class == "shoreline_grass":
				var tuft := MeshInstance3D.new()
				var tuft_mesh := SphereMesh.new()
				tuft_mesh.radius = 0.45 + density * 0.18
				tuft_mesh.height = 0.55
				tuft.mesh = tuft_mesh
				tuft.scale = Vector3(1.0, 0.35, 1.0)
				tuft.position = Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale + 0.12, sample_m[1] * world_scale)
				tuft.material_override = _make_material(Color(0.78, 0.77, 0.52).darkened(0.02 * float(index % 2)), 0.0)
				tuft.set_meta("tile_id", tile_info["tile_id"])
				_prop_root.add_child(tuft)
			else:
				var tree_node := _create_tree_cluster(
					Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale, sample_m[1] * world_scale),
					1.2 + density * 0.7 + float(index % 3) * 0.18,
					0.75 + density * 0.55,
					Color(0.22, 0.47, 0.26).lightened(0.02 * float(index % 4)),
					tile_info["tile_id"]
				)
				_prop_root.add_child(tree_node)

	if scenery.get("prop_masks", []).is_empty():
		_build_roadside_trees(tile_info, scenery)


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
	if _route_points.size() == 1:
		return _route_points[0]
	for index in range(_route_distances_m.size() - 1):
		var start_distance := float(_route_distances_m[index])
		var end_distance := float(_route_distances_m[index + 1])
		if distance_along_route_m <= end_distance:
			var span: float = max(0.001, end_distance - start_distance)
			var ratio: float = clamp((distance_along_route_m - start_distance) / span, 0.0, 1.0)
			return _route_points[index].lerp(_route_points[index + 1], ratio)
	return _route_points[-1]


func _route_point_m_at_distance(distance_along_route_m: float) -> Vector2:
	var world_point := _point_at_distance_m(distance_along_route_m)
	return Vector2(world_point.x / world_scale, world_point.z / world_scale)


func _stream_region_id_for_point(point_m: Vector2) -> String:
	for region in _pack.get("streaming_regions", []):
		var origin: Array = region["origin_m"]
		var size: Array = region["size_m"]
		if point_m.x >= float(origin[0]) and point_m.x < float(origin[0]) + float(size[0]) and point_m.y >= float(origin[1]) and point_m.y < float(origin[1]) + float(size[1]):
			return str(region["stream_region_id"])
	return ""


func _update_follow_camera(delta: float) -> void:
	var forward := _forward_direction_at_distance(_route_progress_m)
	var desired_position := _rider.position - forward * CAMERA_DISTANCE_M + Vector3(0.0, CAMERA_HEIGHT_M, 0.0)
	if not _camera_initialized or delta <= 0.0:
		_camera.position = desired_position
		_camera_initialized = true
	else:
		_camera.position = _camera.position.lerp(desired_position, min(1.0, delta * CAMERA_LERP_RATE))
	_camera.look_at(_rider.position + forward * CAMERA_LOOKAHEAD_M + Vector3(0.0, 1.5, 0.0))


func _forward_direction_at_distance(distance_along_route_m: float) -> Vector3:
	if _route_points.size() < 2:
		return Vector3.FORWARD
	var look_behind := _point_at_distance_m(max(0.0, distance_along_route_m - 6.0))
	var look_ahead := _point_at_distance_m(min(_route_total_distance_m, distance_along_route_m + 12.0))
	var direction := look_ahead - look_behind
	if direction.length() < 0.001:
		return Vector3.FORWARD
	direction.y = 0.0
	return direction.normalized()


func _grade_at_distance(distance_along_route_m: float) -> float:
	var grades: Array = _route.get("grade_profile_pct", [])
	var distances: Array = _route.get("distance_profile_m", [])
	if grades.is_empty() or distances.is_empty():
		return 0.0
	for index in range(distances.size() - 1):
		if distance_along_route_m <= float(distances[index + 1]):
			return float(grades[index])
	return float(grades[-1])


func _edge_status_at_distance(distance_along_route_m: float) -> Dictionary:
	var edge_lookup := {}
	for edge in _pack["ride_graph"]["edges"]:
		edge_lookup[edge["edge_id"]] = edge
	var accumulated := 0.0
	for edge_index in range(_route["snapped_edge_sequence"].size()):
		var edge_id: String = _route["snapped_edge_sequence"][edge_index]
		var edge: Dictionary = edge_lookup[edge_id]
		var next_accumulated: float = accumulated + float(edge["length_m"])
		if distance_along_route_m <= next_accumulated:
			return {"edge_id": edge_id, "segment_index": edge_index, "stream_region_id": str(edge.get("stream_region_id", "phase1"))}
		accumulated = next_accumulated
	return {"edge_id": "n/a", "segment_index": 0, "stream_region_id": "n/a"}


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
	var repo_root := _region_dir.get_base_dir().get_base_dir().get_base_dir()
	var cli_path := repo_root.path_join("geo-pipeline/run_geo_pipeline_cli.py")
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
	return Vector3(point_m[0] * world_scale, elevation_m * elevation_scale, point_m[1] * world_scale)


func _build_terrain_mesh(chunk: Dictionary) -> ArrayMesh:
	var grid: Array = chunk["elevation_grid_m"]
	var rows: int = grid.size()
	var first_row: Array = grid[0]
	var columns: int = first_row.size()
	var step_m: float = float(chunk["sample_spacing_m"])
	var origin: Array = chunk["origin_m"]
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for row in range(rows - 1):
		for column in range(columns - 1):
			var a := _to_world([origin[0] + column * step_m, origin[1] + row * step_m], float(grid[row][column]))
			var b := _to_world([origin[0] + (column + 1) * step_m, origin[1] + row * step_m], float(grid[row][column + 1]))
			var c := _to_world([origin[0] + column * step_m, origin[1] + (row + 1) * step_m], float(grid[row + 1][column]))
			var d := _to_world([origin[0] + (column + 1) * step_m, origin[1] + (row + 1) * step_m], float(grid[row + 1][column + 1]))
			surface.add_vertex(a)
			surface.add_vertex(c)
			surface.add_vertex(b)
			surface.add_vertex(b)
			surface.add_vertex(c)
			surface.add_vertex(d)
	surface.generate_normals()
	return surface.commit()


func _build_road_ribbon_mesh(geometry_m: Array, elevations_m: Array, width_m: float) -> ArrayMesh:
	if geometry_m.size() < 2 or geometry_m.size() != elevations_m.size():
		return ArrayMesh.new()
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
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for index in range(left_points.size() - 1):
		var a := left_points[index]
		var b := right_points[index]
		var c := left_points[index + 1]
		var d := right_points[index + 1]
		surface.add_vertex(a)
		surface.add_vertex(c)
		surface.add_vertex(b)
		surface.add_vertex(b)
		surface.add_vertex(c)
		surface.add_vertex(d)
	surface.generate_normals()
	return surface.commit()


func _build_extruded_polygon_mesh(points_m: Array, height_m: float, base_elevation_m: float) -> ArrayMesh:
	if points_m.size() < 3:
		return ArrayMesh.new()
	var base_ring: Array[Vector3] = []
	var top_ring: Array[Vector3] = []
	for point_m in points_m:
		var base_point := _to_world(point_m, base_elevation_m)
		base_ring.append(base_point)
		top_ring.append(base_point + Vector3(0.0, height_m * elevation_scale, 0.0))
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for index in range(1, top_ring.size() - 1):
		surface.add_vertex(top_ring[0])
		surface.add_vertex(top_ring[index])
		surface.add_vertex(top_ring[index + 1])
	for index in range(base_ring.size()):
		var next_index := (index + 1) % base_ring.size()
		var a := base_ring[index]
		var b := base_ring[next_index]
		var c := top_ring[index]
		var d := top_ring[next_index]
		surface.add_vertex(a)
		surface.add_vertex(b)
		surface.add_vertex(c)
		surface.add_vertex(c)
		surface.add_vertex(b)
		surface.add_vertex(d)
	surface.generate_normals()
	return surface.commit()


func _build_flat_polygon_mesh(points_m: Array, elevation_m: float) -> ArrayMesh:
	if points_m.size() < 3:
		return ArrayMesh.new()
	var vertices: Array[Vector3] = []
	for point_m in points_m:
		vertices.append(_to_world(point_m, elevation_m))
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for index in range(1, vertices.size() - 1):
		surface.add_vertex(vertices[0])
		surface.add_vertex(vertices[index])
		surface.add_vertex(vertices[index + 1])
	surface.generate_normals()
	return surface.commit()


func _average_grid(grid: Array) -> float:
	var total := 0.0
	var count := 0.0
	for row in grid:
		for value in row:
			total += value
			count += 1.0
	return total / max(count, 1.0)


func _polygon_bounds(points: Array) -> Rect2:
	var min_x := INF
	var min_y := INF
	var max_x := -INF
	var max_y := -INF
	for point in points:
		min_x = min(min_x, point[0])
		min_y = min(min_y, point[1])
		max_x = max(max_x, point[0])
		max_y = max(max_y, point[1])
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
	var first_row: Array = grid[0]
	var columns: int = first_row.size()
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


func _make_material(albedo: Color, alpha: float) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(albedo.r, albedo.g, albedo.b, 1.0 - alpha)
	material.roughness = 1.0
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	if enable_low_poly_shading:
		material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	if alpha > 0.0:
		material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	return material


func _create_tree_cluster(base_position: Vector3, trunk_height: float, canopy_radius: float, canopy_color: Color, tile_id: String) -> Node3D:
	var root := Node3D.new()
	root.position = base_position
	root.set_meta("tile_id", tile_id)

	var trunk := MeshInstance3D.new()
	var trunk_mesh := CylinderMesh.new()
	trunk_mesh.top_radius = 0.08
	trunk_mesh.bottom_radius = 0.12
	trunk_mesh.height = trunk_height
	trunk.mesh = trunk_mesh
	trunk.position = Vector3(0.0, trunk_height / 2.0, 0.0)
	trunk.material_override = _make_material(Color(0.34, 0.24, 0.12), 0.0)
	root.add_child(trunk)

	var canopy := MeshInstance3D.new()
	var canopy_mesh := SphereMesh.new()
	canopy_mesh.radius = canopy_radius
	canopy_mesh.height = canopy_radius * 2.0
	canopy.mesh = canopy_mesh
	canopy.position = Vector3(0.0, trunk_height + canopy_radius * 0.75, 0.0)
	canopy.scale = Vector3(1.15, 0.9, 1.15)
	canopy.material_override = _make_material(canopy_color, 0.0)
	root.add_child(canopy)

	return root


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


func _build_roadside_trees(tile_info: Dictionary, scenery: Dictionary) -> void:
	var road_segments: Array = scenery.get("road_segments", [])
	if road_segments.is_empty():
		return
	var edge_lookup := {}
	for edge in _pack["ride_graph"]["edges"]:
		edge_lookup[edge["edge_id"]] = edge
	for segment in road_segments:
		var edge: Dictionary = edge_lookup.get(segment["edge_id"], {})
		if edge.is_empty():
			continue
		var geometry: Array = edge["geometry_m"]
		var elevations: Array = edge["elevation_profile_m"]
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
				var tree := _create_tree_cluster(
					Vector3(sample_m[0] * world_scale, base_elevation * elevation_scale, sample_m[1] * world_scale),
					1.3,
					0.7,
					Color(0.24, 0.51, 0.28),
					tile_info["tile_id"]
				)
				_prop_root.add_child(tree)


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
		"keys: [ ] or 1/2/3/4 routes  W/S power  A/D brake  Q/E cadence",
		"R restart  P pause  I import GPX  Tab overlay",
		_import_status
	]).strip_edges()


func _headless_assert(condition: bool, failure_message: String) -> void:
	if condition:
		return
	if not _headless_test_failures.has(failure_message):
		_headless_test_failures.append(failure_message)


func _run_headless_test(delta: float) -> void:
	if not _headless_test_enabled or _headless_test_completed:
		return
	_headless_test_elapsed_s += delta
	if _headless_test_elapsed_s >= 20.0:
		_headless_assert(false, "headless runtime assertions timed out")
		_finish_headless_test(1)
		return
	if not _loaded_region_ids.is_empty():
		var current_region := _loaded_region_ids[0]
		if not _headless_test_seen_regions.has(current_region):
			_headless_test_seen_regions.append(current_region)
		var loaded_snapshot := ",".join(_loaded_region_ids)
		if _headless_test_loaded_snapshots.is_empty() or _headless_test_loaded_snapshots[-1] != loaded_snapshot:
			_headless_test_loaded_snapshots.append(loaded_snapshot)
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
			_update_streaming()
			if _route_progress_m >= 3200.0 and (_headless_test_seen_regions.size() >= 2 or _headless_test_loaded_snapshots.size() >= 2):
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
		"loaded_region_snapshots": _headless_test_loaded_snapshots,
		"progress_samples_m": _headless_test_progress_samples,
		"route_id": str(_route.get("route_id", "")),
		"runtime_errors": _runtime_errors,
		"seen_regions": _headless_test_seen_regions,
		"stream_region_count": _headless_test_seen_regions.size(),
	}
	if _headless_test_results_path != "":
		DirAccess.make_dir_recursive_absolute(_headless_test_results_path.get_base_dir())
		var handle := FileAccess.open(_headless_test_results_path, FileAccess.WRITE)
		if handle != null:
			handle.store_string(JSON.stringify(payload, "\t") + "\n")
	get_tree().quit(success_exit_code if failures.is_empty() else 1)
