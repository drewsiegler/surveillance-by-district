"""The camera converter: turns a camera list an agency sent in answer to a
public records request into map points, saved in data/record_cameras.json.

    python src/record_cameras.py LIST.csv --agency "San José Police Department" --received 2026-11-24

The records themselves never go in this repo: the converter reads the file
from wherever it was saved and keeps only what the map needs. Every camera it
writes carries the agency and the date the response came in, which is how
records_todo.py knows a response is done, so use the same agency name and date
PRA Tracker has for it. Converting a newer list from the same agency replaces
that agency's cameras; other agencies' stay as they are.

It reads the installation list Flock Safety keeps for each customer, the file
San José police sent in November 2026, with a latitude and longitude for
every camera. Each row becomes:

  - installed or planned, from its planning status. Only installed cameras
    are counted; planned ones are drawn on the map as hollow rings.
  - a license plate reader or a video camera, from its device type. Video
    cameras are marked on the map and counted on their own, never as license
    plate readers.

Two kinds of row are left out. A row marked "original" is where a camera used
to be, once the list shows that camera (by its number) installed somewhere
else; while the move is still planned, the original spot is where it is. And a
row that repeats another's number and location is the same camera listed under
two deployments.

A list that gives street addresses or intersections instead of coordinates
will need a reader that geocodes them; this one says so rather than guess.
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "record_cameras.json"
ABOUT = ("Cameras from agencies' answers to public records requests, made by src/record_cameras.py. "
         "Don't edit it by hand; convert the agency's list again instead.")
SOURCE = "Agencies' answers to California Public Records Act requests"

FLOCK_COLUMNS = ("Location Name", "Device Type", "Latitude", "Longitude", "Planning Status")
DEVICES = {"lpr camera": "license plate reader", "video camera (fixed)": "video camera"}
INSTALLED = {"installed"}
PLANNED = {"planning", "install"}
# Far enough around Santa Clara County to catch a swapped or mistyped
# coordinate without turning away a camera just over the county line.
NEAR_COUNTY = (36.8, 37.6, -122.4, -121.1)  # south, north, west, east


class ConvertError(Exception):
    """The list can't be converted, in words for whoever ran the converter."""


def camera_number(location: str) -> str | None:
    """"#044 …" and "F#044 …" give "44". So does "LPR#044a …": the list marks
    a camera's new spot with an "a" when it moves."""
    found = re.search(r"#\s*0*(\d+)", location)
    return found.group(1) if found else None


def install_date(text: str) -> str | None:
    """"Complete - Jul 25, 2024" as "2024-07-25"; nothing if there's no date."""
    found = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", text or "")
    if not found:
        return None
    return datetime.strptime(" ".join(found.groups()), "%b %d %Y").date().isoformat()


