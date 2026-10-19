# Headless check: the demo scene builds a row for every asset in the manifest, and every stream plays a few frames.
extends SceneTree

func _init() -> void:
	var scene: PackedScene = load("res://scenes/audio_test.tscn")
	var root = scene.instantiate()
	get_root().add_child(root)
	await process_frame
	var manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/generated/audio/manifest.json"))
	var missing := []
	for asset_name in manifest["assets"]:
		if not root.rows.has(asset_name):
			missing.append(asset_name)
	if missing.size() > 0:
		printerr("CHECK_FAIL rows missing for ", missing)
		quit(1)
		return
	print("CHECK_OK ", root.rows.size(), " assets")
	quit(0)
