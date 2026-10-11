"""Contract tests against the REAL iceportal.de. Read-only: never places an order.

Run on the train WiFi:  ICEPORTAL_LIVE=1 uv run pytest -m live
They check that the recorded fixtures still have the shape of the live API, so the mocked tests stay honest.
"""

from __future__ import annotations

import os

import httpx
import pytest

from conftest import load

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("ICEPORTAL_LIVE"), reason="set ICEPORTAL_LIVE=1 (train WiFi) to run"),
]

BASE = "https://iceportal.de"


@pytest.fixture(scope="module")
def live():
    with httpx.Client(base_url=BASE, timeout=15) as c:
        def get(path):
            r = c.get(path)
            r.raise_for_status()
            return r.json()
        yield get


def keys_by_type(products):
    out: dict[str, set[str]] = {}
    for p in products:
        out.setdefault(p["productType"], set()).update(set(p) - {"imageUrl"})
    return out


def test_product_shape_matches_fixture(live):
    live_keys, fixture_keys = keys_by_type(live("/bap/api/products")), keys_by_type(load("products.json"))
    for t, keys in fixture_keys.items():
        assert t in live_keys, f"product type {t} disappeared"
        assert keys <= live_keys[t] | {"optionChoice", "optionChoices", "articleId", "articleIds"}, t
    assert set(live_keys) <= set(fixture_keys), "new product type: server.py does not know how to order it"


def test_every_product_has_an_availability_entry(live):
    ids = {p["ecmId"] for p in live("/bap/api/products")}
    avail = {a["ecmId"]: a for a in live("/bap/api/availabilities")}
    assert ids <= set(avail)
    assert {a["status"] for a in avail.values()} <= {"AVAILABLE", "UNAVAILABLE"}


def test_config_has_coach_list(live):
    c = live("/bap/api/config")["coachList"]["coaches"][0]
    assert {"coachNumber", "hasFirstClass", "hasSecondClass"} <= set(c)


def test_service_status(live):
    assert "bapServiceStatus" in live("/bap/api/bap-service-status")


def test_trip_info_has_what_exit_stations_needs(live):
    trip = live("/api1/rs/tripInfo/trip")["trip"]
    assert "actualNext" in trip["stopInfo"]
    assert all({"evaNr", "name"} <= set(s["station"]) for s in trip["stops"])
