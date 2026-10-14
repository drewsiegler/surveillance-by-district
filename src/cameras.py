"""License plate reader cameras: getting them from OpenStreetMap, and counting
them by district.

The camera locations come from OpenStreetMap, where volunteers, many of them
through DeFlock (deflock.me), map automated license plate readers (ALPRs) and
tag them surveillance:type=ALPR. A count here is a floor, not a census: a
camera is on the map only once someone has spotted it and added it.

The Overpass API, a free public service for reading OpenStreetMap data, is
asked for every ALPR inside a rectangle around the area District Lookup's
maps cover. The answer is kept in data/alpr_cameras.json, which the daily
build commits, so the repo's history doubles as a record of when cameras
were mapped.

Each camera is placed with District Lookup's own lookup_point, the same
matching an address gets there, so its must_match rules hold here too: a
camera on unincorporated land counts toward no council district, and one in
San José never counts toward a Campbell district where the two cities' maps
disagree about a border.

OpenStreetMap data is © OpenStreetMap contributors under the Open Database
License (ODbL 1.0), so the page, the CSV and the JSON all say so.
"""

import csv
import io
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

import requests
from shapely import union_all

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "alpr_cameras.json"
SOURCE = "OpenStreetMap, via the Overpass API"
LICENSE = "ODbL-1.0"
ATTRIBUTION = "© OpenStreetMap contributors"
# Tried in order. The main public Overpass server is free, needs no account,
# and answers this query in about five seconds. Mirrors were tried and left
# out: in October 2026 one timed out and another's copy of the map was
# months out of date. overpass-api.de refuses requests that don't say what's
# asking (406), hence the User-Agent.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
]
USER_AGENT = "Surveillance by District (+https://github.com/drewsiegler/surveillance-by-district)"
# Under load the server turns queries away (504, or 429 when it's rationing)
# for a few seconds at a time, so a refresh waits and asks again before giving up.
BUSY = {429, 503, 504}
RETRY_PAUSES = (5, 15)
QUERY = '[out:json][timeout:60];node["surveillance:type"="ALPR"]({south},{west},{north},{east});out body;'
# Lifecycle prefixes OpenStreetMap uses for something that has come down but
# is still mapped, like demolished:man_made=surveillance.
GONE_PREFIXES = ("demolished:", "removed:", "razed:", "destroyed:", "was:")

CSV_COLUMNS = {
    "map": "Map",
    "within": "Within",
    "district": "District",
    "cameras": "ALPR Cameras Mapped",
    "flock": "Flock Safety",
    "other_makers": "Other Makers",
    "operators": "Operators Named",
}
# Cameras in the county but in none of a map's areas: unincorporated land on
# the city map, or places a unified district covers on the high school map.
ELSEWHERE = "Elsewhere in the county"
# The Census maps carry neighboring districts that reach into the county only
# in slivers along its edge, a hundredth of a square mile or so. Listing those
# with zero cameras would just be noise. The smallest real one, Luther Burbank
# School District, is about a quarter of a square mile.
SLIVER_SQ_MI = 0.05


class RefreshError(Exception):
    """Fresh camera data couldn't be had, in words for whoever ran the build."""


# --- Getting the cameras ----------------------------------------------------------

def bounding_box(dl: dict) -> tuple[float, float, float, float]:
    """(south, west, north, east) around the area the maps cover, rounded
    outward to about 100 m: the coverage layers if there are any (the county),
    otherwise every layer."""
    layers = dl["layers"]
    coverage = set(dl["coverage_layer_ids"](layers))
    bounds = [geometry.bounds for layer in layers if not coverage or layer["id"] in coverage
              for geometry in layer["geometries"]]
    if not bounds:
        raise RefreshError("District Lookup has no maps loaded, so there's no area to count in.")
    west, south = min(b[0] for b in bounds), min(b[1] for b in bounds)
    east, north = max(b[2] for b in bounds), max(b[3] for b in bounds)
    down, up = (lambda x: math.floor(x * 1000) / 1000), (lambda x: math.ceil(x * 1000) / 1000)
    return down(south), down(west), up(north), up(east)


