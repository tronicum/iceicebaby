"""Behaviour of the MCP tools against the recorded fixtures (no network)."""

from __future__ import annotations

import re

from conftest import FakePortal, call, call_err, load

# Products from the recorded menu (ecmIds are stable ids from the real API).
LATTE = 10579328  # OPTION_ARTICLE: pick a size
LATTE_S, LATTE_M, LATTE_L = 10579330, 10579332, 10579334
CAPPUCCINO = 10579274  # OPTION_ARTICLE
CAPPUCCINO_L = 10579280
BUTTERCROISSANT = 10563514  # ARTICLE_WITH_EXTRAS, wraps article 10563512
BUTTERCROISSANT_ARTICLE = 10563512
BAUERNBROETCHEN = 13500140  # ARTICLE_WITH_EXTRAS, wraps article 13500138 (1.60 EUR)
BIONELLA = 13149662  # plain ARTICLE and also an allowed extra (1.20 EUR)
HONIG = 10508128
COLA_ZERO = 10579384  # ARTICLE (4.20 EUR)
CHILI_SIN_CARNE = 13568732
THAI_CURRY = 13409740  # sold out in the fixture
POPCORN_MENU = 14043862  # MENU with one option group (hot drink), sold out in the fixture
MILCH = 13723432  # OPTION_ARTICLE with extras

ISO_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def live_ids() -> set[int]:
    prods = {p["ecmId"]: p for p in load("products.json")}
    avail = {a["ecmId"]: a for a in load("availabilities.json")}
    return {
        i for i, p in prods.items()
        if p["category"] and avail[i]["status"] == "AVAILABLE" and avail[i]["visible"]
    }


def titles(menu: dict) -> set[str]:
    return {i["title"] for items in menu["categories"].values() for i in items}


# ------------------------------------------------------------------- menu

async def test_list_menu_returns_only_live_items(mcp, portal):
    menu = await call(mcp, "list_menu")
    ids = {i["ecm_id"] for items in menu["categories"].values() for i in items}
    assert ids == live_ids()
    assert menu["count"] == len(ids)
    assert all(i["orderable"] for items in menu["categories"].values() for i in items)
    assert "Rotes Thai Curry mit Shiitake-Pilzen" not in titles(menu)  # sold out


async def test_list_menu_can_include_sold_out(mcp, portal):
    menu = await call(mcp, "list_menu", only_available=False)
    assert "Rotes Thai Curry mit Shiitake-Pilzen" in titles(menu)
    assert menu["count"] > len(live_ids())


async def test_list_menu_hides_variants_but_shows_option_parents(mcp, portal):
    names = titles(await call(mcp, "list_menu"))
    assert "Latte Macchiato" in names  # parent
    assert "Latte Macchiato Größe M" not in names  # variant: reached through get_product


async def test_list_menu_category_filter_is_case_insensitive(mcp, portal):
    menu = await call(mcp, "list_menu", category="heiß")
    assert list(menu["categories"]) == ["Heißgetränke"]


async def test_menu_follows_availability_changes(mcp, portal):
    portal.set_available(THAI_CURRY, True)
    assert "Rotes Thai Curry mit Shiitake-Pilzen" in titles(await call(mcp, "list_menu"))
    portal.set_available(COLA_ZERO, False)
    assert "Coca-Cola Zero" not in titles(await call(mcp, "list_menu"))


async def test_search_menu_matches_all_words(mcp, portal):
    hits = await call(mcp, "search_menu", query="vegan chili")
    assert [h["ecm_id"] for h in hits] == [CHILI_SIN_CARNE]
    assert await call(mcp, "search_menu", query="vegan chili xyz") == []


async def test_search_menu_hides_sold_out_unless_asked(mcp, portal):
    assert await call(mcp, "search_menu", query="thai curry") == []
    hits = await call(mcp, "search_menu", query="thai curry", only_available=False)
    assert [h["ecm_id"] for h in hits] == [THAI_CURRY]


