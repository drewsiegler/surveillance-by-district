"""The camera converter's to-do list: ALPR camera lists that agencies sent in
answer to public records requests, waiting to be turned into map points.

    python src/records_todo.py                          what's waiting
    python src/records_todo.py --pra-tracker ~/code/pra-tracker

The requests are tracked in PRA Tracker, which is private: its log is a
campaign plan. So the list stays there, in converter-todo.json, which its
morning run writes whenever a camera list is logged as received. This reads
it from a pra-tracker checkout on the maintainer's computer, where the
records are, and prints it. Nothing from it is written into this repo, the
site or the build's output, and the build never reads it.

Each entry names the agency and the response date, the two things the
converter keeps with every camera it makes from a response. A response is
done once the converter's output, data/record_cameras.json, has a camera with
that agency and date. The converter comes next; until it writes that file,
every response is waiting.

Where it looks for PRA Tracker, in order: --pra-tracker, the PRA_TRACKER
environment variable, then a pra-tracker folder beside this one.
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TODO = "converter-todo.json"
CONVERTED = HERE / "data" / "record_cameras.json"


class NotFound(Exception):
    pass


def locate(path: str | Path | None = None, env: dict = os.environ) -> Path:
    """The PRA Tracker checkout holding the to-do list."""
    for candidate in filter(None, [path, env.get("PRA_TRACKER"), HERE.parent / "pra-tracker"]):
        root = Path(candidate).expanduser().resolve()
        if (root / TODO).exists():
            return root
    raise NotFound(
        f"Can't find PRA Tracker's {TODO}. Pull the pra-tracker repo beside this folder, or say "
        "where it is: python src/records_todo.py --pra-tracker /path/to/pra-tracker")


def read(root: Path) -> list[dict]:
    """The responses on PRA Tracker's list: agency, response_date, file, request, items."""
    data = json.loads((root / TODO).read_text())
    return [r for r in data.get("responses", []) if r.get("agency") and r.get("response_date")]


def converted(path: Path = CONVERTED) -> set[tuple[str, str]]:
    """(agency, response date) for each response the converter has done."""
    if not path.exists():
        return set()
    cameras = json.loads(path.read_text()).get("cameras", [])
    return {(c["agency"], c["response_date"]) for c in cameras if c.get("agency") and c.get("response_date")}


def waiting(responses: list[dict], done: set[tuple[str, str]]) -> list[dict]:
    return [r for r in responses if (r["agency"], r["response_date"]) not in done]


def line(response: dict) -> str:
    day = date.fromisoformat(response["response_date"])
    path = Path(response["file"]).expanduser()
    missing = " (not found at that path)" if path.is_absolute() and not path.exists() else ""
    return f"  {response['agency']}, received {day:%b} {day.day}, {day.year}: {response['file']}{missing}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List the camera lists waiting for the converter.")
    parser.add_argument("--pra-tracker", metavar="PATH",
                        help="PRA Tracker checkout (default: $PRA_TRACKER, then ../pra-tracker)")
    args = parser.parse_args(argv)
    try:
        root = locate(args.pra_tracker)
    except NotFound as err:
        print(err, file=sys.stderr)
        return 1
    responses = read(root)
    todo = waiting(responses, converted())
    if not todo:
        print(f"Nothing to convert: {len(responses)} camera list{'s' if len(responses) != 1 else ''} "
              "received, all done." if responses else "No camera lists received yet.")
        return 0
    print(f"{len(todo)} camera list{'s' if len(todo) != 1 else ''} to convert, from PRA Tracker:")
    for response in todo:
        print(line(response))
    print("Pull pra-tracker first: its morning run updates the list.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
