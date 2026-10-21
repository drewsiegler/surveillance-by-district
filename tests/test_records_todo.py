"""The camera converter's to-do list, read from PRA Tracker's checkout. The responses are made up."""

import json

import records_todo

RESPONSES = [
    {"agency": "Exampleville Police Department", "response_date": "2026-10-21", "file": "Exampleville cameras.pdf",
     "request": "made-up-1", "items": ["ALPR camera locations and install dates"]},
    {"agency": "Sampletown Police Department", "response_date": "2026-12-04", "file": "/nowhere/Sampletown cameras.pdf",
     "request": "made-up-2", "items": ["ALPR camera locations and install dates"]},
]


def make_tracker(path, responses=RESPONSES):
    path.mkdir(parents=True)
    (path / records_todo.TODO).write_text(json.dumps({"about": "private", "responses": responses}))
    return path.resolve()


def test_a_given_path_comes_first_then_the_environment_then_beside(tmp_path, monkeypatch):
    given, env = make_tracker(tmp_path / "given"), make_tracker(tmp_path / "env")
    assert records_todo.locate(given, {"PRA_TRACKER": str(env)}) == given
    assert records_todo.locate(None, {"PRA_TRACKER": str(env)}) == env
    beside = make_tracker(tmp_path / "pra-tracker")
    monkeypatch.setattr(records_todo, "HERE", tmp_path / "surveillance-by-district")
    assert records_todo.locate(None, {}) == beside


def test_no_tracker_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(records_todo, "HERE", tmp_path / "surveillance-by-district")
    try:
        records_todo.locate(None, {})
    except records_todo.NotFound as err:
        assert "--pra-tracker" in str(err)
    else:
        raise AssertionError("expected NotFound")


def test_a_response_is_done_once_the_converter_has_its_cameras(tmp_path):
    converted = tmp_path / "record_cameras.json"
    assert records_todo.converted(converted) == set()  # no converter output yet: all waiting
    converted.write_text(json.dumps({"cameras": [
        {"agency": "Exampleville Police Department", "response_date": "2026-10-21", "lat": 37.28, "lon": -121.95}]}))
    done = records_todo.converted(converted)
    assert [r["request"] for r in records_todo.waiting(RESPONSES, done)] == ["made-up-2"]


def test_it_prints_the_list_and_writes_nothing(tmp_path, monkeypatch, capsys):
    root = make_tracker(tmp_path / "pra-tracker")
    monkeypatch.setattr(records_todo, "CONVERTED", tmp_path / "none.json")
    before = sorted(p.name for p in records_todo.HERE.rglob("*") if ".venv" not in p.parts)
    assert records_todo.main(["--pra-tracker", str(root)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("2 camera lists to convert, from PRA Tracker:\n")
    assert "  Exampleville Police Department, received Oct 21, 2026: Exampleville cameras.pdf\n" in out
    assert "/nowhere/Sampletown cameras.pdf (not found at that path)" in out
    assert sorted(p.name for p in records_todo.HERE.rglob("*") if ".venv" not in p.parts) == before


def test_the_build_never_reads_it():
    build = (records_todo.HERE / "src" / "build.py").read_text()
    assert "records_todo" not in build and records_todo.TODO not in build
