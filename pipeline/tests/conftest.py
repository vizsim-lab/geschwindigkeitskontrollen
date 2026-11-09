from pathlib import Path

import pytest

from kontrollen import geocode, osm

FIXTURES = Path(__file__).parent / "fixtures"
CRS = "EPSG:25833"
CFG = {
    "stadtgrenze": {"name": "Berlin", "admin_level": ["4"]},
    "bbox": [13.38, 52.50, 13.44, 52.56],
}


@pytest.fixture(scope="session")
def auszug():
    return osm.lies(FIXTURES / "mini.osm", bbox=CFG["bbox"], admin_level=("4", "9", "10"))


@pytest.fixture(scope="session")
def netz(auszug):
    return geocode.Netz.aus_auszug(auszug, CRS)


@pytest.fixture(scope="session")
def gebiete(auszug):
    return geocode.Gebiete.aus_auszug(auszug, CRS, CFG, bezirk_ebene="9")
