"""The built website: one self-contained page, a CSV and a JSON file."""

import json
import re
from datetime import datetime, timezone

import pytest

import cameras
import website
from conftest import camera

BUILT = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def built(dl, shapes, tmp_path_factory):
    snapshot = {"as_of": "2026-10-14T18:57:00Z", "license": cameras.LICENSE, "cameras": [
        camera(1, "san_jose_city_hall", manufacturer="Flock Safety"),
        camera(2, "campbell_city_hall", operator="</script><script>alert(1)</script>"),
        camera(3, "san_francisco_city_hall"),
    ]}
    result = cameras.report(dl, snapshot, shapes)
    out = tmp_path_factory.mktemp("site")
    paths = website.write_site(dl, result, shapes, out, built=BUILT)
    page = (out / "index.html").read_text(encoding="utf-8")
    return {"out": out, "paths": paths, "page": page, "result": result}


def embedded_data(page):
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
    return json.loads(match.group(1))


def test_writes_the_page_and_both_downloads(built):
    assert sorted(p.name for p in built["paths"]) == [
        "index.html", "license_plate_readers_by_district.csv", "license_plate_readers_by_district.json"]
    assert (built["out"] / "license_plate_readers_by_district.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_page_loads_nothing_from_anywhere_else(built):
    page = built["page"]
    assert "<script src" not in page and "<link rel=\"stylesheet\"" not in page
    assert "@import" not in page and "url(http" not in page
    assert "fonts.googleapis" not in page


def test_page_carries_its_numbers_and_where_they_came_from(built, dl):
    data = embedded_data(built["page"])
    assert data["total"] == 2 and data["flock"] == 1
    assert data["as_of"] == "2026-10-14T18:57:00Z" and data["built"] == "2026-10-14T13:00:00Z"
    assert data["district_lookup"]["version"] == dl["version"]
    assert [m["id"] for m in data["maps"]] == [layer["id"] for layer in dl["layers"]]
    assert "cameras" not in data  # the map has a dot for each; the JSON download lists them


def test_text_from_openstreetmap_cant_break_out_of_the_page(built):
    page = built["page"]
    assert page.count("<script") == 2  # the data block and the page's own script
    operators = [r["operators"] for m in embedded_data(page)["maps"] for r in m["rows"]]
    assert any("</script>" in text for text in operators)  # survives intact as data


def test_map_has_a_group_per_map_and_a_dot_per_camera(built):
    page, result = built["page"], built["result"]
    groups = re.findall(r'<g class="layer" data-map="([^"]+)">(.*?)</g>', page, re.S)
    assert [map_id for map_id, _ in groups] == [m["id"] for m in result["maps"]]
    for (map_id, body), found in zip(groups, result["maps"]):
        indexes = [int(i) for i in re.findall(r'data-i="(\d+)"', body)]
        assert indexes and all(not found["rows"][i]["elsewhere"] for i in indexes)
    assert page.count("<circle") == result["total"]


def test_json_download_lists_each_camera_under_its_license(built):
    data = json.loads((built["out"] / "license_plate_readers_by_district.json").read_text())
    assert [c["id"] for c in data["cameras"]] == [1, 2]
    assert "ODbL" in data["license"] and "OpenStreetMap" in data["license"]


def test_projection_keeps_the_county_in_proportion():
    projection = website.Projection(-122.2, 36.9, -121.2, 37.5)
    assert projection.point(-122.2, 37.5) == (0, 0)
    x, y = projection.point(-121.2, 36.9)
    assert x == website.WIDTH and projection.height - 1 <= y <= projection.height
    # A degree of longitude is about 0.79 of a degree of latitude here.
    assert 0.45 < projection.height / website.WIDTH < 0.8


def test_script_json_cant_close_its_element():
    text = website.script_json({"x": "</script><!--"})
    assert "<" not in text and json.loads(text) == {"x": "</script><!--"}