async def test_get_product_option_article_lists_sizes_with_prices(mcp, portal):
    p = await call(mcp, "get_product", ecm_id=LATTE)
    assert p["type"] == "OPTION_ARTICLE"
    sizes = {c["ecm_id"]: c["price_eur"] for c in p["options"]["choices"]}
    assert sizes == {LATTE_S: 4.2, LATTE_M: 4.6, LATTE_L: 5.0}


async def test_get_product_with_extras(mcp, portal):
    p = await call(mcp, "get_product", ecm_id=BUTTERCROISSANT)
    assert p["article_ecm_id"] == BUTTERCROISSANT_ARTICLE
    assert BIONELLA in {e["ecm_id"] for e in p["extras"]}


async def test_get_product_menu_lists_option_groups(mcp, portal):
    p = await call(mcp, "get_product", ecm_id=POPCORN_MENU)
    assert p["type"] == "MENU"
    assert len(p["option_choices"]) == 1
    assert LATTE_M in {c["ecm_id"] for c in p["option_choices"][0]["choices"]}


async def test_get_product_unknown_id(mcp, portal):
    assert "Unknown ecm_id" in await call_err(mcp, "get_product", ecm_id=1)


async def test_service_status_is_passed_through(mcp, portal):
    portal.service_status = {"bapServiceStatus": "PAUSED"}
    assert await call(mcp, "get_service_status") == {"bapServiceStatus": "PAUSED"}


async def test_not_on_train_wifi_gives_helpful_error(mcp, portal):
    portal.down = True
    assert "train WiFi" in await call_err(mcp, "list_menu")


# --------------------------------------------------------------- location

async def test_exit_stations_are_only_upcoming_stops(mcp, portal):
    assert await call(mcp, "get_exit_stations") == ["Halle(Saale)Hbf", "Erfurt Hbf", "Frankfurt(Main)Hbf"]


async def test_exit_stations_shrink_as_train_moves(mcp, portal):
    portal.trip["trip"]["stopInfo"]["actualNext"] = "8000105"  # Frankfurt: last stop
    assert await call(mcp, "get_exit_stations") == ["Frankfurt(Main)Hbf"]


async def test_set_location_accepts_valid_and_canonicalises_station(mcp, portal):
    loc = await call(mcp, "set_location", coach=12, seat=25, exit_station="frankfurt(main)hbf")
    assert loc == {"coach": 12, "seat": 25, "exitStation": "Frankfurt(Main)Hbf"}


async def test_set_location_rejects_unknown_coach(mcp, portal):
    assert "not found" in await call_err(mcp, "set_location", coach=99, seat=1, exit_station="Erfurt Hbf")


async def test_set_location_rejects_second_class_only_coach(mcp, portal):
    coaches = {c["coachNumber"]: c for c in portal.config["coachList"]["coaches"]}
    second_only = next(n for n, c in coaches.items() if not c["hasFirstClass"])
    assert "second class" in await call_err(mcp, "set_location", coach=second_only, seat=1, exit_station="Erfurt Hbf")


async def test_set_location_rejects_passed_station(mcp, portal):
    err = await call_err(mcp, "set_location", coach=12, seat=25, exit_station="Berlin Hbf")
    assert "Exit station must be one of" in err


# ------------------------------------------------------------------- cart

async def test_cart_totals_for_sized_drinks(mcp, portal):
    cart = await call(mcp, "add_to_cart", ecm_id=LATTE, option_ids=[LATTE_M], quantity=2)
    assert cart["total_eur"] == 9.2
    assert cart["items"][0]["options"] == ["Latte Macchiato Größe M"]


async def test_cart_totals_for_article_with_extras_include_base_article(mcp, portal):
    cart = await call(mcp, "add_to_cart", ecm_id=BAUERNBROETCHEN, extras={BIONELLA: 1})
    assert cart["total_eur"] == 2.8  # roll 1.60 + Bionella 1.20


async def test_cart_sums_several_items_and_supports_remove_and_clear(mcp, portal):
    await call(mcp, "add_to_cart", ecm_id=BIONELLA)
    await call(mcp, "add_to_cart", ecm_id=COLA_ZERO)
    cart = await call(mcp, "view_cart")
    assert cart["total_eur"] == 5.4
    cart = await call(mcp, "remove_from_cart", index=0)
    assert [i["title"] for i in cart["items"]] == ["Coca-Cola Zero"]
    assert "cleared" in await call(mcp, "clear_cart")
    assert (await call(mcp, "view_cart"))["items"] == []


