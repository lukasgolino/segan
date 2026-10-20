# Lists every asset from SEGAN's manifest with buttons to play it: SFX (and their variations through the
# AudioStreamRandomizer, and their phases), songs with a loop toggle, their variants, the stems as an
# AudioStreamSynchronized with one volume slider per layer (adaptive music), flow songs walked by the SeganMusic
# director, and each soundtrack with a button per game state.
extends Control

const MANIFEST := "res://assets/generated/audio/manifest.json"

var player := AudioStreamPlayer.new()
var stems_player := AudioStreamPlayer.new()
var status := Label.new()
var rows := {}  # asset name -> HBoxContainer (for the scene check)


func _ready() -> void:
	add_child(player)
	add_child(stems_player)
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	if typeof(manifest) != TYPE_DICTIONARY:
		push_error("Can't read %s: run `segan build` in examples/demo first." % MANIFEST)
		return
	var scroll := ScrollContainer.new()
	scroll.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(scroll)
	var list := VBoxContainer.new()
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(list)
	var title := Label.new()
	title.text = "SEGAN demo: %d assets (%s)" % [manifest["assets"].size(), manifest["generator"]]
	list.add_child(title)
	status.text = "press a button"
	list.add_child(status)
	var names: Array = manifest["assets"].keys()
	names.sort_custom(func(a, b): return [manifest["assets"][a]["kind"], a] < [manifest["assets"][b]["kind"], b])
	for asset_name in names:
		var entry: Dictionary = manifest["assets"][asset_name]
		var row := HBoxContainer.new()
		rows[asset_name] = row
		list.add_child(row)
		var label := Label.new()
		label.text = "%s [%s]" % [asset_name, entry.get("category", entry["kind"])]
		label.custom_minimum_size = Vector2(220, 0)
		row.add_child(label)
		if entry.has("file"):
			_button(row, "play", entry["file"])
		if entry.has("godot_randomizer"):
			_button(row, "random variation", entry["godot_randomizer"])
		for phase in entry.get("phases", {}):
			_button(row, phase, entry["phases"][phase]["file"])
		for variant in entry.get("variants", {}):
			_button(row, variant, entry["variants"][variant]["file"])
		if entry["kind"] == "song":
			var loop := CheckBox.new()
			loop.text = "loop"
			loop.button_pressed = true
			loop.toggled.connect(_set_loop.bind(entry))
			row.add_child(loop)
		if entry.has("flow"):
			var walk := Button.new()
			walk.text = "walk sections"
			walk.pressed.connect(_walk.bind(asset_name))
			row.add_child(walk)
		if entry.has("godot_stems"):
			_stems(list, entry)
	for soundtrack in manifest.get("soundtracks", {}):
		_soundtrack(list, soundtrack, manifest["soundtracks"][soundtrack])
	var stop := Button.new()
	stop.text = "stop"
	stop.pressed.connect(_stop)
	list.add_child(stop)


func _director() -> Node:
	return get_node_or_null("/root/SeganMusic")


func _stop() -> void:
	player.stop()
	stems_player.stop()
	if _director():
		_director().stop(1.0)


func _walk(song: String) -> void:
	player.stop()
	stems_player.stop()
	_director().play_song(song, "", 0.5, "now")
	status.text = "walking " + song


func _soundtrack(list: VBoxContainer, soundtrack: String, entry: Dictionary) -> void:
	var row := HBoxContainer.new()
	rows["soundtrack:" + soundtrack] = row
	list.add_child(row)
	var label := Label.new()
	label.text = "%s [soundtrack]" % soundtrack
	label.custom_minimum_size = Vector2(220, 0)
	row.add_child(label)
	for state in entry["states"]:
		var button := Button.new()
		button.text = state
		button.pressed.connect(_state.bind(soundtrack, state))
		row.add_child(button)


func _state(soundtrack: String, state: String) -> void:
	player.stop()
	stems_player.stop()
	var music := _director()
	if music.soundtrack_name != soundtrack:
		music.play_soundtrack(soundtrack, state)
	else:
		music.set_state(state)
	status.text = "soundtrack %s: %s" % [soundtrack, state]


func _button(row: HBoxContainer, text: String, path: String) -> void:
	var button := Button.new()
	button.text = text
	button.pressed.connect(_play.bind(path))
	row.add_child(button)


func _play(path: String) -> void:
	stems_player.stop()
	if _director():
		_director().stop(0.2)
	player.stream = load(path)
	player.play()
	status.text = "playing " + path


func _set_loop(on: bool, entry: Dictionary) -> void:
	var paths := [entry["file"]]
	for variant in entry.get("variants", {}):
		paths.append(entry["variants"][variant]["file"])
	for path in paths:
		var wav: AudioStreamWAV = load(path)
		wav.loop_mode = AudioStreamWAV.LOOP_FORWARD if on else AudioStreamWAV.LOOP_DISABLED


func _stems(list: VBoxContainer, entry: Dictionary) -> void:
	var row := HBoxContainer.new()
	list.add_child(row)
	var spacer := Label.new()
	spacer.text = "    stems:"
	spacer.custom_minimum_size = Vector2(220, 0)
	row.add_child(spacer)
	var sync: AudioStreamSynchronized = load(entry["godot_stems"])
	var play := Button.new()
	play.text = "play layers"
	play.pressed.connect(func(): player.stop(); stems_player.stream = sync; stems_player.play(); status.text = "playing stems " + entry["godot_stems"])
	row.add_child(play)
	var index := 0
	for track in entry["stems"]:
		var label := Label.new()
		label.text = track
		row.add_child(label)
		var slider := HSlider.new()
		slider.min_value = -40.0
		slider.max_value = 0.0
		slider.value = 0.0
		slider.custom_minimum_size = Vector2(90, 0)
		slider.value_changed.connect(func(db): sync.set_sync_stream_volume(index, db if db > -40.0 else -80.0))
		row.add_child(slider)
		index += 1
