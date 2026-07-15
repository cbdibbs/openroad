extends Node3D

const RegionPackLoader = preload("res://addons/procedural_trainer/region_pack_loader.gd")

@export var region_pack_dir := "../../region-data/milwaukee/mke_phase2_region_pack"
@export var active_route_id := "starter_cross_city"
@export var world_scale := 0.18
@export var elevation_scale := 0.24
@export var python_executable := "python3"
@export var snap_output_dir := ""
@export var rider_mass_kg := 82.0
@export var baseline_power_w := 180.0
@export var baseline_cadence_rpm := 90.0
@export var max_brake_pct := 100.0

const POWER_STEP_W := 25.0
const CADENCE_STEP_RPM := 5.0
const BRAKE_STEP_PCT := 10.0
const ROAD_SURFACE_CLEARANCE_M := 0.02

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

@onready var _terrain_root: Node3D = $TerrainRoot
@onready var _biome_root: Node3D = $BiomeRoot
@onready var _road_root: Node3D = $RoadRoot
@onready var _building_root: Node3D = $BuildingRoot
@onready var _prop_root: Node3D = $PropRoot
@onready var _rider: MeshInstance3D = $Rider
@onready var _camera: Camera3D = $Camera3D
@onready var _status_label: Label3D = $StatusLabel
@onready var _hud_label: Label = $CanvasLayer/HudLabel
@onready var _file_dialog: FileDialog = $ImportDialog


func _ready() -> void:
	_region_dir = _loader.resolve_repo_relative_path(region_pack_dir)
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
			KEY_BRACKETLEFT:
				_select_route_delta(-1)
			KEY_BRACKETRIGHT:
				_select_route_delta(1)
			KEY_1, KEY_2, KEY_3, KEY_4:
				_select_route_by_number(int(event.keycode - KEY_1))


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
		_camera.position = _rider.position + Vector3(-9.0, 6.5, -9.0)
		_camera.look_at(_rider.position + Vector3(0.0, 1.0, 0.0))
		_update_streaming()
		_set_status("%s | %s | resistance %.2f" % [_pack["manifest"]["region_id"], _route["route_id"], resistance_factor])

	_update_overlay()


func _reload_pack_and_route(route_override: Dictionary = {}) -> void:
	var result := _loader.load_region_pack(_region_dir)
	if not result.get("ok", false):
		_set_status("Failed to load region pack: %s" % result.get("error", "unknown error"))
		push_error(str(result))
		return

	_pack = result["pack"]
	_route = route_override if not route_override.is_empty() else _find_route(active_route_id)
	if _route.is_empty() and not _pack.get("routes", []).is_empty():
		_route = _pack["routes"][0]
		active_route_id = str(_route["route_id"])
	if _route.is_empty():
		_set_status("No route points available")
		return

	_sync_selected_route_index()
	_clear_loaded_tiles()
	_build_route()
	_restart_route()


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
		return
	_loaded_tile_nodes[tile_id] = true
	_build_tile_visuals(tile_info, result["tile"])


func _unload_tile(tile_id: String) -> void:
	var roots: Array[Node3D] = [_terrain_root, _biome_root, _road_root, _building_root, _prop_root]
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
	_build_biomes(tile_info, tile_pack["scenery"])
	_build_roads(tile_info, tile_pack["ride_graph"], tile_pack["scenery"])
	_build_buildings(tile_info, tile_pack["scenery"])
	_build_props(tile_info, tile_pack["scenery"])


func _build_terrain(tile_info: Dictionary, scenery: Dictionary) -> void:
	for chunk in scenery["terrain_chunks"]:
		var mesh_instance := MeshInstance3D.new()
		mesh_instance.mesh = _build_terrain_mesh(chunk)
		mesh_instance.material_override = _make_material(Color(0.42, 0.49, 0.33), 0.0)
		mesh_instance.set_meta("tile_id", tile_info["tile_id"])
		_terrain_root.add_child(mesh_instance)