def parse(answer: dict, box: tuple[float, float, float, float]) -> dict:
    """An Overpass answer as a snapshot: only what the site uses, sorted by
    OpenStreetMap id so each day's commit shows just the cameras that changed."""
    remark = answer.get("remark") or ""
    if "error" in remark.lower():
        # Overpass reports a timeout or overload as a remark beside whatever
        # it found before giving up. A partial list would undercount, so it
        # counts as a failure.
        raise ValueError(remark)
    if "elements" not in answer:
        raise ValueError("no elements in the answer")
    cameras = []
    for element in answer["elements"]:
        tags = element.get("tags") or {}
        if element.get("type") != "node" or any(key.startswith(GONE_PREFIXES) for key in tags):
            continue
        camera = {"id": element["id"], "lat": element["lat"], "lon": element["lon"]}
        maker = tags.get("manufacturer") or tags.get("brand")
        if maker:
            camera["manufacturer"] = maker
        if tags.get("operator"):
            camera["operator"] = tags["operator"]
        cameras.append(camera)
    cameras.sort(key=lambda camera: camera["id"])
    return {
        "as_of": (answer.get("osm3s") or {}).get("timestamp_osm_base"),
        "bbox": list(box),
        "source": SOURCE,
        "license": LICENSE,
        "cameras": cameras,
    }


def fetch(box: tuple[float, float, float, float], not_before: str | None = None,
          timeout: float = 75) -> dict:
    """Every ALPR mapped inside the box, fresh from OpenStreetMap. A server
    whose copy of the map is older than not_before is passed over: mirrors can
    run weeks behind, and a refresh should never go backward."""
    south, west, north, east = box
    query = QUERY.format(south=south, west=west, north=north, east=east)
    for url in OVERPASS_URLS:
        for pause in (*RETRY_PAUSES, None):
            try:
                response = requests.post(url, data={"data": query}, timeout=timeout,
                                         headers={"User-Agent": USER_AGENT})
                if response.status_code in BUSY and pause is not None:
                    time.sleep(pause)
                    continue
                response.raise_for_status()
                snapshot = parse(response.json(), box)
            except (requests.RequestException, ValueError):
                break  # down, offline or a broken answer; try the next server
            if not_before and (snapshot["as_of"] or "") < not_before:
                break
            return snapshot
    raise RefreshError("Couldn't get fresh camera data from OpenStreetMap: its servers are busy "
                       "or unreachable. Try again in a few minutes.")


def write(snapshot: dict, path: Path | None = None) -> None:
    """One camera per line, in id order, so a day's diff is readable."""
    path = path or SNAPSHOT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {key: value for key, value in snapshot.items() if key != "cameras"}
    lines = ["{"] + [f" {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},"
                     for key, value in head.items()]
    lines.append(' "cameras": [')
    rows = [" " + json.dumps(camera, ensure_ascii=False) for camera in snapshot["cameras"]]
    if rows:
        lines.append(",\n".join(rows))
    lines += [" ]", "}"]
    temp = path.with_suffix(".tmp")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.replace(path)  # never leaves a half-written file behind


def read(path: Path | None = None) -> dict | None:
    path = path or SNAPSHOT_PATH
    try:
        with open(path, encoding="utf-8") as f:
            snapshot = json.load(f)
        return snapshot if isinstance(snapshot.get("cameras"), list) else None
    except (OSError, ValueError, AttributeError):
        return None


# --- Counting them -----------------------------------------------------------------

def is_flock(camera: dict) -> bool:
    """Made by Flock Safety, going by its maker, or by its operator when no
    maker is mapped. Without the second, about 50 of Saratoga's cameras, mapped
    with Flock Safety as the operator and no maker, wouldn't count as Flock."""
    maker = camera.get("manufacturer") or camera.get("operator") or ""
    return maker.lower().startswith("flock")


def square_miles(geometry) -> float:
    """Rough area of a lat/lon shape, plenty to tell a district from a sliver."""
    if geometry.is_empty:
        return 0.0
    return geometry.area * 69.1 ** 2 * math.cos(math.radians(geometry.centroid.y))


def natural_key(text: str | None) -> list:
    """"TA2" before "TA10". Splitting on digits puts text at even positions and
    numbers at odd ones, so two keys never compare a number with text."""
    parts = re.split(r"(\d+)", text or "")
    return [int(part) if i % 2 else part.lower() for i, part in enumerate(parts)]


