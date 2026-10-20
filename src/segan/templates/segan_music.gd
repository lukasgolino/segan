# SEGAN music director: plays SEGAN songs, flows (section graphs) and soundtracks from manifest.json.
# Written by `segan build` next to manifest.json; don't edit it (every build overwrites it).
#
# Add it as an autoload (Project > Project Settings > Globals > Autoload, name it SeganMusic), then:
#   SeganMusic.play_soundtrack("main")            # starts in the soundtrack's start state
#   SeganMusic.set_state("combat")                # the soundtrack's transitions say when and how
#   SeganMusic.play_song("overworld", "danger")   # one song; a flow song walks its sections forever
#   SeganMusic.queue_section("chorus")            # a flow song's next section (instead of a random pick)
#   SeganMusic.stop(2.0)                          # fade out over 2 s
#
# Sections are chained sample-exactly: an AudioStreamGenerator is fed from the clips with mix_audio, and every
# seam sounds like the linear render (the clip after a seam has the previous section's ring-out baked in).
# A song change starts the new song on the old one's beat/bar/section grid (within one audio mix chunk) while
# the old one fades or rings out.
extends Node

signal song_started(song: String, variant: String)
signal section_started(song: String, section: String)
signal song_finished(song: String)
signal state_changed(state: String)

const SILENT_DB := -80.0

## manifest.json written by `segan build` (empty: the one next to this script).
@export_file("*.json") var manifest_path := ""
@export var bus: StringName = &"Master"
## Audio queued ahead of the speakers. Song changes take effect after it (and then on the next beat/bar...).
@export var buffer_seconds := 0.3
## 0 = a different walk every run.
@export var random_seed := 0

var manifest := {}
var rng := RandomNumberGenerator.new()
var soundtrack_name := ""
var state := ""
var offline := false  # tests: no players; render() pulls the newest deck's audio
var decks: Array = []  # Deck; the current song is the last one, older ones are ringing or fading out
var _gap_timer: SceneTreeTimer = null
var _last_in_state := {}  # state -> the song it played last (no immediate repeats)
var _streams := {}
var _preroll := -1  # output frames a new playback is late by (Godot's resampler history), measured once


class Segment:
	var path: String
	var frames: int  # output frames; -1 = until the deck stops (a looping song)
	var start_src := 0  # source frames into the file
	var section := ""  # flow: the section this clip belongs to
	var ends_section := false
	var starts_section := false
	var stinger := false


