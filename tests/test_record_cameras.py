"""The camera converter, reading a made-up list laid out like Flock Safety's
installation list (the layout San José police sent). Every name in it is
invented; the coordinates are public buildings from POINTS."""

import json

import pytest

import record_cameras
import records_todo
from conftest import POINTS

AGENCY, RECEIVED = "Exampleville Police Department", "2026-11-24"
SJ, CAMPBELL = POINTS["san_jose_city_hall"], POINTS["campbell_city_hall"]
HEADER = ("SFDC Account Name,Deployment Name,Planning Status,Substatus,Scheduling Status,Installed Date,"
          "Location Name,Device Type,Latitude,Longitude,Permitting Jurisdiction")


def row(location, status="INSTALLED", device="LPR Camera", point=SJ, when="Complete - Apr 18, 2022",
        lat=None, lon=None):
    lat = point[0] if lat is None else lat
    lon = point[1] if lon is None else lon
    return f'Example PD,Example deployment,{status},,"{when}",Complete,{location},{device},{lat},{lon},Example'


ROWS = [
    row("#001 Sample Ave @ Example St NB"),
    row("C#001 Sample Ave @ Example St", device="Video Camera (Fixed)"),       # a video camera beside it
    row("#002 Old Rd @ Elm - original", point=CAMPBELL),                        # moved, and installed again:
    row("#002 New Rd @ Oak SB", when="Complete - May 9, 2024", lat=SJ[0] + 0.01),  # the old spot goes
    row("#003 Stay Rd @ Pine - original", lat=SJ[0] + 0.02),                    # move still planned:
    row("#003 Next Rd @ Ash", status="Planning", when="Pending", lat=SJ[0] + 0.03),  # the old spot stays
    row("#004 Twice Blvd @ Main", lat=SJ[0] + 0.04),                            # listed under two deployments
    row("#004 Twice Blvd @ Main", lat=SJ[0] + 0.04),
    row("F#005 Soon St @ First", status="Install", when="Pending", lat=SJ[0] + 0.05),
    row("LPR#006a Moved Ave @ Second", when="Complete", lat=SJ[0] + 0.06),      # "a" marks the new spot
    row("#006 Former Ave @ Third - original", lat=SJ[0] + 0.07),
]


def write_list(tmp_path, rows=ROWS, header=HEADER):
    path = tmp_path / "Example cameras.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8-sig")
    return path


@pytest.fixture
def converted(tmp_path):
    return record_cameras.read_flock_list(write_list(tmp_path), AGENCY, RECEIVED)


def test_each_camera_keeps_its_agency_response_date_and_place(converted):
    cameras, _ = converted
    assert all(c["agency"] == AGENCY and c["response_date"] == RECEIVED for c in cameras)
    first = cameras[0]
    assert first["location"] == "#001 Sample Ave @ Example St NB"
    assert (first["lat"], first["lon"]) == SJ
    assert first["installed"] == "2022-04-18" and first["maker"] == "Flock Safety"
    assert first["match"] == "coordinates in the records"


def test_installed_planned_and_video_cameras_are_told_apart(converted):
    cameras, _ = converted
    kinds = sorted((c["location"].split(" ")[0], c["device"], c["status"]) for c in cameras)
    assert kinds == [
        ("#001", "license plate reader", "installed"),
        ("#002", "license plate reader", "installed"),
        ("#003", "license plate reader", "installed"),
        ("#003", "license plate reader", "planned"),
        ("#004", "license plate reader", "installed"),
        ("C#001", "video camera", "installed"),
        ("F#005", "license plate reader", "planned"),
        ("LPR#006a", "license plate reader", "installed"),
    ]
    assert all("installed" not in c for c in cameras if c["status"] == "planned")


def test_old_spots_of_moved_cameras_and_repeats_are_left_out(converted):
    cameras, left_out = converted
    assert left_out == {"old spot of a camera since moved": 2, "listed twice": 1}
    # The original spot stays while the move is only planned.
    assert any(c["location"] == "#003 Stay Rd @ Pine - original" for c in cameras)


def test_a_list_in_another_layout_is_refused_plainly(tmp_path):
    path = write_list(tmp_path, ["123 Main St,Flock"], header="Address,Vendor")
    with pytest.raises(record_cameras.ConvertError, match="Location Name, Device Type, Latitude"):
        record_cameras.read_flock_list(path, AGENCY, RECEIVED)