async def test_remove_from_cart_rejects_bad_index(mcp, portal):
    assert "No such cart index" in await call_err(mcp, "remove_from_cart", index=3)


async def test_add_rejects_unknown_and_sold_out_products(mcp, portal):
    assert "Unknown ecm_id" in await call_err(mcp, "add_to_cart", ecm_id=1)
    assert "not available" in await call_err(mcp, "add_to_cart", ecm_id=THAI_CURRY)


async def test_add_rejects_bad_quantity(mcp, portal):
    assert "quantity" in await call_err(mcp, "add_to_cart", ecm_id=COLA_ZERO, quantity=0)


async def test_option_article_needs_exactly_one_valid_option(mcp, portal):
    assert "exactly one option" in await call_err(mcp, "add_to_cart", ecm_id=LATTE)
    assert "exactly one option" in await call_err(mcp, "add_to_cart", ecm_id=LATTE, option_ids=[LATTE_S, LATTE_M])
    assert "exactly one option" in await call_err(mcp, "add_to_cart", ecm_id=LATTE, option_ids=[COLA_ZERO])


async def test_option_must_itself_be_available(mcp, portal):
    portal.set_available(LATTE_L, False)
    assert "not available" in await call_err(mcp, "add_to_cart", ecm_id=LATTE, option_ids=[LATTE_L])


async def test_plain_article_takes_no_options_or_extras(mcp, portal):
    assert "takes no options" in await call_err(mcp, "add_to_cart", ecm_id=COLA_ZERO, option_ids=[LATTE_S])
    assert "not allowed" in await call_err(mcp, "add_to_cart", ecm_id=COLA_ZERO, extras={BIONELLA: 1})


async def test_extras_must_be_in_the_products_extra_list(mcp, portal):
    assert "not allowed" in await call_err(mcp, "add_to_cart", ecm_id=BUTTERCROISSANT, extras={COLA_ZERO: 1})


async def test_menu_needs_one_option_per_group_in_order(mcp, portal):
    portal.set_available(POPCORN_MENU)  # synthetic: real menu structure, made orderable
    assert "one option per group" in await call_err(mcp, "add_to_cart", ecm_id=POPCORN_MENU)
    assert "one option per group" in await call_err(mcp, "add_to_cart", ecm_id=POPCORN_MENU, option_ids=[COLA_ZERO])
    cart = await call(mcp, "add_to_cart", ecm_id=POPCORN_MENU, option_ids=[LATTE_M])
    assert cart["total_eur"] == 7.9


# ------------------------------------------------------------------ order

async def ready(mcp, *items):
    await call(mcp, "set_location", coach=12, seat=25, exit_station="Frankfurt(Main)Hbf")
    for args in items:
        await call(mcp, "add_to_cart", **args)


async def test_place_order_needs_items_and_location(mcp, portal):
    assert "Cart is empty" in await call_err(mcp, "place_order", confirm=True)
    await call(mcp, "add_to_cart", ecm_id=COLA_ZERO)
    assert "set_location" in await call_err(mcp, "place_order", confirm=True)
    assert portal.posted_orders == []


async def test_place_order_without_confirm_only_previews(mcp, portal):
    await ready(mcp, dict(ecm_id=COLA_ZERO))
    res = await call(mcp, "place_order")
    assert res["preview"]["total_eur"] == 4.2
    assert "confirm=True" in res["note"]
    assert portal.posted_orders == []
    assert len((await call(mcp, "view_cart"))["items"]) == 1  # cart untouched