class Deck:
	var music: Node
	var song := ""
	var variant := ""
	var entry := {}  # the song's manifest entry (a variant's timing merged over it)
	var flow = null  # the flow's clips for this variant, or null
	var rate := 44100
	var ratio := 1.0  # output frames per source frame
	var player: AudioStreamPlayer = null
	var gen: AudioStreamGeneratorPlayback = null
	var capacity := 0
	var segments: Array = []  # Segment, not started yet
	var current: Segment = null
	var current_pb: AudioStreamPlayback = null
	var current_left := 0
	var current_start := 0  # output frame where the current segment started
	var pushed := 0  # output frames pushed (lead-in silence included)
	var src_total := 0  # source frames of every clip queued so far (exact boundaries at any output rate)
	var silence := 0  # output frames of silence still to push first
	var lead := 0  # output frames of silence it started with (the song is heard from there)
	var queued_from := 0  # output frame where the next queued segment starts
	var events: Array = []  # [output frame, section] for section_started
	var section := ""  # last section queued
	var section_start := 0  # output frame where that section starts
	var forced: Array = []  # sections queued by the game
	var ending := false  # no more sections: finish what's queued
	var stop_at := -1  # output frame where feeding stops (with a short fade)
	var finished := false
	var play_until := -1  # output frame after which the song ends (soundtrack play time), -1 = never
	var announced := false  # song_started emitted (when its first frame is heard)
	var fade_out := 0.0
	var next_choice: Dictionary = {}  # the soundtrack's next song when it cross-fades into this one (same family)
	var crossfade := 0.0

	func audible() -> int:
		if gen == null:
			return pushed
		return pushed - (capacity - gen.get_frames_available())

	func out_frames(src_frames: int) -> int:
		var a := int(round(src_total * ratio))
		src_total += src_frames
		return int(round(src_total * ratio)) - a

	func add(path: String, src_frames: int, section_name := "", starts := false, ends := false) -> void:
		var s := Segment.new()
		s.path = path
		s.frames = out_frames(src_frames) if src_frames >= 0 else -1
		s.section = section_name
		s.starts_section = starts
		s.ends_section = ends
		if starts:
			events.append([queued_from, section_name])
			section_start = queued_from
		if s.frames >= 0:
			queued_from += s.frames
		segments.append(s)

	func queue_section(name: String, prev: String) -> void:
		var clips: Dictionary = flow["sections"][name]
		var head = clips["from"].get(prev, clips["head"]) if prev != "" else clips["head"]
		var head_frames := int(clips["head_samples"])
		var rest_frames := int(clips["samples"]) - head_frames
		add(head, head_frames, name, true, clips["rest"] == null)
		if clips["rest"] != null:
			add(clips["rest"], rest_frames, name, false, true)
		section = name

	func queue_tail(name: String) -> void:
		var tail = flow["sections"][name]["tail"]
		if tail != null:
			var s := Segment.new()
			s.path = tail
			s.frames = -2  # to its end
			segments.append(s)

	func pick_next() -> String:
		if not forced.is_empty():
			return forced.pop_front()
		var options: Array = []
		var succ: Dictionary = music.flow_next(entry["flow"], section)
		for name in succ:
			if not (entry["flow"]["no_repeat"] and name == section and succ.size() > 1):
				options.append([name, float(succ[name])])
		if options.is_empty():
			return ""
		var total := 0.0
		for o in options:
			total += o[1]
		var pick: float = music.rng.randf() * total
		for o in options:
			pick -= o[1]
			if pick < 0.0:
				return o[0]
		return options[-1][0]

	func plan() -> void:
		if flow == null or ending or not segments.is_empty():
			return
		var past_play := play_until >= 0 and queued_from >= play_until
		if past_play and next_choice.is_empty():  # (a cross-fade keeps walking until the next song takes over)
			end_song()
			return
		var name := pick_next()
		if name == "":
			end_song()
			return
		queue_section(name, section)

	## Finish after the section queued last: the flow's ending section if it has one, then the ring-out.
	func end_song() -> void:
		if ending:
			return
		ending = true
		if flow == null:
			return
		var end_name = entry["flow"].get("end")
		if end_name != null and section != end_name:
			queue_section(end_name, section)
		queue_tail(section)

	## The first sync point (output frame) at or after what's already pushed.
	func next_point(kind: String) -> int:
		var after := pushed
		if kind == "now":
			return after
		var beat := float(entry["beat_seconds"]) * rate * ratio
		var bar := beat * float(entry["meter"][0])
		if flow != null:
			if kind == "beat" or kind == "bar":
				var step := beat if kind == "beat" else bar
				var k := ceili((after - section_start) / step)
				return section_start + int(round(k * step))
			return -1  # section / end: handled by drop_after_section
		var pos := after - current_start if current != null else 0
		var src := pos / ratio
		var loop = entry.get("loop")
		var length := float(entry["samples"])
		var target := -1.0
		if kind == "beat" or kind == "bar":
			var step_src := float(entry["beat_seconds"]) * rate * (1.0 if kind == "beat" else float(entry["meter"][0]))
			target = ceilf(src / step_src) * step_src
		elif kind == "section" or kind == "end":
			var points: Array = []
			if kind == "section":
				for part in entry["arrangement"]:
					points.append(float(part["start"]))
			var song_end := float(entry["arrangement"][-1]["end"])
			points.append(song_end)
			if typeof(loop) == TYPE_DICTIONARY:
				var ls := float(loop["start"])
				var le := float(loop["end"])
				var offset := float(loop["offset"])
				for p in points.duplicate():
					if p >= ls - offset and p + offset <= le:
						points.append(p + offset)
				points.append(le)
				if src >= le:  # unwrap: the loop region repeats every le - ls frames
					var period := le - ls
					var n := floorf((src - ls) / period)
					var local := src - n * period
					for p in points:
						if p >= ls and p >= local:
							target = p + n * period if target < 0.0 else minf(target, p + n * period)
					if target < 0.0:
						target = ls + (n + 1) * period
					return current_start + int(round(target * ratio))
			else:
				points.append(length)
			for p in points:
				if p >= src:
					target = p if target < 0.0 else minf(target, p)
			if target < 0.0:
				target = length
		return current_start + int(round(target * ratio))

	## Flow: keep only up to the end of the section being pushed; returns that output frame.
	func drop_after_section() -> int:
		var at := current_start + (current.frames if current != null and current.frames >= 0 else 0)
		if current != null:
			section = current.section
		if current != null and current.ends_section:
			segments.clear()
		else:
			var keep: Array = []
			for s in segments:
				keep.append(s)
				at += s.frames
				section = s.section
				if s.ends_section:
					break
			segments = keep
		# forget sections queued after the boundary
		var kept: Array = []
		for e in events:
			if e[0] < at:
				kept.append(e)
		events = kept
		queued_from = at
		ending = true
		return at

	## The next n output frames (silence once finished).
	func produce(n: int) -> PackedVector2Array:
		var out := PackedVector2Array()
		while out.size() < n:
			var want := n - out.size()
			if stop_at >= 0 and pushed + out.size() >= stop_at:
				finished = true
			if finished:
				var rest := PackedVector2Array()
				rest.resize(want)
				out.append_array(rest)
				break
			if silence > 0:
				var gap := PackedVector2Array()
				gap.resize(mini(silence, want))
				silence -= gap.size()
				out.append_array(gap)
				continue
			if current == null:
				plan()
				if segments.is_empty():
					finished = true
					continue
				current = segments.pop_front()
				current_start = pushed + out.size()
				var stream: AudioStream = music.stream(current.path)
				if stream == null:
					push_error("SeganMusic: can't load " + current.path + " (rebuild, then let Godot import it)")
					current = null
					continue
				current_pb = stream.instantiate_playback()
				current_pb.start(float(current.start_src) / rate)
				var late: int = music.preroll(rate)
				if late > 0:
					current_pb.mix_audio(1.0, late)  # so the clip's first frame comes first: seams stay exact
				current_left = current.frames
				if current.frames == -2:
					current_left = int(round(stream.get_length() * rate * ratio))
			var take := want if current_left < 0 else mini(want, current_left)
			if stop_at >= 0:
				take = mini(take, stop_at - (pushed + out.size()))
			var chunk: PackedVector2Array = current_pb.mix_audio(1.0, take)
			var ended := chunk.size() < take or not current_pb.is_playing()
			if chunk.size() < take:
				chunk.resize(take)  # the file ran out (a tail): silence
			if stop_at >= 0:
				chunk = _declick(chunk, pushed + out.size())
			out.append_array(chunk)
			if current_left >= 0:
				current_left -= take
			if current_left == 0 or (ended and current_left != 0):
				current = null
		pushed += out.size()
		return out

	## A 5 ms fade into stop_at (a hard cut would click).
	func _declick(chunk: PackedVector2Array, at: int) -> PackedVector2Array:
		var ramp := int(0.005 * rate * ratio)
		for i in chunk.size():
			var left := stop_at - (at + i)
			if left < ramp:
				chunk[i] *= maxf(0.0, float(left) / ramp)
		return chunk

	func pump() -> void:
		if player != null and gen == null and player.is_inside_tree():
			player.play()  # here, not when created: the director may be used before it's in the tree
			gen = player.get_stream_playback()
			capacity = gen.get_frames_available()
		if gen == null or finished:
			return
		var free := gen.get_frames_available()
		if free > 0:
			gen.push_buffer(produce(free))


