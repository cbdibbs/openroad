extends Node3D

const RegionPackLoader = preload("res://addons/procedural_trainer/region_pack_loader.gd")

@export var region_pack_dir := "../../region-data/milwaukee/mke_demo_region_pack"
@export var active_route_id := "oak_leaf_demo_loop"
@export var world_scale := 0.2
@export var elevation_scale := 0.25
@export var rider_speed_mps := 9.0

var _pack: Dictionary = {}
var _route_points: Array[Vector3] = []
var _route_segment_lengths: Array[float] = []
var _route_total_length := 0.0
var _route_progress := 0.0

@onready var _terrain_root: Node3D = $TerrainRoot
@onready var _biome_root: Node3D = $BiomeRoot
@onready var _road_root: Node3D = $RoadRoot
@onready var _rider: MeshInstance3D = $Rider
@onready var _camera: Camera3D = $Camera3D
@onready var _status_label: Label3D = $StatusLabel


func _ready() -> void:
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
	_build_route()

	if _route_points.is_empty():
		_set_status("No route points available for %s" % active_route_id)
		return

	_rider.position = _route_points[0]
	_set_status(
		"%s | %s | edges=%d"
		% [
			_pack["manifest"]["region_id"],
			active_route_id,
			_pack["ride_graph"]["edges"].size()
		]
	)


func _process(delta: float) -> void:
	if _route_total_length <= 0.0:
		return

	_route_progress = fmod(_route_progress + (delta * rider_speed_mps * world_scale), _route_total_length)
	_rider.position = _point_at_distance(_route_progress)
	_camera.position = _rider.position + Vector3(-8.0, 6.0, -8.0)
	_camera.look_at(_rider.position + Vector3(0.0, 1.0, 0.0))


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
	_route_segment_lengths.clear()
	_route_total_length = 0.0

	var route := _find_route(active_route_id)
	if route.is_empty():
		return

	var edge_lookup := {}
	for edge in _pack["ride_graph"]["edges"]:
		edge_lookup[edge["edge_id"]] = edge

	for edge_id in route["snapped_edge_sequence"]:
		var edge: Dictionary = edge_lookup[edge_id]
		var geometry: Array = edge["geometry_m"]
		var elevations: Array = edge["elevation_profile_m"]
		for index in range(geometry.size()):
			if not _route_points.is_empty() and index == 0:
				continue
			_route_points.append(_to_world(geometry[index], elevations[index]))

	for index in range(_route_points.size() - 1):
		var segment_length := _route_points[index].distance_to(_route_points[index + 1])
		_route_segment_lengths.append(segment_length)
		_route_total_length += segment_length


func _find_route(route_id: String) -> Dictionary:
	for route in _pack["routes"]:
		if route["route_id"] == route_id:
			return route
	return {}


func _point_at_distance(distance_along_route: float) -> Vector3:
	if _route_points.size() == 1:
		return _route_points[0]

	var remaining := distance_along_route
	for index in range(_route_segment_lengths.size()):
		var segment_length := _route_segment_lengths[index]
		if remaining <= segment_length:
			var ratio := remaining / segment_length if segment_length > 0.0 else 0.0
			return _route_points[index].lerp(_route_points[index + 1], ratio)
		remaining -= segment_length

	return _route_points[-1]


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