async def test_place_order_request_matches_what_the_real_portal_accepted(mcp, portal):
    """Golden test: the exact body of the cappuccino-only order that the crew ACCEPTED on 2026-10-11."""
    await ready(mcp, dict(ecm_id=CAPPUCCINO, option_ids=[CAPPUCCINO_L]))
    res = await call(mcp, "place_order", confirm=True)
    assert res["order"]["status"]["statusType"] == "OPEN"
    (body,) = portal.posted_orders
    assert body["guest"] == {"seat": 25, "coach": 12, "exitStation": "Frankfurt(Main)Hbf"}
    assert ISO_Z.match(body["orderedAt"])
    assert body["products"] == [{
        "ecmId": CAPPUCCINO,
        "productType": "OPTION_ARTICLE",
        "orderedOption": {"productType": "ARTICLE", "ecmId": CAPPUCCINO_L},
        "orderedExtras": [],
    }]


async def test_order_body_for_every_product_type(mcp, portal):
    portal.set_available(POPCORN_MENU)
    await ready(
        mcp,
        dict(ecm_id=BIONELLA),
        dict(ecm_id=BUTTERCROISSANT, extras={BIONELLA: 1, HONIG: 2}),
        dict(ecm_id=POPCORN_MENU, option_ids=[LATTE_M]),
    )
    await call(mcp, "place_order", confirm=True)
    plain, extras, menu = portal.posted_orders[0]["products"]
    assert plain == {"ecmId": BIONELLA, "productType": "ARTICLE"}
    assert extras == {
        "ecmId": BUTTERCROISSANT,
        "productType": "ARTICLE_WITH_EXTRAS",
        "orderedArticle": {"ecmId": BUTTERCROISSANT_ARTICLE, "productType": "ARTICLE"},
        "orderedExtras": [
            {"productType": "EXTRA", "ecmId": BIONELLA, "amount": 1},
            {"productType": "EXTRA", "ecmId": HONIG, "amount": 2},
        ],
    }
    assert menu == {
        "ecmId": POPCORN_MENU,
        "productType": "MENU",
        "orderedOptions": [{"productType": "ARTICLE", "ecmId": LATTE_M}],
        "orderedExtras": [],
    }


async def test_quantity_becomes_repeated_entries(mcp, portal):
    await ready(mcp, dict(ecm_id=COLA_ZERO, quantity=3))
    await call(mcp, "place_order", confirm=True)
    assert portal.posted_orders[0]["products"] == [{"ecmId": COLA_ZERO, "productType": "ARTICLE"}] * 3


async def test_successful_order_clears_cart_and_remembers_id(mcp, portal):
    await ready(mcp, dict(ecm_id=COLA_ZERO))
    await call(mcp, "place_order", confirm=True)
    assert (await call(mcp, "view_cart"))["items"] == []
    status = await call(mcp, "get_order_status")  # defaults to the last order
    assert status["statusType"] == "ACCEPTED"
    assert ("GET", f"/bap/api/orders/{portal.order_id}/status") in portal.requests


async def test_get_order_status_by_explicit_id(mcp, portal):
    portal.order_status = {"statusType": "DECLINED"}
    assert (await call(mcp, "get_order_status", order_id=portal.order_id))["statusType"] == "DECLINED"


async def test_get_order_status_without_any_order(mcp, portal):
    assert "No order id" in await call_err(mcp, "get_order_status")


async def test_item_sold_out_after_adding_blocks_the_order(mcp, portal):
    await ready(mcp, dict(ecm_id=COLA_ZERO))
    portal.set_available(COLA_ZERO, False)
    assert "No longer available" in await call_err(mcp, "place_order", confirm=True)
    assert portal.posted_orders == []


async def test_rejected_order_keeps_the_cart(mcp, portal):
    await ready(mcp, dict(ecm_id=COLA_ZERO))
    portal.order_post_status = 400
    assert "Order rejected: HTTP 400" in await call_err(mcp, "place_order", confirm=True)
    assert len((await call(mcp, "view_cart"))["items"]) == 1


async def test_connection_drop_while_ordering_warns_not_to_blindly_retry(mcp, portal):
    await ready(mcp, dict(ecm_id=COLA_ZERO))
    portal.post_down = True
    err = await call_err(mcp, "place_order", confirm=True)
    assert "may NOT have been placed" in err
    assert len((await call(mcp, "view_cart"))["items"]) == 1
