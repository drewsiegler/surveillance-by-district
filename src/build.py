"""Builds the website.

    python src/build.py                 fetch fresh cameras, then build site/
    python src/build.py --offline       build from data/alpr_cameras.json as it is
    python src/build.py --district-lookup ~/code/district-lookup

The daily GitHub Actions run does the first. If OpenStreetMap can't be
reached, it still builds, from the last snapshot, so a District Lookup map fix
goes out even on a day Overpass is down; the page always shows the date its
camera data is from.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cameras
import district_lookup
import website

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Surveillance by District website.")
    parser.add_argument("--offline", action="store_true",
                        help="don't ask OpenStreetMap; use data/alpr_cameras.json as it is")
    parser.add_argument("--district-lookup", metavar="PATH",
                        help="District Lookup checkout to use (default: $DISTRICT_LOOKUP, "
                             "then ../district-lookup)")
    parser.add_argument("--out", default=str(ROOT / "site"), help="where to write the site")
    args = parser.parse_args(argv)

    try:
        root = district_lookup.locate(args.district_lookup)
    except district_lookup.NotFound as err:
        print(err, file=sys.stderr)
        return 1
    print(f"Loading District Lookup's maps from {root}…")
    dl = district_lookup.load(root)

    saved = cameras.read()
    snapshot = saved
    if not args.offline:
        box = cameras.bounding_box(dl)
        print(f"Asking OpenStreetMap for license plate readers in {box}…")
        try:
            snapshot = cameras.fetch(box, not_before=(saved or {}).get("as_of"))
            cameras.write(snapshot)
        except cameras.RefreshError as err:
            print(f"{err} Building from the saved copy instead.", file=sys.stderr)
    if snapshot is None:
        print("No camera data: data/alpr_cameras.json is missing and OpenStreetMap couldn't be "
              "reached.", file=sys.stderr)
        return 1

    shapes = cameras.district_shapes(dl)
    result = cameras.report(dl, snapshot, shapes)
    written = website.write_site(dl, result, shapes, Path(args.out))
    print(f"{result['total']} cameras in the county ({result['flock']} Flock), as of "
          f"{snapshot['as_of']}, counted across {len(result['maps'])} maps from District Lookup "
          f"{dl['version']}.")
    for path in written:
        print(f"  {path} ({path.stat().st_size / 1024:,.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
