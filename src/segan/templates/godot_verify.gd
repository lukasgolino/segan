# Run by `segan build --verify-godot` (from a temp folder): loads every stream SEGAN generated, checks its loop
# points and format against manifest.json, and mixes a few frames of each (the "plays for one frame" check).
# Any script error ends the run with exit 1: the checks run in `_check`, which sets `finished` only when it gets
# to the end (a GDScript runtime error returns from the function with a default value instead of raising).
extends SceneTree

var finished := false
var failures := 0
var checked := 0

func _init() -> void:
	var code := _check()
	if not finished:
		printerr("SEGAN_VERIFY_FAIL the check script hit an error (see SCRIPT ERROR above)")
		code = 1
	quit(code)

func _fail(message: String) -> void:
	printerr("SEGAN_VERIFY_FAIL ", message)
	failures += 1

func _plays(stream: AudioStream, path: String) -> void:
	var playback := stream.instantiate_playback()
	if playback == null:
		_fail(path + " can't be played")
		return
	playback.start(0.0)
	var frames: PackedVector2Array = playback.mix_audio(1.0, 256)
	if frames.size() != 256:
		_fail(path + " mixed " + str(frames.size()) + " frames, expected 256")
	playback.stop()

func _check_ogg(entry: Dictionary, rate: int) -> void:
	var path: String = entry["file"]
	var stream = load(path)
	if stream == null or not (stream is AudioStreamOggVorbis):
		_fail("not an AudioStreamOggVorbis: " + path)
		return
	var ogg: AudioStreamOggVorbis = stream
	if ogg.packet_sequence == null or int(ogg.packet_sequence.sampling_rate) != rate:
		_fail(path + " sampling rate isn't " + str(rate))
	var loop = entry.get("loop")
	if typeof(loop) == TYPE_DICTIONARY:
		# Godot restarts a loop at floor(loop_offset * rate), after the last frame of the file
		if not ogg.loop or int(ogg.loop_offset * rate) != int(loop["start"]):
			_fail(path + " loop " + str(ogg.loop) + " from " + str(ogg.loop_offset * rate) + ", expected from frame " + str(int(loop["start"])))
	elif ogg.loop:
		_fail(path + " loops but the manifest says it doesn't")
	_plays(ogg, path)
	checked += 1

func _check_wav(entry: Dictionary, rate: int) -> void:
	var path: String = entry["file"]
	if path.ends_with(".ogg"):
		_check_ogg(entry, rate)
		return
	var stream = load(path)
	if stream == null or not (stream is AudioStreamWAV):
		_fail("not an AudioStreamWAV: " + path)
		return
	var wav: AudioStreamWAV = stream
	if wav.mix_rate != rate:
		_fail(path + " mix_rate " + str(wav.mix_rate) + ", expected " + str(rate))
	if wav.stereo != (int(entry.get("channels", 1)) == 2):
		_fail(path + " stereo is " + str(wav.stereo))
	var loop = entry.get("loop")
	if typeof(loop) == TYPE_DICTIONARY:
		# Godot plays loop_begin+1 .. loop_end, so [start, end) is begin = start - 1, end = end - 1
		if wav.loop_mode != AudioStreamWAV.LOOP_FORWARD or wav.loop_begin != int(loop["start"]) - 1 or wav.loop_end != int(loop["end"]) - 1:
			_fail(path + " loop " + str(wav.loop_mode) + " " + str(wav.loop_begin) + ".." + str(wav.loop_end) + ", expected forward " + str(int(loop["start"]) - 1) + ".." + str(int(loop["end"]) - 1))
	elif wav.loop_mode != AudioStreamWAV.LOOP_DISABLED:
		_fail(path + " loops but the manifest says it doesn't")
	_plays(wav, path)
	checked += 1

func _check_clip(path: String, rate: int) -> void:
	_check_wav({"file": path, "channels": 2 if (load(path) is AudioStreamWAV and load(path).stereo) else 1, "loop": null}, rate)

func _check_flow(flow: Dictionary, rate: int) -> void:
	var sets: Array = [flow]
	for v in flow.get("variants", {}):
		sets.append(flow["variants"][v])
	for clips in sets:
		for name in clips["sections"]:
			var section: Dictionary = clips["sections"][name]
			for part in ["head", "rest", "tail"]:
				if section[part] != null:
					_check_clip(section[part], rate)
			for prev in section["from"]:
				_check_clip(section["from"][prev], rate)

func _check_director(manifest_path: String, manifest: Dictionary) -> void:
	var path := manifest_path.get_base_dir().path_join("segan_music.gd")
	var script = load(path)
	if script == null or not script.can_instantiate():
		_fail("the director " + path + " doesn't load")
		return
	var music = script.new()
	music.offline = true
	music.manifest = manifest
	music.rng.seed = 1
	for name in manifest["assets"]:
		var entry: Dictionary = manifest["assets"][name]
		if entry.get("kind") == "song" and (entry.has("file") or entry.has("flow")):
			music.play_song(name)
			var frames: PackedVector2Array = music.render(4096)
			if frames.size() != 4096:
				_fail("the director rendered " + str(frames.size()) + " frames of " + name + ", expected 4096")
			checked += 1
	music.free()

func _walk(value, rate: int) -> void:
	if typeof(value) == TYPE_DICTIONARY:
		if value.has("file") and typeof(value["file"]) == TYPE_STRING:
			_check_wav(value, rate)
		for key in value:
			_walk(value[key], rate)
	elif typeof(value) == TYPE_ARRAY:
		for item in value:
			_walk(item, rate)

func _check() -> int:
	var args := OS.get_cmdline_user_args()
	var manifest_path: String = args[0] if args.size() > 0 else "res://assets/generated/audio/manifest.json"
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
	if typeof(manifest) != TYPE_DICTIONARY or typeof(manifest.get("assets")) != TYPE_DICTIONARY:
		printerr("SEGAN_VERIFY_FAIL cannot read manifest ", manifest_path)
		finished = true
		return 1
	for name in manifest["assets"]:
		var entry: Dictionary = manifest["assets"][name]
		var rate: int = int(entry.get("sample_rate", 44100))
		_walk(entry, rate)
		if entry.has("flow"):
			_check_flow(entry["flow"], rate)
		if entry.has("godot_randomizer"):
			var randomizer = load(entry["godot_randomizer"])
			if randomizer == null or not (randomizer is AudioStreamRandomizer):
				_fail("not an AudioStreamRandomizer: " + str(entry["godot_randomizer"]))
			elif randomizer.streams_count != entry.get("variations", []).size():
				_fail(str(entry["godot_randomizer"]) + " has " + str(randomizer.streams_count) + " streams, expected " + str(entry.get("variations", []).size()))
			else:
				_plays(randomizer, entry["godot_randomizer"])
				checked += 1
		if entry.has("godot_stems"):
			var stems = load(entry["godot_stems"])
			if stems == null or not (stems is AudioStreamSynchronized):
				_fail("not an AudioStreamSynchronized: " + str(entry["godot_stems"]))
			elif stems.stream_count != entry.get("stems", {}).size():
				_fail(str(entry["godot_stems"]) + " has " + str(stems.stream_count) + " streams, expected " + str(entry.get("stems", {}).size()))
			else:
				_plays(stems, entry["godot_stems"])
				checked += 1
	if FileAccess.file_exists(manifest_path.get_base_dir().path_join("segan_music.gd")):
		_check_director(manifest_path, manifest)
	finished = true
	if failures > 0:
		printerr("SEGAN_VERIFY_FAIL ", failures, " problems")
		return 1
	print("SEGAN_VERIFY_OK ", checked, " streams checked")
	return 0
