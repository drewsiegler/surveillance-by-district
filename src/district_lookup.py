"""Borrowing District Lookup's maps and its matching, so the two tools always
agree about which district a spot is in.

District Lookup (github.com/drewsiegler/district-lookup) holds the boundary
maps and the rules for reading them: which attribute names each district,
how it's written ("D2—Sup. Betty Duong"), and must_match, which keeps a
council district or trustee area inside the city or school district that drew
it. Rather than copy any of that, the build points at a District Lookup
checkout and imports its own code. The daily build clones the latest one, so a
map fixed there is fixed here the next morning.

Where it looks, in order: the path given on the command line, the
DISTRICT_LOOKUP environment variable, then a district-lookup folder beside
this one (how the two repos sit on the maintainer's computer).
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/drewsiegler/district-lookup"


class NotFound(Exception):
    pass


def locate(path: str | Path | None = None, env: dict = os.environ) -> Path:
    """The District Lookup checkout to use, checked for the files the build needs."""
    candidates = [path, env.get("DISTRICT_LOOKUP"), HERE.parent / "district-lookup"]
    for candidate in filter(None, candidates):
        root = Path(candidate).expanduser().resolve()
        if (root / "src" / "layers.py").exists() and (root / "data" / "layers.json").exists():
            return root
    raise NotFound(
        "Can't find District Lookup, whose maps this builds on. Clone it beside this "
        f"folder (git clone {REPO_URL}), or say where it is: "
        "DISTRICT_LOOKUP=/path/to/district-lookup python src/build.py"
    )


def load(root: Path) -> dict:
    """District Lookup's loaded layers and the functions that read them, plus
    which version of it they came from, for the page to credit."""
    src = str(root / "src")
    if src not in sys.path:
        # At the end, so this repo's own modules are never shadowed by one of
        # District Lookup's that happens to share a name.
        sys.path.append(src)
    layers = importlib.import_module("layers")
    lookup = importlib.import_module("lookup")
    about = importlib.import_module("about")
    if Path(layers.__file__).resolve().parent != root / "src":
        raise NotFound(f"Another copy of District Lookup is already loaded: {layers.__file__}")
    return {
        "layers": layers.load_layers(),
        "lookup_point": lookup.lookup_point,
        "coverage_layer_ids": layers.coverage_layer_ids,
        "version": about.VERSION,
        "commit": commit_of(root),
        "repo_url": REPO_URL,
    }


def commit_of(root: Path) -> str | None:
    """The short commit id of the checkout, if it's a git checkout."""
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10, check=True)
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
