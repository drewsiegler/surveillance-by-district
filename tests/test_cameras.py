"""License plate readers counted by district, with OpenStreetMap faked.
Cameras are placed at public buildings from POINTS."""

import csv
import math
import io

import pytest
import requests
from shapely import union_all

import cameras
from conftest import POINTS, camera, largest_piece


@pytest.fixture(scope="module")
def snapshot():
    return {
        "as_of": "2026-10-14T18:57:00Z",
        "license": cameras.LICENSE,
        "cameras": [
            camera(1, "san_jose_city_hall", manufacturer="Flock Safety"),
            camera(2, "san_jose_city_hall", manufacturer="Motorola Solutions",
                   operator="San Jose Police Department"),
            camera(3, "campbell_city_hall", manufacturer="Flock Safety"),
            camera(4, "stanford_campus"),
            camera(5, "san_francisco_city_hall", manufacturer="Flock Safety"),
        ],
    }


@pytest.fixture(scope="module")
def result(dl, shapes, snapshot):
    """Built once for the module; tests only read it."""
    return cameras.report(dl, snapshot, shapes)


def rows(result, map_id):
    return next(found for found in result["maps"] if found["id"] == map_id)["rows"]


def row(result, map_id, district_starts, within=None):
    return next(r for r in rows(result, map_id)
                if r["district"].startswith(district_starts) and r["within"] == within)


def test_only_cameras_inside_the_county_are_counted(result):
    assert result["total"] == 4
    assert result["flock"] == 2  # San Francisco's Flock camera isn't the county's
    assert [c["id"] for c in result["cameras"]] == [1, 2, 3, 4]


def test_council_districts_count_only_inside_their_own_city(result):
    san_jose_3 = row(result, "council_district", "3—", within="San Jose")
    assert san_jose_3["cameras"] == 2 and san_jose_3["flock"] == 1
    assert san_jose_3["other_makers"] == "Motorola Solutions 1"
    assert san_jose_3["operators"] == "San Jose Police Department 1"
    assert row(result, "council_district", "3—", within="Campbell")["cameras"] == 1
    council = rows(result, "council_district")
    # Stanford is unincorporated, so it counts toward no council district, and a
    # must_match map never gets an "elsewhere" row.
    assert sum(r["cameras"] for r in council) == 3
    assert not any(r["elsewhere"] for r in council)


def test_cameras_outside_every_area_of_a_map_are_counted_as_elsewhere(result):
    assert row(result, "city", "San Jose")["cameras"] == 2
    elsewhere = row(result, "city", cameras.ELSEWHERE)
    assert elsewhere["elsewhere"] and elsewhere["cameras"] == 1
    assert rows(result, "city")[-1] is elsewhere  # always listed last


def test_districts_without_cameras_are_listed_with_zero(result):
    supervisors = {r["district"].split("—")[0]: r["cameras"]
                   for r in rows(result, "santa_clara_county_supervisorial")}
    assert supervisors == {"D1": 0, "D2": 2, "D3": 0, "D4": 1, "D5": 1}


def test_neighbors_slivers_along_the_county_line_are_left_out(result):
    congress = {r["district"].split("—")[0] for r in rows(result, "us_congress")}
    assert congress == {"US-CA16", "US-CA17", "US-CA18", "US-CA19"}
    # The smallest real district stays in even with no cameras in it.
    assert row(result, "elementary_school_districts", "Luther Burbank")["cameras"] == 0


def test_a_camera_in_a_sliver_still_gets_counted(dl, shapes):
    """Found from the map data: skips if the Census ever stops drawing a sliver
    of Congressional District 13 inside the county."""
    county = cameras.covered_area(dl)
    congress = next(layer for layer in dl["layers"] if layer["id"] == "us_congress")
    sliver = union_all([g for district, g in zip(congress["display"], congress["geometries"])
                        if district.startswith("US-CA13")]).intersection(county)
    if sliver.is_empty:
        pytest.skip("no sliver of US-CA13 inside the county any more")
    point = largest_piece(sliver).representative_point()
    result = cameras.report(dl, {"cameras": [{"id": 1, "lat": point.y, "lon": point.x}]}, shapes)
    assert row(result, "us_congress", "US-CA13")["cameras"] == 1


def test_a_camera_flock_operates_counts_as_flock_when_its_maker_isnt_mapped(dl, shapes):
    found = cameras.report(dl, {"cameras": [
        camera(1, "san_jose_city_hall", operator="Flock Safety"),
        camera(2, "san_jose_city_hall", manufacturer="Axis Communications", operator="Flock Safety"),
    ]}, shapes)
    assert found["flock"] == 1
    san_jose = row(found, "city", "San Jose")
    assert san_jose["flock"] == 1 and san_jose["other_makers"] == "Axis Communications 1"


