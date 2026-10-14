# AGENTS.md

Guidance for AI coding agents working in this repo. [README.md](README.md) is the source of truth for what the site shows and how it's built and published.

## What this is

A static website, rebuilt daily, that counts license plate reader cameras from OpenStreetMap by district. It's built off [District Lookup](https://github.com/drewsiegler/district-lookup): the build imports District Lookup's own `layers.py` and `lookup.py` from a checkout (`src/district_lookup.py`) and uses its maps in `data/districts/`. Never copy District Lookup's code or maps into this repo; if something it does needs changing, the change belongs there.

`src/` is flat modules, like District Lookup's. District Lookup's `src/` is appended to `sys.path` at build time, so never give a module here one of its names (`layers`, `lookup`, `about`, `app_paths`, `web`, `main`, `pipeline`, `geocode`, `input_table`, `launcher`) or a standard library name (the page writer is `website.py` because `site` is taken).

- `src/build.py`: the entry point. Fetches cameras, saves them, builds `site/`.
- `src/cameras.py`: the Overpass query, the snapshot file, and counting by district.
- `src/website.py`: the SVG map, the embedded data, and the three output files.
- `src/page.html`: the page template. `__MAP_SVG__` and `__PAGE_DATA__` are filled in by the build.

## Commands

Python 3.10 or newer, in the repo's `.venv`. District Lookup must be checked out beside this folder, or named by `DISTRICT_LOOKUP` or `--district-lookup`.

- Install: `pip install -r requirements-dev.txt`
- Tests: `python -m pytest` (about 4 s, no network)
- Build: `python src/build.py`, or `python src/build.py --offline` to skip OpenStreetMap

Tests and the build must pass before a change counts as done.

## Rules

- **The page loads nothing from anywhere else**: no CDN scripts or styles, web fonts, map tiles, analytics or embeds. `tests/test_website.py` checks. Links people click are fine.
- **No test touches the network.** `tests/conftest.py` makes `requests.get`/`post` fail the test; fake them in the test that needs them.
- **Text from OpenStreetMap is untrusted.** Operator and maker names go into the page only through `website.script_json` (which writes every `<` as `<`) and the script's `esc()`.
- **The runtime stays at `shapely` + `requests`**, the same as District Lookup's. Ask before adding any dependency.
- `data/alpr_cameras.json` is written by the build, one camera per line in OpenStreetMap id order, so each day's commit shows just the cameras that changed. Never hand-edit it.
- A partial Overpass answer (a `remark` reporting an error) is a failed fetch, never a smaller count, and a fetch never replaces the saved cameras with an older copy of the map.
- Every district is listed, zeros included, except neighbors' slivers along the county line (`SLIVER_SQ_MI`).
- Credit OpenStreetMap (ODbL) wherever the camera data goes: the page footer, the CSV's last row, the JSON's `license`.

## Writing

The page, the README and error messages are read by organizers. Use plain language, no jargon, and say what to do next.

## Commits and boundaries

- Commit subjects are a plain-English imperative sentence with no prefix. The body says what changed and why, with numbers where they matter.
- Ask before pushing, before changing the workflow's schedule or permissions, and before touching LICENSE or the README's License section.
