extends Node3D

const RegionPackLoader = preload("res://addons/procedural_trainer/region_pack_loader.gd")

@export var region_pack_dir := "../../region-data/milwaukee/mke_demo_region_pack"
@export var active_route_id := "oak_leaf_demo_loop"
@export var world_scale := 0.2
@export var elevation_scale := 0.25
@export var python_executable := "python3"
@export var snap_output_dir := ""
@export var rider_mass_kg := 82.0
@export var baseline_power_w := 180.0
@export var baseline_cadence_rpm := 90.0
@export var max_brake_pct := 100.0

const POWER_STEP_W := 25.0
const CADENCE_STEP_RPM := 5.0
const BRAKE_STEP_PCT := 10.0

var _pack: Dictionary = {}
var _route: Dictionary = {}
var _route_points: Array[Vector3] = []
var _route_segment_lengths_world: Array[float] = []
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

@onready var _terrain_root: Node3D = $TerrainRoot
@onready var _biome_root: Node3D = $BiomeRoot
@onready var _road_root: Node3D = $RoadRoot
@onready var _rider: MeshInstance3D = $Rider
@onready var _camera: Camera3D = $Camera3D
@onready var _status_label: Label3D = $StatusLabel
@onready var _hud_label: Label = $CanvasLayer/HudLabel
@onready var _file_dialog: FileDialog = $ImportDialog


func _ready() -> void:
	_reload_pack_and_route()


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


func _process(delta: float) -> void:
	if _route_total_distance_m <= 0.0:
		_update_overlay()
		return

	if not _paused:
		var grade_pct := _grade_at_distance(_route_progress_m)
		var resistance_factor := _resistance_factor(grade_pct)
		var target_speed := _target_speed_mps(grade_pct)
		_current_speed_mps = lerp(_current_speed_mps, target_speed, min(1.0, delta * 1.6))
		_route_progress_m = min(_route_total_distance_m, _route_progress_m + (_current_speed_mps * delta))
		_rider.position = _point_at_distance_m(_route_progress_m)
		_camera.position = _rider.position + Vector3(-8.0, 6.0, -8.0)
		_camera.look_at(_rider.position + Vector3(0.0, 1.0, 0.0))
		_set_status("%s | %s | resistance %.2f" % [_pack["manifest"]["region_id"], _route["route_id"], resistance_factor])

	_update_overlay()


func _reload_pack_and_route(route_override: Dictionary = {}) -> void:
	var loader := RegionPackLoader.new()
	var absolute_region_dir := loader.resolve_repo_relative_path(region_pack_dir)
	var result := loader.load_region_pack(absolute_region_dir)
	if not result.get("ok", false):
		_set_status("Failed to load region pack: %s" % result.get("error", "unknown error"))
		push_error(str(result))
		return

	_pack = result["pack"]
	_build_terrain()
	_build_biomes()
	_build_roads()

	_route = route_override if not route_override.is_empty() else _find_route(active_route_id)
	if _route.is_empty():
		_set_status("No route points available for %s" % active_route_id)
		return

	_build_route()
	_restart_route()


func _restart_route() -> void:
	_route_progress_m = 0.0
	_current_speed_mps = 0.0
	_rider.position = _point_at_distance_m(0.0) if not _route_points.is_empty() else Vector3.ZERO


func _build_terrain() -> void:
	for child in _terrain_root.get_children():
		child.queue_free()

	for chunk in _pack["scenery"]["terrain_chunks"]:
		var mesh_instance := MeshInstance3D.new()
		var plane := PlaneMesh.new()
		plane.size = Vector2(chunk["size_m"][0] * world_scale, chunk["size_m"][1] * world_scale)
		mesh_instance.mesh = plane
		mesh_instance.rotation_degrees.x = -90.0
		mesh_instance.position = Vector3(
			(chunk["origin_m"][0] + (chunk["size_m"][0] / 2.0)) * world_scale,
			_average_grid(chunk["elevation_grid_m"]) * elevation_scale - 0.1,
			(chunk["origin_m"][1] + (chunk["size_m"][1] / 2.0)) * world_scale
		)
		mesh_instance.material_override = _make_material(Color(0.43, 0.49, 0.32), 0.0)
		_terrain_root.add_child(mesh_instance)


func _build_biomes() -> void:
	for child in _biome_root.get_children():
		child.queue_free()

	for biome in _pack["scenery"]["biome_patches"]:
		var bounds := _polygon_bounds(biome["polygon_m"])
		var mesh_instance := MeshInstance3D.new()
		var plane := PlaneMesh.new()
		plane.size = Vector2(bounds.size.x * world_scale, bounds.size.y * world_scale)
		mesh_instance.mesh = plane
		mesh_instance.rotation_degrees.x = -90.0
		mesh_instance.position = Vector3(
			(bounds.position.x + (bounds.size.x / 2.0)) * world_scale,
			0.05,
			(bounds.position.y + (bounds.size.y / 2.0)) * world_scale
		)
		mesh_instance.material_override = _make_material(Color.from_string(biome["color_hint"], Color(0.5, 0.7, 0.5)), 0.35)
		_biome_root.add_child(mesh_instance)