func _build_biomes(tile_info: Dictionary, scenery: Dictionary) -> void:
	for biome in scenery.get("biome_patches", []):
		var bounds := _polygon_bounds(biome["polygon_m"])
		var mesh_instance := MeshInstance3D.new()
		var plane := PlaneMesh.new()
		plane.size = Vector2(bounds.size.x * world_scale, bounds.size.y * world_scale)
		mesh_instance.mesh = plane
		mesh_instance.rotation_degrees.x = -90.0
		mesh_instance.position = Vector3(
			(bounds.position.x + (bounds.size.x / 2.0)) * world_scale,
			0.08,
			(bounds.position.y + (bounds.size.y / 2.0)) * world_scale
		)
		mesh_instance.material_override = _make_material(Color.from_string(biome["color_hint"], Color(0.5, 0.7, 0.5)), 0.32)
		mesh_instance.set_meta("tile_id", tile_info["tile_id"])
		_biome_root.add_child(mesh_instance)


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
		var geometry: Array = edge["geometry_m"]
		var elevations: Array = edge["elevation_profile_m"]
		for index in range(geometry.size() - 1):
			var road_piece := MeshInstance3D.new()
			road_piece.mesh = _build_road_mesh(
				geometry[index],
				elevations[index],
				geometry[index + 1],
				elevations[index + 1],
				float(road_style["width_m"])
			)
			road_piece.material_override = road_materials.get(str(road_style["material"]), road_materials["asphalt"])
			road_piece.set_meta("tile_id", tile_info["tile_id"])
			_road_root.add_child(road_piece)


func _build_buildings(tile_info: Dictionary, scenery: Dictionary) -> void:
	for building in scenery.get("buildings", []):
		var bounds := _polygon_bounds(building["footprint_m"])
		var mesh_instance := MeshInstance3D.new()
		var box := BoxMesh.new()
		box.size = Vector3(bounds.size.x * world_scale, float(building["height_m"]) * elevation_scale, bounds.size.y * world_scale)
		mesh_instance.mesh = box
		var center_m := [bounds.position.x + (bounds.size.x / 2.0), bounds.position.y + (bounds.size.y / 2.0)]
		var base_elevation := _scenery_height_at_point_m(scenery, center_m)
		mesh_instance.position = Vector3(
			center_m[0] * world_scale,
			base_elevation * elevation_scale + (float(building["height_m"]) * elevation_scale) / 2.0,
			center_m[1] * world_scale
		)
		mesh_instance.material_override = _make_material(Color(0.77, 0.69, 0.58), 0.0)
		mesh_instance.set_meta("tile_id", tile_info["tile_id"])
		_building_root.add_child(mesh_instance)


func _build_props(tile_info: Dictionary, scenery: Dictionary) -> void:
	for mask in scenery.get("prop_masks", []):
		var bounds := _polygon_bounds(mask["polygon_m"])
		var mesh_instance := MeshInstance3D.new()
		var cylinder := CylinderMesh.new()
		cylinder.top_radius = 0.18
		cylinder.bottom_radius = 0.3
		cylinder.height = 1.6 + float(mask.get("density", 0.5))
		mesh_instance.mesh = cylinder
		var center_m := [bounds.position.x + (bounds.size.x / 2.0), bounds.position.y + (bounds.size.y / 2.0)]
		var base_elevation := _scenery_height_at_point_m(scenery, center_m)
		mesh_instance.position = Vector3(
			center_m[0] * world_scale,
			base_elevation * elevation_scale + cylinder.height / 2.0,
			center_m[1] * world_scale
		)
		mesh_instance.material_override = _make_material(Color(0.22, 0.47, 0.26), 0.0)
		mesh_instance.set_meta("tile_id", tile_info["tile_id"])
		_prop_root.add_child(mesh_instance)


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
	_reload_pack_and_route()


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


func _on_import_dialog_file_selected(path: String) -> void:
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


func _build_road_mesh(start_point_m: Array, start_elevation_m: float, end_point_m: Array, end_elevation_m: float, width_m: float) -> ArrayMesh:
	var start_point := _to_world(start_point_m, start_elevation_m + ROAD_SURFACE_CLEARANCE_M)
	var end_point := _to_world(end_point_m, end_elevation_m + ROAD_SURFACE_CLEARANCE_M)
	var forward := end_point - start_point
	if forward.length() < 0.001:
		return ArrayMesh.new()
	var lateral := Vector3(-forward.z, 0.0, forward.x).normalized() * (width_m * world_scale * 0.5)
	var a := start_point - lateral
	var b := start_point + lateral
	var c := end_point - lateral
	var d := end_point + lateral
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	surface.add_vertex(a)
	surface.add_vertex(c)
	surface.add_vertex(b)
	surface.add_vertex(b)
	surface.add_vertex(c)
	surface.add_vertex(d)
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
	if alpha > 0.0:
		material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	return material


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