func _ready() -> void:
	_ensure()


## Load the manifest and seed the walk on first use (methods may be called before _ready).
func _ensure() -> void:
	if manifest.is_empty():
		rng.seed = random_seed if random_seed != 0 else int(Time.get_ticks_usec())
		load_manifest(manifest_path if manifest_path != "" else get_script().resource_path.get_base_dir().path_join("manifest.json"))


func load_manifest(path: String) -> void:
	var data = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(data) != TYPE_DICTIONARY:
		push_error("SeganMusic: can't read " + path)
		return
	manifest = data


func stream(path: String) -> AudioStream:
	if not _streams.has(path):
		_streams[path] = load(path)
	return _streams[path]


## How many output frames a freshly started playback of a `rate` Hz WAV is late by (an impulse's delay).
func preroll(rate: int) -> int:
	if _preroll < 0:
		var wav := AudioStreamWAV.new()
		wav.format = AudioStreamWAV.FORMAT_16_BITS
		wav.mix_rate = int(AudioServer.get_mix_rate())
		var data := PackedByteArray()
		data.resize(64)
		data.encode_s16(0, 32767)
		wav.data = data
		var pb := wav.instantiate_playback()
		pb.start(0.0)
		var frames: PackedVector2Array = pb.mix_audio(1.0, 16)
		_preroll = 0
		for i in frames.size():
			if absf(frames[i].x) > absf(frames[_preroll].x):
				_preroll = i
	return int(round(_preroll * AudioServer.get_mix_rate() / rate)) if rate != int(AudioServer.get_mix_rate()) else _preroll