func _build_roads() -> void:
	for child in _road_root.get_children():
		child.queue_free()

	var road_materials := {
		"asphalt": _make_material(Color(0.12, 0.12, 0.12), 0.0),
		"packed_gravel": _make_material(Color(0.42, 0.36, 0.24), 0.0)
	}
	var ride_graph_edges: Array = _pack["ride_graph"]["edges"]
	var road_segment_lookup := {}
	for segment in _pack["scenery"]["road_segments"]:
		road_segment_lookup[segment["edge_id"]] = segment

	for edge in ride_graph_edges:
		var road_style: Dictionary = road_segment_lookup.get(edge["edge_id"], {"width_m": 4.0, "material": "asphalt"})
		var geometry: Array = edge["geometry_m"]
		var elevations: Array = edge["elevation_profile_m"]
		for index in range(geometry.size() - 1):
			var start_point := _to_world(geometry[index], elevations[index])
			var end_point := _to_world(geometry[index + 1], elevations[index + 1])
			var direction := end_point - start_point
			var road_piece := MeshInstance3D.new()
			var box := BoxMesh.new()
			box.size = Vector3(road_style["width_m"] * world_scale, 0.15, direction.length())
			road_piece.mesh = box
			road_piece.position = (start_point + end_point) / 2.0
			road_piece.rotation.y = atan2(direction.x, direction.z)
			road_piece.material_override = road_materials.get(road_style["material"], road_materials["asphalt"])
			_road_root.add_child(road_piece)


func _build_route() -> void:
	_route_points.clear()
	_route_segment_lengths_world.clear()
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

	for index in range(_route_points.size() - 1):
		_route_segment_lengths_world.append(_route_points[index].distance_to(_route_points[index + 1]))
	_route_total_distance_m = float(_route["distance_m"])


func _find_route(route_id: String) -> Dictionary:
	for route in _pack["routes"]:
		if route["route_id"] == route_id:
			return route
	return {}


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
			return {"edge_id": edge_id, "segment_index": edge_index}
		accumulated = next_accumulated
	return {
		"edge_id": str(_route["snapped_edge_sequence"][-1]) if not _route["snapped_edge_sequence"].is_empty() else "n/a",
		"segment_index": max(0, _route["snapped_edge_sequence"].size() - 1)
	}


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


func _on_import_dialog_file_selected(path: String) -> void:
	var loader := RegionPackLoader.new()
	var absolute_region_dir := loader.resolve_repo_relative_path(region_pack_dir)
	var repo_root := absolute_region_dir.get_base_dir().get_base_dir().get_base_dir()
	var cli_path := repo_root.path_join("geo-pipeline/run_geo_pipeline_cli.py")
	var output_dir := snap_output_dir
	if output_dir == "":
		output_dir = "user://snapped_routes"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(output_dir))
	var output_path := ProjectSettings.globalize_path(output_dir).path_join("%s.route.json" % path.get_file().get_basename())
	var output: Array = []
	var exit_code := OS.execute(
		python_executable,
		PackedStringArray([
			cli_path,
			"snap-gpx",
			absolute_region_dir,
			path,
			"--output",
			output_path
		]),
		output,
		true
	)
	if exit_code != 0:
		_import_status = "GPX import failed: %s" % "\n".join(output)
		_set_status(_import_status)
		return

	var file := FileAccess.open(output_path, FileAccess.READ)
	if file == null:
		_import_status = "GPX snap output missing: %s" % output_path
		_set_status(_import_status)
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		_import_status = "GPX snap output was not a route definition"
		_set_status(_import_status)
		return

	_import_status = "Imported %s" % path.get_file()
	active_route_id = str(parsed["route_id"])
	_reload_pack_and_route(parsed)


func _to_world(point_m: Array, elevation_m: float) -> Vector3:
	return Vector3(point_m[0] * world_scale, elevation_m * elevation_scale, point_m[1] * world_scale)


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


func _make_material(albedo: Color, alpha: float) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(albedo.r, albedo.g, albedo.b, 1.0 - alpha)
	if alpha > 0.0:
		material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	return material


func _set_status(text: String) -> void:
	_status_label.text = text


func _update_overlay() -> void:
	var edge_status := _edge_status_at_distance(_route_progress_m)
	var grade_pct := _grade_at_distance(_route_progress_m)
	var resistance_factor := _resistance_factor(grade_pct)
	_hud_label.text = "\n".join([
		"route: %s" % str(_route.get("route_id", active_route_id)),
		"progress: %.1f / %.1f m" % [_route_progress_m, _route_total_distance_m],
		"grade: %.2f%%" % grade_pct,
		"speed: %.2f m/s" % _current_speed_mps,
		"power: %.0f W" % _simulated_power_w,
		"cadence: %.0f rpm" % _simulated_cadence_rpm,
		"brake: %.0f%%" % _brake_pct,
		"resistance: %.2f" % resistance_factor,
		"edge: %s / segment %d" % [str(edge_status["edge_id"]), int(edge_status["segment_index"])],
		"keys: W/S power  A/D brake  Q/E cadence  Space clear brake",
		"R restart  P pause  I import GPX  Tab overlay",
		_import_status
	]).strip_edges()