def test_districts_are_in_natural_order():
    assert sorted(["TA10", "TA2", "TA1"], key=cameras.natural_key) == ["TA1", "TA2", "TA10"]
    assert sorted(["C—Cm. B", "3—Cm. A", None], key=cameras.natural_key) == [None, "3—Cm. A", "C—Cm. B"]


def test_csv_lists_every_district_and_credits_openstreetmap(result):
    table = list(csv.reader(io.StringIO(cameras.csv_text(result))))
    assert table[0] == list(cameras.CSV_COLUMNS.values())
    assert len(table) == 2 + sum(len(found["rows"]) for found in result["maps"])
    assert "© OpenStreetMap contributors" in table[-1][0] and "ODbL" in table[-1][0]
    assert "2026-10-14" in table[-1][0]
    san_jose = next(r for r in table if r[1] == "San Jose" and r[2].startswith("3—"))
    assert san_jose[0] == "City Council District" and san_jose[3] == "2"


def test_bounding_box_takes_in_the_whole_county(dl):
    south, west, north, east = cameras.bounding_box(dl)
    for layer in dl["layers"]:
        if layer["coverage"]:
            for geometry in layer["geometries"]:
                minx, miny, maxx, maxy = geometry.bounds
                assert west <= minx and south <= miny and maxx <= east and maxy <= north


# --- Getting the data from OpenStreetMap ---------------------------------------

ANSWER = {
    "osm3s": {"timestamp_osm_base": "2026-10-14T18:57:00Z"},
    "elements": [
        {"type": "node", "id": 30, "lat": 37.3, "lon": -121.9,
         "tags": {"surveillance:type": "ALPR", "brand": "Flock Safety"}},
        {"type": "node", "id": 10, "lat": 37.4, "lon": -122.0,
         "tags": {"surveillance:type": "ALPR", "manufacturer": "Genetec", "operator": "Sunnyvale DPS"}},
        {"type": "node", "id": 20, "lat": 37.2, "lon": -121.8,
         "tags": {"surveillance:type": "ALPR", "demolished:man_made": "surveillance"}},
        {"type": "way", "id": 40, "tags": {"surveillance:type": "ALPR"}},
    ],
}
BOX = (36.892, -122.203, 37.485, -121.208)
SERVERS = ["https://first.example/api/interpreter", "https://second.example/api/interpreter"]


class FakeResponse:
    def __init__(self, answer, status_code=200):
        self.answer, self.status_code = answer, status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.answer


def test_answer_keeps_standing_cameras_in_id_order():
    snapshot = cameras.parse(ANSWER, BOX)
    assert snapshot["as_of"] == "2026-10-14T18:57:00Z" and snapshot["bbox"] == list(BOX)
    assert snapshot["cameras"] == [
        {"id": 10, "lat": 37.4, "lon": -122.0, "manufacturer": "Genetec", "operator": "Sunnyvale DPS"},
        {"id": 30, "lat": 37.3, "lon": -121.9, "manufacturer": "Flock Safety"},
    ]


def test_a_partial_answer_is_refused():
    with pytest.raises(ValueError):
        cameras.parse({**ANSWER, "remark": "runtime error: Query timed out"}, BOX)
    with pytest.raises(ValueError):
        cameras.parse({"osm3s": {}}, BOX)


def test_fetch_sends_only_the_box_and_moves_on_from_a_down_server(monkeypatch):
    calls = []

    def fake_post(url, data, timeout, headers):
        calls.append((url, data, headers))
        if url == SERVERS[0]:
            raise requests.ConnectionError("down")
        return FakeResponse(ANSWER)

    monkeypatch.setattr(cameras, "OVERPASS_URLS", SERVERS)
    monkeypatch.setattr(requests, "post", fake_post)
    snapshot = cameras.fetch(BOX)
    assert [url for url, _, _ in calls] == SERVERS
    _, data, headers = calls[-1]
    assert list(data) == ["data"]
    assert "(36.892,-122.203,37.485,-121.208)" in data["data"]
    assert headers["User-Agent"].startswith("Surveillance by District")
    assert len(snapshot["cameras"]) == 2


def test_a_busy_server_is_asked_again_after_a_pause(monkeypatch):
    statuses, pauses = [504, 429, 200], []
    monkeypatch.setattr(cameras.time, "sleep", pauses.append)
    monkeypatch.setattr(requests, "post",
                        lambda url, **kwargs: FakeResponse(ANSWER, statuses.pop(0)))
    assert len(cameras.fetch(BOX)["cameras"]) == 2
    assert pauses == list(cameras.RETRY_PAUSES)