def describe(counts: Counter) -> str:
    return ", ".join(f"{name} {n}" for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def covered_area(dl: dict):
    """The whole area the maps cover (the county), or None if no layer says."""
    coverage = dl["coverage_layer_ids"](dl["layers"])
    if not coverage:
        return None
    return union_all([geometry for layer in dl["layers"] if layer["id"] in coverage
                      for geometry in layer["geometries"]])


def district_shapes(dl: dict) -> dict[str, dict[tuple, object]]:
    """{layer id: {(within, district): shape}} for every district worth
    listing: the pieces of each district merged and clipped to the county,
    with neighbors' slivers along the county line left out."""
    covered = covered_area(dl)
    shapes = {}
    for layer in dl["layers"]:
        pieces = {}
        for within, district, geometry in zip(layer["scope"], layer["display"], layer["geometries"]):
            if district:
                inside = geometry if covered is None else covered.intersection(geometry)
                pieces.setdefault((within, district), []).append(inside)
        merged = {key: union_all(parts) for key, parts in pieces.items()}
        shapes[layer["id"]] = {key: shape for key, shape in merged.items()
                               if square_miles(shape) >= SLIVER_SQ_MI}
    return shapes


def report(dl: dict, snapshot: dict, shapes: dict | None = None) -> dict:
    """How many mapped cameras fall in each district of each map. Every
    district is listed, including those with none, since zero is part of the
    picture; only neighbors' slivers along the county line are left out,
    unless a camera is in one. Cameras outside the area the maps cover (the
    query's rectangle reaches past the county line) aren't counted anywhere."""
    layers, lookup_point = dl["layers"], dl["lookup_point"]
    coverage = dl["coverage_layer_ids"](layers)
    shapes = district_shapes(dl) if shapes is None else shapes
    tallies = {layer["id"]: {key: [] for key in shapes.get(layer["id"], {})} for layer in layers}

    counted = []
    for camera in snapshot.get("cameras", []):
        districts = lookup_point(layers, camera["lat"], camera["lon"])
        if coverage and not any(districts.get(layer_id) for layer_id in coverage):
            continue
        counted.append(camera)
        for layer in layers:
            district = districts.get(layer["id"])
            if district:
                within = districts.get(layer["must_match"]["layer"]) if layer["must_match"] else None
            elif layer["must_match"]:
                continue  # unincorporated land, an at-large city, a district without trustee areas
            else:
                within = None
            tallies[layer["id"]].setdefault((within, district), []).append(camera)

    maps = []
    for layer in layers:
        rows = []
        keys = sorted(tallies[layer["id"]], key=lambda key: (
            key[1] is None, natural_key(key[0]), natural_key(key[1])))
        for within, district in keys:
            found = tallies[layer["id"]][(within, district)]
            others = Counter(c["manufacturer"] for c in found
                             if c.get("manufacturer") and not is_flock(c))
            rows.append({
                "within": within,
                "district": district or ELSEWHERE,
                "elsewhere": district is None,
                "cameras": len(found),
                "flock": sum(map(is_flock, found)),
                "other_makers": describe(others),
                "operators": describe(Counter(c["operator"] for c in found if c.get("operator"))),
            })
        maps.append({"id": layer["id"], "label": layer["label"],
                     "scoped": bool(layer["must_match"]), "rows": rows})

    return {
        "as_of": snapshot.get("as_of"),
        "total": len(counted),
        "flock": sum(map(is_flock, counted)),
        "attribution": ATTRIBUTION,
        "license": snapshot.get("license", LICENSE),
        "maps": maps,
        "cameras": counted,
    }


def csv_text(result: dict) -> str:
    """The whole report, every map and district, as one CSV. The last row says
    where the data came from, as OpenStreetMap's license asks."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for found in result["maps"]:
        for row in found["rows"]:
            writer.writerow({"map": found["label"],
                             **{key: value for key, value in row.items() if key in CSV_COLUMNS}})
    as_of = (result["as_of"] or "unknown")[:10]
    writer.writerow({"map": (
        f"Source: OpenStreetMap, {ATTRIBUTION}, under the Open Database License (ODbL 1.0); "
        f"camera locations as of {as_of}. Counts include only cameras volunteers have mapped."
    )})
    return buffer.getvalue()