func flow_next(flow: Dictionary, section: String) -> Dictionary:
	return flow["next"].get(section, {})


# --- songs ---------------------------------------------------------------------------------------


func _song_entry(song: String, variant: String) -> Dictionary:
	_ensure()
	var entry: Dictionary = manifest["assets"].get(song, {})
	if entry.is_empty() or entry.get("kind") != "song":
		push_error("SeganMusic: no song " + song)
		return {}
	if variant != "":
		var v: Dictionary = entry.get("variants", {}).get(variant, {})
		if v.is_empty():
			push_error("SeganMusic: song " + song + " has no variant " + variant)
			return {}
		var merged := entry.duplicate()
		merged.merge(v, true)
		merged.erase("flow")
		if entry.has("flow") and entry["flow"].get("variants", {}).has(variant):
			var flow: Dictionary = entry["flow"].duplicate()
			flow.merge(entry["flow"]["variants"][variant], true)
			merged["flow"] = flow
		return merged
	return entry


func _new_deck(song: String, variant: String) -> Deck:
	var entry := _song_entry(song, variant)
	if entry.is_empty():
		return null
	var deck := Deck.new()
	deck.music = self
	deck.song = song
	deck.variant = variant
	deck.entry = entry
	deck.flow = entry.get("flow")
	deck.rate = int(entry.get("sample_rate", 44100))
	deck.ratio = float(AudioServer.get_mix_rate()) / deck.rate
	if not offline:
		deck.player = AudioStreamPlayer.new()
		deck.player.bus = bus
		var generator := AudioStreamGenerator.new()
		generator.mix_rate = AudioServer.get_mix_rate()
		generator.buffer_length = buffer_seconds
		deck.player.stream = generator
		add_child(deck.player)
	return deck


func _start(deck: Deck, first_section := "") -> void:
	if deck.flow != null:
		var start: Array = deck.entry["flow"]["start"]
		var first: String = first_section if first_section != "" else start[rng.randi() % start.size()]
		deck.queue_section(first, "")
	else:
		var seg := Segment.new()
		seg.path = deck.entry["file"]
		var start_src := 0
		if first_section != "":
			for part in deck.entry["arrangement"]:
				if part["section"] == first_section:
					start_src = int(part["start"])
					break
		seg.start_src = start_src
		seg.frames = -1 if typeof(deck.entry.get("loop")) == TYPE_DICTIONARY else deck.out_frames(int(deck.entry["samples"]) - start_src)
		deck.segments.append(seg)


## Play a song now (stops whatever plays, with a fade). A flow song walks its sections until stop() or a change.
func play_song(song: String, variant := "", fade := 0.5, at := "bar", first_section := "") -> void:
	_cancel_gap()
	_switch(song, variant, at, fade, 0.0, "", first_section, -1.0, 0.0)


## The next section of the playing flow song (call it any time before the current section ends).
func queue_section(section: String) -> void:
	var deck: Deck = current_deck()
	if deck != null and deck.flow != null and deck.flow["sections"].has(section):
		deck.forced.append(section)


## Stop the music: fade out over `fade` seconds from the next `at` point (now, beat, bar, section, end).
func stop(fade := 1.0, at := "now") -> void:
	_cancel_gap()
	soundtrack_name = ""
	state = ""
	var deck: Deck = current_deck()
	if deck != null:
		_end_deck(deck, at, fade)


func current_deck() -> Deck:
	for i in range(decks.size() - 1, -1, -1):
		if not decks[i].ending:
			return decks[i]
	return null


func current_song() -> String:
	var deck: Deck = current_deck()
	return deck.song if deck != null else ""


func current_section() -> String:
	var deck: Deck = current_deck()
	return deck.section if deck != null else ""


# --- soundtracks ---------------------------------------------------------------------------------