def test_a_server_still_busy_after_the_retries_gives_a_plain_answer(monkeypatch):
    monkeypatch.setattr(cameras.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: FakeResponse({}, 504))
    with pytest.raises(cameras.RefreshError, match="busy"):
        cameras.fetch(BOX)


def test_a_server_running_behind_is_passed_over(monkeypatch):
    stale = {**ANSWER, "osm3s": {"timestamp_osm_base": "2026-07-28T00:00:00Z"}}
    answers = dict(zip(SERVERS, [stale, ANSWER]))
    monkeypatch.setattr(cameras, "OVERPASS_URLS", SERVERS)
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: FakeResponse(answers[url]))
    assert cameras.fetch(BOX, not_before="2026-10-01T00:00:00Z")["as_of"] == "2026-10-14T18:57:00Z"
    answers[SERVERS[1]] = stale
    with pytest.raises(cameras.RefreshError):
        cameras.fetch(BOX, not_before="2026-10-01T00:00:00Z")


# --- Saving and loading -----------------------------------------------------------

def test_saved_snapshot_reads_back_one_camera_per_line(tmp_path):
    snapshot = cameras.parse(ANSWER, BOX)
    path = tmp_path / "cameras.json"
    cameras.write(snapshot, path)
    first = path.read_bytes()
    assert cameras.read(path) == snapshot
    assert sum(line.lstrip().startswith('{"id"') for line in path.read_text().splitlines()) == 2
    cameras.write(snapshot, path)
    assert path.read_bytes() == first  # the same data always writes the same bytes
    cameras.write({**snapshot, "cameras": []}, path)
    assert cameras.read(path)["cameras"] == []
    path.write_text("{not json", encoding="utf-8")
    assert cameras.read(path) is None


def test_committed_snapshot_is_there_and_sound():
    snapshot = cameras.read()
    assert snapshot and snapshot["as_of"] and snapshot["license"] == "ODbL-1.0"
    ids = [c["id"] for c in snapshot["cameras"]]
    assert ids and ids == sorted(set(ids))
    south, west, north, east = snapshot["bbox"]
    assert all(south <= c["lat"] <= north and west <= c["lon"] <= east for c in snapshot["cameras"])


# --- Cameras from police records ------------------------------------------------------

METER = 1 / cameras.METERS_PER_DEGREE  # a meter north, in degrees of latitude


def listed(point, status="installed", north=0.0, agency="Exampleville Police Department", **extra):
    lat, lon = POINTS[point]
    return {"agency": agency, "response_date": "2026-11-24", "location": f"#{len(extra)} Example St",
            "lat": lat + north * METER, "lon": lon, "device": "license plate reader",
            "status": status, "maker": "Flock Safety", **extra}


def test_each_listed_camera_claims_the_nearest_mapped_one_within_50_meters():
    corner = [{"lat": 37.3 + n * METER, "lon": -121.9} for n in (0, 4)]
    mapped = [{"lat": 37.3 + n * METER, "lon": -121.9} for n in (3, 60, 49 + 4)]
    # The listed camera 4 m north takes the mapped one 1 m from it, so the
    # other listed camera, 3 m from that one, has to settle for the next, 53 m off: too far.
    assert cameras.same_cameras(corner, mapped) == {0: 1}
    assert cameras.same_cameras(corner, mapped, meters=60) == {0: 1, 2: 0}
    # East and west too, where a degree is shorter than it is north and south.
    east = [{"lat": 37.3, "lon": -121.9 + 45 * METER / math.cos(math.radians(37.3))}]
    assert cameras.same_cameras(corner[:1], east) == {0: 0}
    assert cameras.same_cameras(corner[:1], east, meters=40) == {}
    assert cameras.same_cameras([], mapped) == {}


@pytest.fixture(scope="module")
def with_records(dl, shapes, snapshot):
    """San José has a police list here: one camera on it volunteers also
    mapped (OpenStreetMap's camera 1, 10 m off), one they didn't, one planned,
    and a video camera installed and another planned."""
    records = {
        "responses": [{"agency": "Exampleville Police Department", "response_date": "2026-11-24",
                       "installed": 2, "planned": 1, "video": 1}],
        "cameras": [
            listed("san_jose_city_hall", north=10),
            listed("san_jose_city_hall", north=400),
            listed("san_jose_city_hall", status="planned", north=800),
            {**listed("san_jose_city_hall"), "device": "video camera"},
            {**listed("san_jose_city_hall", status="planned", north=900), "device": "video camera"},
            listed("san_francisco_city_hall"),  # outside the county
        ],
    }
    return cameras.report(dl, snapshot, shapes, records)


