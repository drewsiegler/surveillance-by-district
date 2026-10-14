"""Writes the website: one self-contained page, plus the same numbers as a
CSV and a JSON file to download.

The page carries everything it needs, map included, so it loads no scripts,
fonts, map tiles or analytics from anywhere else: visitors' browsers talk only
to wherever the site is hosted. The district map is drawn here, at build
time, as plain SVG: each district clipped to the county, simplified to about
the width of a street, and placed with a flat projection that's true to
within a fraction of a percent across one county.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import cameras

PAGE_TEMPLATE = Path(__file__).resolve().parent / "page.html"
WIDTH = 1000  # SVG units across the county; one unit is about 90 m in Santa Clara County
SIMPLIFY_DEGREES = 0.0006  # about 60 m, less than one SVG unit


class Projection:
    """Longitude and latitude to SVG x and y, north up, with longitude scaled
    by the cosine of the middle latitude so shapes keep their proportions."""

    def __init__(self, west: float, south: float, east: float, north: float):
        self.west, self.north = west, north
        self.squash = math.cos(math.radians((south + north) / 2))
        self.scale = WIDTH / ((east - west) * self.squash)
        self.height = math.ceil((north - south) * self.scale)

    def point(self, lon: float, lat: float) -> tuple[int, int]:
        return (round((lon - self.west) * self.squash * self.scale),
                round((self.north - lat) * self.scale))


def path_data(geometry, projection: Projection) -> str:
    """An SVG path for a polygon or multipolygon: each ring as "M x y x y … Z",
    skipping points that round onto the one before."""
    rings = []
    for polygon in getattr(geometry, "geoms", [geometry]):
        if polygon.geom_type != "Polygon":
            continue  # a stray line or point left over from clipping
        for ring in [polygon.exterior, *polygon.interiors]:
            points = []
            for lon, lat in ring.coords:
                point = projection.point(lon, lat)
                if not points or point != points[-1]:
                    points.append(point)
            if len(points) >= 4:
                rings.append("M" + " ".join(f"{x} {y}" for x, y in points[:-1]) + "Z")
    return "".join(rings)


def map_svg(dl: dict, result: dict, shapes: dict) -> str:
    """The county with every map's districts as a group of paths (the page's
    CSS shows only the group marked "on", and its script shades it by count),
    and a dot per camera.
    Each path's data-i is the index of its row in that map's table."""
    county = cameras.covered_area(dl)
    outline = county if county is not None else None
    west, south, east, north = (outline.bounds if outline is not None
                                else _bounds([g for s in shapes.values() for g in s.values()]))
    projection = Projection(west, south, east, north)
    groups = []
    for found in result["maps"]:
        by_key = shapes.get(found["id"], {})
        paths = []
        for i, row in enumerate(found["rows"]):
            shape = by_key.get((row["within"], None if row["elsewhere"] else row["district"]))
            if shape is None:
                continue
            d = path_data(shape.simplify(SIMPLIFY_DEGREES, preserve_topology=True), projection)
            if d:
                paths.append(f'<path class="district" data-i="{i}" d="{d}"/>')
        groups.append(f'<g class="layer" data-map="{found["id"]}">{"".join(paths)}</g>')
    county_path = (path_data(outline.simplify(SIMPLIFY_DEGREES), projection)
                   if outline is not None else "")
    dots = "".join(
        '<circle cx="{}" cy="{}" r="2.6"/>'.format(*projection.point(c["lon"], c["lat"]))
        for c in result["cameras"])
    return (
        f'<svg id="map" viewBox="0 0 {WIDTH} {projection.height}" role="img" '
        f'aria-label="Map of the county shaded by how many license plate readers each district has">'
        f'<path class="county" d="{county_path}"/>'
        f'{"".join(groups)}'
        f'<path class="county-line" d="{county_path}"/>'
        f'<g class="cams">{dots}</g></svg>'
    )


def _bounds(geometries) -> tuple[float, float, float, float]:
    boxes = [g.bounds for g in geometries]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def page_data(dl: dict, result: dict, built: datetime) -> dict:
    """What the page's script reads: the tables, without the camera list (the
    map already has a dot for each), and where everything came from."""
    return {
        "as_of": result["as_of"],
        "built": built.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": result["total"],
        "flock": result["flock"],
        "maps": result["maps"],
        "district_lookup": {"version": dl["version"], "commit": dl["commit"],
                            "url": dl["repo_url"]},
    }


def json_data(dl: dict, result: dict, built: datetime) -> dict:
    """The download: the tables plus every counted camera, with the license
    OpenStreetMap's data comes under."""
    return {
        **page_data(dl, result, built),
        "source": cameras.SOURCE,
        "license": "Camera locations © OpenStreetMap contributors, Open Database License (ODbL 1.0): "
                   "https://opendatacommons.org/licenses/odbl/",
        "cameras": result["cameras"],
    }


def script_json(data: dict) -> str:
    """JSON that's safe inside a <script> element. Names and tags come from
    whoever edited OpenStreetMap, so every "<" is written as \\u003c, which
    JSON.parse turns back into "<" but the HTML parser never sees as a tag."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def write_site(dl: dict, result: dict, shapes: dict, out: Path,
               built: datetime | None = None) -> list[Path]:
    built = built or datetime.now(timezone.utc)
    out.mkdir(parents=True, exist_ok=True)
    page = PAGE_TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("__MAP_SVG__", map_svg(dl, result, shapes))
    page = page.replace("__PAGE_DATA__", script_json(page_data(dl, result, built)))
    written = {
        "index.html": page,
        "license_plate_readers_by_district.csv": cameras.csv_text(result),
        "license_plate_readers_by_district.json":
            json.dumps(json_data(dl, result, built), ensure_ascii=False, indent=1) + "\n",
    }
    paths = []
    for name, text in written.items():
        path = out / name
        # utf-8-sig for the CSV so Excel shows the em dashes and accents correctly
        path.write_text(text, encoding="utf-8-sig" if name.endswith(".csv") else "utf-8")
        paths.append(path)
    return paths