def read_flock_list(path: Path, agency: str, received: str) -> tuple[list[dict], Counter]:
    """The cameras in a Flock Safety installation list, and a tally of the
    rows left out and why."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in FLOCK_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ConvertError(
                f"{path.name} isn't laid out like Flock Safety's installation list: it has no "
                f"{', '.join(missing)} column. A list in another layout needs a reader of its own.")
        rows = [{k: (v or "").strip() for k, v in row.items() if k} for row in reader]

    problems, cameras = [], []
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        status = row["Planning Status"].lower()
        device = DEVICES.get(row["Device Type"].lower())
        try:
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
        except ValueError:
            lat = lon = None
        if status not in INSTALLED | PLANNED:
            problems.append(f"line {line}: planning status {row['Planning Status']!r} isn't one this knows")
        elif device is None:
            problems.append(f"line {line}: device type {row['Device Type']!r} isn't one this knows")
        elif lat is None or not (NEAR_COUNTY[0] <= lat <= NEAR_COUNTY[1]
                                 and NEAR_COUNTY[2] <= lon <= NEAR_COUNTY[3]):
            problems.append(f"line {line}: {row['Location Name']!r} has no usable latitude and longitude "
                            f"({row['Latitude']!r}, {row['Longitude']!r})")
        else:
            camera = {"agency": agency, "response_date": received, "location": row["Location Name"],
                      "lat": lat, "lon": lon, "device": device,
                      "status": "installed" if status in INSTALLED else "planned"}
            when = install_date(row.get("Scheduling Status", ""))
            if when and camera["status"] == "installed":
                camera["installed"] = when
            camera["maker"] = "Flock Safety"
            camera["match"] = "coordinates in the records"
            cameras.append(camera)
    if problems:
        raise ConvertError(f"{len(problems)} row{'s' if len(problems) != 1 else ''} of {path.name} "
                           "can't be placed, so nothing was converted:\n  " + "\n  ".join(problems))
    return drop_moved_and_repeated(cameras)


def drop_moved_and_repeated(cameras: list[dict]) -> tuple[list[dict], Counter]:
    left_out = Counter()
    installed_elsewhere = {(c["device"], camera_number(c["location"])) for c in cameras
                           if c["status"] == "installed" and "original" not in c["location"].lower()}
    kept, seen = [], set()
    for camera in cameras:
        number = camera_number(camera["location"])
        if "original" in camera["location"].lower() and (camera["device"], number) in installed_elsewhere:
            left_out["old spot of a camera since moved"] += 1
            continue
        key = (camera["device"], camera["status"], number, camera["lat"], camera["lon"])
        if number and key in seen:
            left_out["listed twice"] += 1
            continue
        seen.add(key)
        kept.append(camera)
    return kept, left_out


def sort_key(camera: dict) -> tuple:
    number = camera_number(camera["location"])
    return (camera["agency"], camera["device"], camera["status"],
            int(number) if number else 1 << 30, camera["location"], camera["lat"], camera["lon"])


def read(path: Path | None = None) -> dict:
    """Everything converted so far: {"responses": [...], "cameras": [...]},
    empty if nothing has been."""
    path = path or PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"responses": [], "cameras": []}
    return {"responses": data.get("responses") or [], "cameras": data.get("cameras") or []}


def write(data: dict, path: Path | None = None) -> None:
    """One camera per line, so a new list's commit shows what changed."""
    path = path or PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["{", f' "about": {json.dumps(ABOUT)},', f' "source": {json.dumps(SOURCE)},', ' "responses": [']
    lines.append(",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in data["responses"]))
    lines += [" ],", ' "cameras": [']
    lines.append(",\n".join("  " + json.dumps(c, ensure_ascii=False) for c in data["cameras"]))
    lines += [" ]", "}"]
    temp = path.with_suffix(".tmp")
    temp.write_text("\n".join(line for line in lines if line) + "\n", encoding="utf-8")
    temp.replace(path)


def add(data: dict, agency: str, received: str, cameras: list[dict]) -> dict:
    """data with this agency's cameras and response replaced by these."""
    readers = [c for c in cameras if c["device"] == "license plate reader"]
    numbers = {camera_number(c["location"]) for c in readers if c["status"] == "installed"}
    planned = [c for c in readers if c["status"] == "planned"]
    response = {"agency": agency, "response_date": received, "list": "Flock Safety installation list",
                "installed": len(readers) - len(planned), "planned": len(planned),
                # planned spots for a camera that's installed now: moves, not new cameras
                "moves": sum(camera_number(c["location"]) in numbers for c in planned),
                "video": sum(c["device"] == "video camera" for c in cameras)}
    responses = [r for r in data["responses"] if r["agency"] != agency] + [response]
    kept = [c for c in data["cameras"] if c["agency"] != agency] + cameras
    return {"responses": sorted(responses, key=lambda r: r["agency"]),
            "cameras": sorted(kept, key=sort_key)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn an agency's camera list into map points.")
    parser.add_argument("file", help="the camera list the agency sent (a CSV)")
    parser.add_argument("--agency", required=True,
                        help='the agency, as PRA Tracker names it: "San José Police Department"')
    parser.add_argument("--received", required=True, metavar="YYYY-MM-DD",
                        help="the day the agency's answer came in, as PRA Tracker has it")
    args = parser.parse_args(argv)
    try:
        received = date.fromisoformat(args.received).isoformat()
    except ValueError:
        print(f"--received should be a date like 2026-11-24, not {args.received!r}.", file=sys.stderr)
        return 1
    path = Path(args.file).expanduser()
    try:
        cameras, left_out = read_flock_list(path, args.agency, received)
    except OSError as err:
        print(f"Can't read {path}: {err.strerror}.", file=sys.stderr)
        return 1
    except ConvertError as err:
        print(err, file=sys.stderr)
        return 1
    write(add(read(), args.agency, received, cameras))
    tally = Counter((c["device"], c["status"]) for c in cameras)
    print(f"{args.agency}, received {received}: {len(cameras)} cameras saved in {PATH.name}.")
    for (device, status), n in sorted(tally.items()):
        print(f"  {n} {device}{'s' if n != 1 else ''}, {status}")
    for why, n in sorted(left_out.items()):
        print(f"  {n} row{'s' if n != 1 else ''} left out: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