def test_a_camera_on_the_police_list_and_on_the_map_counts_once(with_records):
    # OpenStreetMap's 2 to 4 are still counted; its 1 is the listed camera 10 m off.
    assert with_records["total"] == 5 and with_records["records"] == 2 and with_records["volunteers"] == 3
    first = with_records["cameras"][0]
    assert first["source"] == "records" and first["osm_id"] == 1 and first["operator"] == "Exampleville Police Department"
    assert [c.get("id") for c in with_records["cameras"] if c["source"] == "osm"] == [2, 3, 4]
    assert with_records["flock"] == 3  # both listed cameras, and Campbell's


def test_mapped_cameras_in_the_listed_city_but_not_on_the_list_are_marked(with_records):
    marked = [c["id"] for c in with_records["cameras"] if "not_in_records" in c]
    assert marked == [2]  # San José's Motorola camera; Campbell's and Stanford's aren't San José's
    san_jose = row(with_records, "city", "San Jose")
    assert (san_jose["cameras"], san_jose["records"], san_jose["volunteers"], san_jose["not_in_records"]) == (3, 2, 1, 1)
    source = with_records["sources"][0]
    assert source["cities"] == ["San Jose"] and source["installed"] == 2 and source["also_mapped"] == 1
    assert source["planned"] == 1 and source["not_in_records"] == 1 and source["video"] == 1


def test_districts_say_whether_a_police_list_covers_them(with_records):
    assert row(with_records, "city", "San Jose")["records_here"]
    assert not row(with_records, "city", "Campbell")["records_here"]
    assert row(with_records, "council_district", "3—", within="San Jose")["records_here"]
    # No San José in Campbell's council districts or Palo Alto, so a 0 there means no list yet.
    assert not row(with_records, "council_district", "3—", within="Campbell")["records_here"]
    assert not row(with_records, "city", "Palo Alto")["records_here"]
    # Every supervisor district takes in some of San José.
    assert all(r["records_here"] for r in rows(with_records, "santa_clara_county_supervisorial")
               if not r["elsewhere"])


def test_planned_cameras_arent_counted(with_records):
    assert [c["status"] for c in with_records["planned"]] == ["planned"]
    assert all(c["status"] == "installed" for c in with_records["cameras"] if c["source"] == "records")


def test_video_cameras_are_counted_on_their_own(with_records):
    assert with_records["video"] == 1
    assert not any(c.get("device") for c in with_records["cameras"])  # not license plate readers
    assert [c["status"] for c in with_records["video_cameras"]] == ["installed", "planned"]
    san_jose = row(with_records, "city", "San Jose")
    assert san_jose["video"] == 1 and san_jose["cameras"] == 3  # the video camera isn't in the 3
    assert row(with_records, "council_district", "3—", within="San Jose")["video"] == 1
    assert row(with_records, "city", "Campbell")["video"] == 0
    source = with_records["sources"][0]
    assert (source["video"], source["video_planned"]) == (1, 1)


def test_a_list_of_only_video_cameras_still_covers_its_district(dl, shapes):
    found = cameras.report(dl, {"cameras": []}, shapes, {
        "responses": [{"agency": "Exampleville Police Department", "response_date": "2026-11-24"}],
        "cameras": [{**listed("campbell_city_hall"), "device": "video camera"}]})
    campbell = row(found, "city", "Campbell")
    assert (campbell["cameras"], campbell["video"], campbell["records_here"]) == (0, 1, True)
    assert found["total"] == 0 and found["video"] == 1


def test_csv_leaves_the_records_column_blank_where_no_list_covers(with_records):
    table = list(csv.reader(io.StringIO(cameras.csv_text(with_records))))
    header = table[0]
    get = lambda r, name: r[header.index(cameras.CSV_COLUMNS[name])]
    san_jose = next(r for r in table if r[0] == "City / Town (Santa Clara County)" and r[2] == "San Jose")
    campbell = next(r for r in table if r[0] == "City / Town (Santa Clara County)" and r[2] == "Campbell")
    assert (get(san_jose, "records"), get(san_jose, "not_in_records"), get(san_jose, "video")) == ("2", "1", "1")
    assert (get(campbell, "records"), get(campbell, "not_in_records"), get(campbell, "video"),
            get(campbell, "cameras")) == ("", "", "", "1")
    assert "Exampleville Police Department's list" in table[-1][0] and "OpenStreetMap" in table[-1][0]
    assert "Video cameras" in table[-1][0]