@pytest.mark.parametrize("bad_row, problem", [
    (row("#009 Nowhere", lat="", lon=""), "no usable latitude and longitude"),
    (row("#009 Swapped", lat=SJ[1], lon=SJ[0]), "no usable latitude and longitude"),
    (row("#009 Gone", status="Removed"), "planning status 'Removed'"),
    (row("#009 Drone", device="Drone"), "device type 'Drone'"),
])
def test_a_row_that_cant_be_placed_stops_the_whole_list(tmp_path, bad_row, problem):
    with pytest.raises(record_cameras.ConvertError, match=problem):
        record_cameras.read_flock_list(write_list(tmp_path, [*ROWS, bad_row]), AGENCY, RECEIVED)


def test_saved_list_reads_back_one_camera_per_line(tmp_path, converted):
    path = tmp_path / "record_cameras.json"
    data = record_cameras.add(record_cameras.read(path), AGENCY, RECEIVED, converted[0])
    record_cameras.write(data, path)
    first = path.read_bytes()
    assert record_cameras.read(path) == data
    assert sum('"location"' in line for line in path.read_text().splitlines()) == 8
    record_cameras.write(data, path)
    assert path.read_bytes() == first  # the same list always writes the same bytes
    assert data["responses"] == [{"agency": AGENCY, "response_date": RECEIVED,
                                  "list": "Flock Safety installation list",
                                  "installed": 5, "planned": 2, "moves": 1, "video": 1}]


def test_a_newer_list_replaces_the_agencys_cameras_and_keeps_the_others(converted):
    other = [{**c, "agency": "Sampletown Police Department"} for c in converted[0][:2]]
    data = record_cameras.add({"responses": [], "cameras": []}, "Sampletown Police Department",
                              RECEIVED, other)
    data = record_cameras.add(data, AGENCY, RECEIVED, converted[0])
    data = record_cameras.add(data, AGENCY, "2027-01-05", [{**converted[0][0], "response_date": "2027-01-05"}])
    assert [(r["agency"], r["response_date"]) for r in data["responses"]] == [
        (AGENCY, "2027-01-05"), ("Sampletown Police Department", RECEIVED)]
    assert sum(c["agency"] == AGENCY for c in data["cameras"]) == 1
    assert sum(c["agency"] == "Sampletown Police Department" for c in data["cameras"]) == 2


def test_the_to_do_list_sees_a_converted_response_as_done(tmp_path, monkeypatch, capsys):
    path = tmp_path / "record_cameras.json"
    monkeypatch.setattr(record_cameras, "PATH", path)
    assert record_cameras.main([str(write_list(tmp_path)), "--agency", AGENCY, "--received", RECEIVED]) == 0
    out = capsys.readouterr().out
    assert "8 cameras saved" in out and "2 rows left out: old spot of a camera since moved" in out
    assert records_todo.converted(path) == {(AGENCY, RECEIVED)}


def test_the_command_says_what_went_wrong(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(record_cameras, "PATH", tmp_path / "record_cameras.json")
    assert record_cameras.main([str(tmp_path / "missing.csv"), "--agency", AGENCY, "--received", RECEIVED]) == 1
    assert "Can't read" in capsys.readouterr().err
    assert record_cameras.main([str(write_list(tmp_path)), "--agency", AGENCY, "--received", "Nov 24"]) == 1
    assert "2026-11-24" in capsys.readouterr().err
    assert not (tmp_path / "record_cameras.json").exists()


def test_committed_records_are_sound():
    data = record_cameras.read()
    for camera in data["cameras"]:
        assert camera["agency"] and camera["response_date"] and camera["location"]
        assert 36.8 < camera["lat"] < 37.6 and -122.4 < camera["lon"] < -121.1
        assert camera["status"] in {"installed", "planned"}
        assert camera["device"] in record_cameras.DEVICES.values()
    assert data["cameras"] == sorted(data["cameras"], key=record_cameras.sort_key)
    for response in data["responses"]:
        mine = [c for c in data["cameras"] if c["agency"] == response["agency"]]
        assert {c["response_date"] for c in mine} == {response["response_date"]}
        readers = [c for c in mine if c["device"] == "license plate reader"]
        assert response["installed"] == sum(c["status"] == "installed" for c in readers)
        assert response["planned"] == sum(c["status"] == "planned" for c in readers)
    raw = json.dumps(data)
    assert "pra-tracker" not in raw and "requests.yaml" not in raw  # nothing from PRA Tracker
