from pathlib import Path

import pytest

from segan.findings import SeganError
from segan.kit import load_kit_file, parse_kit
from segan.yamlio import parse_yaml

GOOD = """\
name: test
instruments:
  p: { name: lead, osc: pulse, duty: 0.25, env: [0.01, 0.1, 0.5, 0.2], range: [C4, C6] }
  é: { osc: sine, env: { attack: 0.1, release: 0.3 } }
  k: { drum: kick, tune: 60 }
groups:
  leads: [p, é]
"""


def parse(text: str, name: str | None = "test") -> tuple[object, list[str]]:
    kit, findings = parse_kit(parse_yaml(text), Path("x.kit.yaml"), name)
    return kit, [f"{f.rule} {f.where} {f.message}" for f in findings]


def test_valid_kit() -> None:
    kit, findings = parse(GOOD)
    assert findings == []
    assert kit is not None
    p = kit.instruments["p"]  # type: ignore[attr-defined]
    assert p.wave == "pulse" and p.duty == 0.25 and p.range == (60, 84)
    e = kit.instruments["é"]  # type: ignore[attr-defined]
    assert e.env.attack == 0.1 and e.env.release == 0.3 and e.env.sustain == 0.7
    assert kit.instruments["k"].drum_param("tune") == 60 and kit.instruments["k"].drum_param("decay") > 0  # type: ignore[attr-defined]
    assert kit.groups == {"leads": ("p", "é")}  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("name: test\ninstruments:\n  '.': { osc: sine }\n", "E005 instruments.. "),
        ("name: test\ninstruments:\n  ab: { osc: sine }\n", "ONE letter or digit"),
        ("name: test\ninstruments:\n  p: { osc: wobble }\n", "osc must be one of"),
        ("name: test\ninstruments:\n  p: { colour: red, osc: sine }\n", "unknown instrument field 'colour'"),
        ("name: test\ninstruments:\n  p: { osc: sine, env: [1, 2] }\n", "env must be"),
        ("name: test\ninstruments:\n  p: { gain: -3 }\n", "needs a sound source"),
        ("name: test\ninstruments:\n  p: { osc: sine, env: [0, 1, 0, 1, linear] }\n", "env curve must be"),
        ("name: test\ninstruments:\n  p: { osc: sine, env: { decay: 1, shape: exp } }\n", "unknown env field 'shape'"),
        ("name: test\ninstruments:\n  p: { osc: sine, tune: 40 }\n", "drum parameter"),
        ("name: test\ninstruments:\n  p: { osc: sine }\ngroups:\n  g: [q]\n", "unknown instrument key"),
        ("name: other\ninstruments:\n  p: { osc: sine }\n", "must match the file name"),
        ("name: test\ninstrument:\n  p: { osc: sine }\n", "unknown kit field"),
        ("name: test\ninstruments:\n  p: { osc: pulse, range: [C6, C4] }\n", "range must be"),
        ("name: test\ninstruments:\n  p: { name: a, osc: sine }\n  q: { name: a, osc: saw }\n", "names must be unique"),
    ],
)
def test_kit_errors(text: str, expected: str) -> None:
    kit, findings = parse(text)
    assert kit is None
    assert any(expected in f for f in findings), findings


def test_load_kit_file_reports_yaml_errors_with_lines(tmp_path: Path) -> None:
    path = tmp_path / "bad.kit.yaml"
    path.write_text("name: bad\ninstruments:\n  p: { osc: sine\n")
    with pytest.raises(SeganError) as exc:
        load_kit_file(path)
    assert exc.value.findings[0].rule == "E001" and exc.value.findings[0].line is not None


def test_demo_kits_are_valid() -> None:
    root = Path(__file__).parent.parent / "examples" / "demo" / "kits"
    for path in sorted(root.glob("*.kit.yaml")):
        load_kit_file(path)


def test_env_curve_forms() -> None:
    """#5: `exp` as a fifth env item, or `curve:` in the mapping form."""
    kit, findings = parse("name: test\ninstruments:\n  p: { osc: sine, env: [0, 1, 0, 2, exp] }\n  q: { osc: sine, env: { decay: 1, curve: exp } }\n  r: { osc: sine }\n")
    assert kit is not None, findings
    assert kit.instruments["p"].env.curve == "exp" and kit.instruments["p"].env.release == 2.0  # type: ignore[attr-defined]
    assert kit.instruments["q"].env.curve == "exp" and kit.instruments["r"].env.curve == "cubic"  # type: ignore[attr-defined]
    assert kit.instruments["p"].env.as_list() == [0.0, 1.0, 0.0, 2.0, "exp"]  # type: ignore[attr-defined]
