"""The built website: one self-contained page, a CSV and a JSON file."""

import json
import re
from datetime import datetime, timezone

import pytest

import cameras
import website
from conftest import POINTS, camera

BUILT = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def built(dl, shapes, tmp_path_factory):
    snapshot = {"as_of": "2026-10-14T18:57:00Z", "license": cameras.LICENSE, "cameras": [
        camera(1, "san_jose_city_hall", manufacturer="Flock Safety"),
        camera(2, "campbell_city_hall", operator="</script><script>alert(1)</script>"),
        camera(3, "san_francisco_city_hall"),
    ]}
    # A made-up police list with OpenStreetMap's camera 1 on it, and one planned.
    lat, lon = POINTS["san_jose_city_hall"]
    listed = {"agency": "Exampleville Police Department", "response_date": "2026-11-24",
              "location": "#1 Example St", "lat": lat, "lon": lon, "device": "license plate reader",
              "status": "installed", "maker": "Flock Safety"}
    records = {"responses": [{"agency": listed["agency"], "response_date": "2026-11-24",
                              "installed": 1, "planned": 1, "video": 0}],
               "cameras": [listed, {**listed, "status": "planned", "lat": lat + 0.01},
                           {**listed, "device": "video camera"},
                           {**listed, "device": "video camera", "status": "planned", "lat": lat + 0.02}]}
    result = cameras.report(dl, snapshot, shapes, records)
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
    assert data["total"] == 2 and data["flock"] == 1  # camera 1 is on the police list: counted once
    assert data["records"] == 1 and data["volunteers"] == 1 and data["video"] == 1
    assert data["sources"][0]["agency"] == "Exampleville Police Department"
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
    dots = dict(re.findall(r'<g class="cams (\w+)">(.*?)</g>', page, re.S))
    assert {name: body.count("<circle") for name, body in dots.items()} == {
        "mapped": 1, "planned": 1, "listed": 1, "video": 0}
    # Video cameras are diamonds, each an outline over a halo; the planned one dashed.
    assert re.findall(r'<path class="(\w+(?: planned)?)"', dots["video"]) == [
        "halo", "mark", "halo planned", "mark planned"]
    assert page.count("<circle") == result["total"] + len(result["planned"])


def test_json_download_lists_each_camera_under_its_license(built):
    data = json.loads((built["out"] / "license_plate_readers_by_district.json").read_text())
    assert [(c["source"], c.get("id"), c.get("osm_id")) for c in data["cameras"]] == [
        ("records", None, 1), ("osm", 2, None)]
    assert "ODbL" in data["license"] and "OpenStreetMap" in data["license"]
    assert "Public Records Act" in data["license"]
    assert [c["status"] for c in data["planned"]] == ["planned"]
    assert [c["status"] for c in data["video_cameras"]] == ["installed", "planned"]


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


def test_map_has_zoom_controls_that_keep_lines_and_markers_in_proportion(built):
    page = built["page"]
    for button in ("zoom-in", "zoom-out", "zoom-all"):
        assert f'id="{button}"' in page
    assert re.search(r'<svg id="map" viewBox="0 0 1000 \d+"', page)
    # Lines hold their width on screen and markers grow more slowly than the map.
    assert "calc(1.2px / var(--k, 1))" in page and "scale(var(--grow, 1))" in page
    # The color variable markers are filled with is never reused for zooming.
    assert 'setProperty("--dot"' not in page


def test_camera_markers_are_placed_to_a_tenth_of_a_unit(built):
    projection = website.Projection(-122.2, 36.9, -121.2, 37.5)
    x, y = projection.spot(-121.886224, 37.338163)
    rounded = projection.point(-121.886224, 37.338163)
    assert all(len(v.partition(".")[2]) == 1 for v in (x, y))  # neither lands on a whole unit
    assert abs(float(x) - rounded[0]) <= 0.5 and abs(float(y) - rounded[1]) <= 0.5
    assert website.short(12.0) == "12" and website.short(3.14159) == "3.1"
    dots = re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', built["page"])
    assert dots and all(len(v.partition(".")[2]) <= 1 for pair in dots for v in pair)
