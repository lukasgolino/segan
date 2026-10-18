from segan.notes import note_name, parse_key, parse_note, transpose_key


def test_parse_note() -> None:
    assert parse_note("A4") == 69
    assert parse_note("C4") == 60
    assert parse_note("C#5") == 73
    assert parse_note("Db5") == 73
    assert parse_note("Bb2") == 46
    assert parse_note("C-1") == 0
    assert parse_note("H4") is None and parse_note("A") is None and parse_note(4) is None
    assert note_name(70) == "A#4" and note_name(70, flats=True) == "Bb4"


def test_keys_and_rows() -> None:
    key = parse_key("A minor")
    assert key is not None and key.scale == "minor" and key.root == 9
    rows = key.notes_between(parse_note("A3") or 0, parse_note("A4") or 0)
    assert [key.name(m) for m in rows] == ["A4", "G4", "F4", "E4", "D4", "C4", "B3", "A3"]
    assert parse_key("C# dorian") is not None and parse_key("X major") is None and parse_key("A") is None
    assert parse_key("F major") is not None and parse_key("F major").flats  # type: ignore[union-attr]


def test_degree_shift_and_mode_mapping() -> None:
    key = parse_key("C major")
    assert key is not None
    assert key.degree_shift(60, 2) == 64 and key.degree_shift(60, -1) == 59 and key.degree_shift(61, 1) is None
    major = parse_key("A major")
    minor = parse_key("A minor")
    assert minor is not None and major is not None
    assert minor.map_to(major, 72) == 73  # C (minor third) -> C# (major third)
    assert minor.map_to(major, 69) == 69
    assert transpose_key(minor, 2).root == 11