func play_soundtrack(name: String, start_state := "") -> void:
	_ensure()
	var st: Dictionary = manifest.get("soundtracks", {}).get(name, {})
	if st.is_empty():
		push_error("SeganMusic: no soundtrack " + name)
		return
	soundtrack_name = name
	state = ""
	set_state(start_state if start_state != "" else st["start"])


func set_state(new_state: String) -> void:
	var st: Dictionary = manifest.get("soundtracks", {}).get(soundtrack_name, {})
	if st.is_empty() or not st["states"].has(new_state):
		push_error("SeganMusic: no state " + new_state + " in soundtrack " + soundtrack_name)
		return
	if new_state == state:
		return
	var rule := _transition(st, state, new_state) if state != "" else {"at": "now", "fade": 0.0, "fade_in": 0.0, "stinger": null, "start": null}
	state = new_state
	state_changed.emit(new_state)
	_cancel_gap()
	_next_in_state(rule)


func _transition(st: Dictionary, src: String, dst: String) -> Dictionary:
	for key in [src + ">" + dst, src + ">*", "*>" + dst, "*"]:
		if st["transitions"].has(key):
			return st["transitions"][key]
	return st["default_transition"]


func _pick_song(st_state: Dictionary) -> Dictionary:
	var options: Array = st_state["songs"]
	var last: String = _last_in_state.get(state, "")
	var pool: Array = []
	for o in options:
		var label: String = o["song"] + ("." + o["variant"] if o["variant"] != null else "")
		if options.size() == 1 or label != last:
			pool.append(o)
	var total := 0.0
	for o in pool:
		total += float(o["weight"])
	var pick := rng.randf() * total
	for o in pool:
		pick -= float(o["weight"])
		if pick < 0.0:
			return o
	return pool[-1]


func _next_in_state(rule: Dictionary, preset := {}) -> void:
	var st: Dictionary = manifest["soundtracks"][soundtrack_name]
	var st_state: Dictionary = st["states"][state]
	var choice: Dictionary = preset if not preset.is_empty() else _pick_song(st_state)
	var variant: String = choice["variant"] if choice["variant"] != null else ""
	_last_in_state[state] = choice["song"] + ("." + variant if variant != "" else "")
	var play_seconds := -1.0
	if st_state["play"] != null:
		play_seconds = rng.randf_range(float(st_state["play"][0]), float(st_state["play"][1]))
	var start = rule.get("start")
	_switch(choice["song"], variant, rule["at"], float(rule["fade"]), float(rule["fade_in"]), str(rule["stinger"]) if rule.get("stinger") != null else "",
		str(start) if start != null else "", play_seconds, float(st_state["fade_out"]))
	var crossfade := float(st_state.get("crossfade", 0.0))
	var deck := _newest()
	if crossfade > 0.0 and play_seconds > 0.0 and deck != null and deck.song == choice["song"]:
		var after: Dictionary = _pick_song(st_state)  # picked now: a flow song keeps walking past its play time for it
		if after.get("family") == choice.get("family"):
			deck.next_choice = after
			deck.crossfade = crossfade


func _song_ended(deck: Deck) -> void:
	song_finished.emit(deck.song)
	if soundtrack_name == "" or state == "" or deck != _newest():
		return
	var st_state: Dictionary = manifest["soundtracks"][soundtrack_name]["states"][state]
	var gap := rng.randf_range(float(st_state["gap"][0]), float(st_state["gap"][1]))
	var rule := {"at": "now", "fade": 0.0, "fade_in": 0.0, "stinger": null, "start": null}
	if gap <= 0.0:
		_next_in_state(rule)
		return
	var waiting_state := state
	_gap_timer = get_tree().create_timer(gap)
	_gap_timer.timeout.connect(func():
		if state == waiting_state and _gap_timer != null:
			_gap_timer = null
			_next_in_state(rule))


func _cancel_gap() -> void:
	_gap_timer = null


func _newest() -> Deck:
	return decks[-1] if not decks.is_empty() else null


# --- switching -----------------------------------------------------------------------------------


