"""Shared test setup.

The tests run against a real District Lookup checkout, found the way the
build finds it (src/district_lookup.py): $DISTRICT_LOOKUP, or a
district-lookup folder beside this one. No test reaches the network:
OpenStreetMap is faked, and any stray request fails the test.
"""

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import district_lookup  # noqa: E402

# Public buildings, as the Census geocoder places them (copied from District
# Lookup's tests/conftest.py, where they were geocoded once by the real service).
POINTS = {
    "san_jose_city_hall": (37.338163163635, -121.886224209159),
    "campbell_city_hall": (37.288195597821, -121.944759236182),
    "stanford_campus": (37.4275, -122.1697),  # unincorporated county land
    "san_francisco_city_hall": (37.778532096981, -122.418308756397),  # outside the county
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("A test tried to reach the network; fake requests.post instead.")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


@pytest.fixture(scope="session")
def dl():
    """District Lookup's layers and lookup, loaded once for the whole run."""
    try:
        root = district_lookup.locate()
    except district_lookup.NotFound as err:
        pytest.exit(str(err), returncode=1)
    return district_lookup.load(root)


@pytest.fixture(scope="session")
def shapes(dl):
    import cameras
    return cameras.district_shapes(dl)


def camera(osm_id, point, **tags):
    lat, lon = POINTS[point]
    return {"id": osm_id, "lat": lat, "lon": lon, **tags}


def largest_piece(geometry):
    return max(getattr(geometry, "geoms", [geometry]), key=lambda g: g.area)
