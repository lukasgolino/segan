# SEGAN SFX player: plays SEGAN sound effects by name from manifest.json, on their category's bus at its default
# volume ([bus] in segan.toml), honouring each SFX's playback hints (max_instances, min_gap_s, repeat_attenuation_db).
# Written by `segan build` next to manifest.json when the project has a [bus] table or playback hints; don't edit
# it (every build overwrites it).
#
# Add it as an autoload (Project > Project Settings > Globals > Autoload, name it SeganSfx), then:
#   SeganSfx.play("coin")                          # a random variation each time (the SFX's AudioStreamRandomizer)
#   SeganSfx.play_2d("hit", global_position)       # an AudioStreamPlayer2D at a position
#   SeganSfx.play_3d("hit", global_position)       # an AudioStreamPlayer3D
#   var hum = SeganSfx.play("engine", -6.0)        # extra dB on top of the category's; a looping SFX plays until stopped
#   SeganSfx.stop("engine")
# play* return the player, or null when a hint dropped the play (min_gap_s) or the name is unknown.
#
# Hints: a play within min_gap_s of the SFX's last start is dropped; at max_instances copies sounding, the oldest
# stops; each copy still sounding makes a new one repeat_attenuation_db quieter.
# Buses: ones the manifest names but the game's layout lacks are added (0 dB, sending to Master) unless
# add_missing_buses is off. SEGAN's own layout, segan_buses.tres, is never applied by itself; to use it:
#   AudioServer.set_bus_layout(load(SeganSfx.manifest["godot_bus_layout"]))
extends Node

## manifest.json written by `segan build` (empty: the one next to this script).
@export_file("*.json") var manifest_path := ""
## Add buses the manifest names that the current bus layout doesn't have.
@export var add_missing_buses := true

var manifest := {}
var _streams := {}
var _playing := {}  # SFX name -> players still sounding, oldest first
var _last_start := {}  # SFX name -> seconds of its last start


func _ready() -> void:
	_ensure()


## Load the manifest on first use (methods may be called before _ready).
func _ensure() -> void:
	if manifest.is_empty():
		load_manifest(manifest_path if manifest_path != "" else get_script().resource_path.get_base_dir().path_join("manifest.json"))


func load_manifest(path: String) -> void:
	var data = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(data) != TYPE_DICTIONARY:
		push_error("SeganSfx: can't read " + path)
		return
	manifest = data
	if add_missing_buses:
		add_buses()


## Add every bus the manifest names that the current layout lacks (0 dB, sending to Master).
func add_buses() -> void:
	var buses: Dictionary = manifest.get("buses", {})
	for category in buses:
		var bus_name: String = buses[category]["bus"]
		if AudioServer.get_bus_index(bus_name) == -1:
			AudioServer.add_bus()
			var index := AudioServer.bus_count - 1
			AudioServer.set_bus_name(index, bus_name)
			AudioServer.set_bus_send(index, &"Master")


## The SFX's manifest entry ({} if there is none).
func entry(sfx: String) -> Dictionary:
	_ensure()
	var found = manifest.get("assets", {}).get(sfx)
	return found if typeof(found) == TYPE_DICTIONARY and found.get("kind") == "sfx" else {}


## The stream to play: the randomizer over the variations if there is one, else the main file.
func stream_for(sfx: String) -> AudioStream:
	var info := entry(sfx)
	var path: String = info.get("godot_randomizer", info.get("file", ""))
	if path == "":
		return null
	if not _streams.has(path):
		_streams[path] = load(path)
	return _streams[path]


## The bus the SFX's category plays on (Master if [bus] doesn't list it).
func bus_for(sfx: String) -> StringName:
	var bus_name: String = entry(sfx).get("bus", "Master")
	return StringName(bus_name) if AudioServer.get_bus_index(bus_name) != -1 else &"Master"


## The category's default volume, less repeat_attenuation_db per copy of the SFX still sounding.
func volume_db_for(sfx: String) -> float:
	var info := entry(sfx)
	var category: Dictionary = manifest.get("buses", {}).get(info.get("category", ""), {})
	var hints: Dictionary = info.get("playback", {})
	return float(category.get("volume_db", 0.0)) - float(hints.get("repeat_attenuation_db", 0.0)) * playing(sfx).size()


## Players of the SFX still sounding, oldest first.
func playing(sfx: String) -> Array:
	var alive: Array = _playing.get(sfx, []).filter(func(p): return is_instance_valid(p) and not p.is_queued_for_deletion() and (p.playing or p.autoplay))
	_playing[sfx] = alive
	return alive


func play(sfx: String, volume_db := 0.0, pitch_scale := 1.0) -> AudioStreamPlayer:
	return _start(sfx, AudioStreamPlayer.new(), volume_db, pitch_scale)


func play_2d(sfx: String, position: Vector2, volume_db := 0.0, pitch_scale := 1.0) -> AudioStreamPlayer2D:
	var player := AudioStreamPlayer2D.new()
	player.position = position  # a child of this Node: its position is global
	return _start(sfx, player, volume_db, pitch_scale)


func play_3d(sfx: String, position: Vector3, volume_db := 0.0, pitch_scale := 1.0) -> AudioStreamPlayer3D:
	var player := AudioStreamPlayer3D.new()
	player.position = position
	return _start(sfx, player, volume_db, pitch_scale)


## Stop every copy of the SFX.
func stop(sfx: String) -> void:
	for player in _playing.get(sfx, []):
		if is_instance_valid(player):
			player.queue_free()
	_playing.erase(sfx)


func _start(sfx: String, player: Node, volume_db: float, pitch_scale: float) -> Node:
	var stream := stream_for(sfx)
	if stream == null:
		push_error("SeganSfx: no SFX named " + sfx + " in the manifest")
		player.free()
		return null
	var hints: Dictionary = entry(sfx).get("playback", {})
	var now := Time.get_ticks_usec() / 1000000.0
	if hints.has("min_gap_s") and _last_start.has(sfx) and now - _last_start[sfx] < float(hints["min_gap_s"]):
		player.free()
		return null
	var alive := playing(sfx)
	if hints.has("max_instances"):
		while alive.size() >= int(hints["max_instances"]):
			alive.pop_front().queue_free()
	player.stream = stream
	player.bus = bus_for(sfx)
	player.volume_db = volume_db_for(sfx) + volume_db  # (after the cap: copies just stopped don't count)
	player.pitch_scale = pitch_scale
	player.finished.connect(player.queue_free)
	add_child(player)
	if player.is_inside_tree():
		player.play()
	else:
		player.autoplay = true  # this node isn't in the scene tree yet: start when it is
	playing(sfx).append(player)  # playing() replaces the list: append to the current one
	_last_start[sfx] = now
	return player
