"""The build from start to finish, with OpenStreetMap faked or offline."""

import requests

import build
import cameras


def fake_overpass(monkeypatch, answer):
    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return answer

    monkeypatch.setattr(requests, "post", lambda url, **kwargs: Response())


def test_offline_build_uses_the_saved_cameras(tmp_path):
    assert build.main(["--offline", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "index.html").exists()


def test_fresh_cameras_are_saved_and_built(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "alpr_cameras.json"
    monkeypatch.setattr(cameras, "SNAPSHOT_PATH", snapshot_path)
    fake_overpass(monkeypatch, {"osm3s": {"timestamp_osm_base": "2030-01-01T00:00:00Z"}, "elements": [
        {"type": "node", "id": 1, "lat": 37.338163163635, "lon": -121.886224209159,
         "tags": {"surveillance:type": "ALPR", "manufacturer": "Flock Safety"}}]})
    assert build.main(["--out", str(tmp_path / "site")]) == 0
    assert cameras.read(snapshot_path)["as_of"] == "2030-01-01T00:00:00Z"
    assert '"total":1' in (tmp_path / "site" / "index.html").read_text()


def test_build_goes_ahead_from_the_saved_copy_when_openstreetmap_is_down(tmp_path, monkeypatch, capsys):
    saved = cameras.read()
    monkeypatch.setattr(cameras.time, "sleep", lambda seconds: None)

    def down(*args, **kwargs):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests, "post", down)
    assert build.main(["--out", str(tmp_path)]) == 0
    assert "Building from the saved copy" in capsys.readouterr().err
    assert cameras.read() == saved  # nothing overwritten
    assert f'"as_of":"{saved["as_of"]}"' in (tmp_path / "index.html").read_text()


def test_missing_district_lookup_is_explained(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISTRICT_LOOKUP", str(tmp_path / "nowhere"))
    monkeypatch.setattr(build.district_lookup, "HERE", tmp_path)
    assert build.main(["--offline", "--out", str(tmp_path / "site")]) == 1
    assert "git clone" in capsys.readouterr().err
