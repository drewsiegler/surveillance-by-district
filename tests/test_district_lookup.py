"""Finding District Lookup's checkout."""

import pytest

import district_lookup


def make_checkout(path):
    (path / "src").mkdir(parents=True)
    (path / "data").mkdir()
    (path / "src" / "layers.py").write_text("")
    (path / "data" / "layers.json").write_text("{}")
    return path.resolve()


def test_a_given_path_comes_first_then_the_environment(tmp_path):
    given, env = make_checkout(tmp_path / "given"), make_checkout(tmp_path / "env")
    assert district_lookup.locate(given, {"DISTRICT_LOOKUP": str(env)}) == given
    assert district_lookup.locate(None, {"DISTRICT_LOOKUP": str(env)}) == env


def test_falls_back_to_the_folder_beside_this_one(tmp_path, monkeypatch):
    beside = make_checkout(tmp_path / "district-lookup")
    monkeypatch.setattr(district_lookup, "HERE", tmp_path / "surveillance-by-district")
    assert district_lookup.locate(None, {}) == beside


def test_a_folder_without_district_lookup_in_it_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(district_lookup, "HERE", tmp_path / "surveillance-by-district")
    (tmp_path / "empty").mkdir()
    with pytest.raises(district_lookup.NotFound, match="git clone"):
        district_lookup.locate(tmp_path / "empty", {})


def test_loaded_maps_say_which_version_they_are(dl):
    assert dl["layers"] and dl["version"]
    assert callable(dl["lookup_point"])