func _switch(song: String, variant: String, at: String, fade: float, fade_in: float, stinger: String, first_section: String, play_seconds: float,
		fade_out: float) -> void:
	var deck := _new_deck(song, variant)
	if deck == null:
		return
	var old: Deck = current_deck()
	var start := 0
	if old != null:
		start = _end_deck(old, at, fade)
	elif fade > 0.0:
		for d in decks:  # songs still playing their ending: the new one starts now, they fade
			if d.player != null:
				create_tween().tween_property(d.player, "volume_db", SILENT_DB, fade)
	if old != null and start > old.audible():
		deck.silence = start - old.audible() if not offline else 0
	if deck.player != null and fade_in > 0.0:
		deck.player.volume_db = SILENT_DB
		var tween := create_tween()
		tween.tween_interval(float(deck.silence) / AudioServer.get_mix_rate())
		tween.tween_property(deck.player, "volume_db", 0.0, fade_in)
	if play_seconds > 0.0:
		deck.play_until = deck.silence + int(play_seconds * AudioServer.get_mix_rate())
	deck.fade_out = fade_out
	deck.lead = deck.silence
	deck.queued_from = deck.silence
	deck.section_start = deck.silence
	_start(deck, first_section)
	decks.append(deck)
	if stinger != "":
		_play_stinger(stinger, deck.silence)


## Make `deck` stop at the next `at` point; returns that point (output frames, the deck's own clock).
func _end_deck(deck: Deck, at: String, fade: float) -> int:
	var point := -1
	if deck.flow != null and (at == "section" or at == "end"):
		point = deck.drop_after_section()
		if at == "end":
			deck.ending = false
			deck.end_song()
			point = deck.queued_from
		elif fade <= 0.0:
			deck.queue_tail(deck.section)
	else:
		point = deck.next_point(at)
		deck.ending = true
		if fade <= 0.0:
			deck.stop_at = point
	if fade > 0.0 and deck.player != null:
		var tween := create_tween()
		tween.tween_interval(maxf(0.0, float(point - deck.audible()) / AudioServer.get_mix_rate()))
		tween.tween_property(deck.player, "volume_db", SILENT_DB, fade)
		tween.tween_callback(func(): deck.finished = true)
	return point


func _play_stinger(sfx: String, delay_frames: int) -> void:
	var entry: Dictionary = manifest["assets"].get(sfx, {})
	var file = entry.get("file")
	if file == null and entry.has("variations"):
		file = entry["variations"][rng.randi() % entry["variations"].size()]["file"]
	if file == null or offline:
		return
	var player := AudioStreamPlayer.new()
	player.bus = bus
	player.stream = stream(file)
	add_child(player)
	player.finished.connect(player.queue_free)
	if delay_frames > 0:
		get_tree().create_timer(float(delay_frames) / AudioServer.get_mix_rate()).timeout.connect(player.play)
	else:
		player.play()


func _process(_delta: float) -> void:
	for deck in decks.duplicate():
		deck.pump()
		var heard: int = deck.audible()
		if not deck.announced and deck.gen != null and heard >= deck.lead:
			deck.announced = true
			song_started.emit(deck.song, deck.variant)
		while not deck.events.is_empty() and deck.events[0][0] <= heard:
			var e = deck.events.pop_front()
			section_started.emit(deck.song, e[1])
		if deck.play_until >= 0 and heard >= deck.play_until and not deck.ending and deck == current_deck():
			deck.play_until = -1
			if not deck.next_choice.is_empty() and soundtrack_name != "":  # same family: the next song cross-fades in, no gap
				var fade: float = deck.crossfade
				_next_in_state({"at": "bar", "fade": fade, "fade_in": fade, "stinger": null, "start": null}, deck.next_choice)
			elif deck.flow != null:
				deck.end_song()
			else:
				_end_deck(deck, "bar", deck.fade_out)
		if deck.finished and deck.gen != null and deck.gen.get_frames_available() >= deck.capacity:
			_retire(deck)  # everything it pushed has been heard


func _retire(deck: Deck) -> void:
	decks.erase(deck)
	if deck.player != null:
		deck.player.queue_free()
	_song_ended(deck)


## Tests: the newest deck's next `frames` output frames (set `offline = true` before playing).
func render(frames: int) -> PackedVector2Array:
	var deck := _newest()
	if deck != null and not deck.announced:
		deck.announced = true
		song_started.emit(deck.song, deck.variant)
	var out := deck.produce(frames) if deck != null else PackedVector2Array()
	for d in decks:
		while not d.events.is_empty() and d.events[0][0] <= d.pushed:
			section_started.emit(d.song, d.events.pop_front()[1])
	return out
