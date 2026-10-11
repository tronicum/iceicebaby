"""MCP server for ordering from the ICE Portal board restaurant ("Bestellen am Platz").

Only works while connected to the on-board WiFi (WIFIonICE), where
https://iceportal.de is reachable. The menu is the *live* menu: the static product
catalogue (`/bap/api/products`) is joined with `/bap/api/availabilities`, so only what
can actually be ordered right now is shown by default.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

BASE_URL = os.environ.get("ICEPORTAL_URL", "https://iceportal.de").rstrip("/")

mcp = FastMCP(
    "iceicebaby",
    instructions=(
        "Order food and drinks from the ICE board restaurant to your seat. "
        "Workflow: list_menu / search_menu -> get_product (for options/extras) -> "
        "add_to_cart -> view_cart -> set_location (coach, seat, exit station) -> "
        "place_order. Always show the user the cart and total and get an explicit "
        "OK before calling place_order with confirm=True; ordering costs real money."
    ),
)

_client = httpx.AsyncClient(base_url=BASE_URL, timeout=15, headers={"User-Agent": "iceicebaby"})

# In-memory session state (one MCP server process == one passenger).
_cart: list[dict[str, Any]] = []
_location: dict[str, Any] = {}
_last_order_id: str | None = None


# --------------------------------------------------------------------------- API

async def _get(path: str) -> Any:
    try:
        r = await _client.get(path)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise ToolError(f"ICE Portal request {path} failed ({e}). Are you on the train WiFi?") from e


async def _catalog() -> dict[int, dict[str, Any]]:
    """All products by ecmId, each with a `live` flag from the availabilities endpoint."""
    products = await _get("/bap/api/products")
    avail = {a["ecmId"]: a for a in await _get("/bap/api/availabilities")}
    out = {}
    for p in products:
        a = avail.get(p["ecmId"])
        p["live"] = bool(a and a["status"] == "AVAILABLE" and a["visible"])
        out[p["ecmId"]] = p
    return out


def _eur(p: dict[str, Any]) -> float | None:
    return next((x["price"] for x in p.get("prices", []) if x["currency"] == "EUR"), None)


def _summary(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "ecm_id": p["ecmId"],
        "title": p["title"],
        "description": p.get("description"),
        "category": p["category"],
        "type": p["productType"],
        "price_eur": _eur(p),
        "orderable": p["live"],
    }


def _is_leaf(p: dict[str, Any]) -> bool:
    # Variants (sizes, toys, ...) have no category; they are reached via their
    # OPTION_ARTICLE parent through get_product, so the menu only shows the parent.
    return bool(p["category"])


# ------------------------------------------------------------------------- menu

@mcp.tool
async def list_menu(category: str | None = None, only_available: bool = True) -> dict[str, Any]:
    """List the board restaurant menu, grouped by category.

    By default only the *live* menu is returned (items that are orderable right now).
    Set only_available=False to include sold-out / hidden items. Items of type
    OPTION_ARTICLE are choose-a-variant parents (e.g. "Latte Macchiato" -> size, price
    depends on the variant); use get_product to see the variants.
    """
    cat = await _catalog()
    items = [p for p in cat.values() if (p["live"] or not only_available)]
    if category:
        items = [p for p in items if category.lower() in p["category"].lower()]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for p in items:
        if _is_leaf(p):
            grouped.setdefault(p["category"], []).append(_summary(p))
    return {"categories": grouped, "count": sum(map(len, grouped.values()))}


@mcp.tool
async def search_menu(query: str, only_available: bool = True) -> list[dict[str, Any]]:
    """Search the menu by words in title/description/category (e.g. "kaffee", "vegan", "bier")."""
    words = query.lower().split()
    res = []
    for p in (await _catalog()).values():
        if (only_available and not p["live"]) or not _is_leaf(p):
            continue
        hay = " ".join(str(p.get(k) or "") for k in ("title", "description", "category")).lower()
        if all(w in hay for w in words):
            res.append(_summary(p))
    return res


@mcp.tool
async def get_product(ecm_id: int) -> dict[str, Any]:
    """Full details of one product: price, allergens/additives, and what must/can be chosen.

    - ARTICLE: plain item, nothing to choose.
    - OPTION_ARTICLE: pick exactly one of `options` (e.g. a size) when adding to cart.
    - ARTICLE_WITH_EXTRAS: optionally pick `extras` (each with an amount).
    - MENU: pick one option per entry of `option_choices`.
    """
    cat = await _catalog()
    p = cat.get(ecm_id)
    if not p:
        raise ToolError(f"Unknown ecm_id {ecm_id}")

    def refs(ids: list[int]) -> list[dict[str, Any]]:
        return [_summary(cat[i]) for i in ids if i in cat]

    out = _summary(p)
    out["additives"] = [f'{d["shortDescription"]}: {d["description"]}' for d in p.get("declarations", [])]
    if p["productType"] == "OPTION_ARTICLE":
        oc = p.get("optionChoice", {})
        out["options"] = {"prompt": oc.get("textBeforeChoice"), "choices": refs(oc.get("articleIds", []))}
    if p["productType"] == "MENU":
        out["contains"] = refs(p.get("articleIds", []))
        out["option_choices"] = [
            {"prompt": oc.get("textBeforeChoice"), "choices": refs(oc.get("articleIds", []))}
            for oc in p.get("optionChoices", [])
        ]
    if p["productType"] == "ARTICLE_WITH_EXTRAS":
        out["article_ecm_id"] = p["articleId"]
    if p.get("extraChoice", {}).get("articleIds"):
        out["extras"] = refs(p["extraChoice"]["articleIds"])
    return out


@mcp.tool
async def get_service_status() -> dict[str, Any]:
    """Whether ordering is currently possible on this train (ACTIVE / PAUSED / ...)."""
    return await _get("/bap/api/bap-service-status")


# --------------------------------------------------------------------- location

@mcp.tool
async def get_exit_stations() -> list[str]:
    """Upcoming stops of this train. The order's exit station must be one of these (by name)."""
    trip = (await _get("/api1/rs/tripInfo/trip"))["trip"]
    nxt = trip["stopInfo"]["actualNext"]
    names, seen_next = [], False
    for s in trip["stops"]:
        seen_next = seen_next or s["station"]["evaNr"] == nxt
        if seen_next:
            names.append(s["station"]["name"])
    return names


@mcp.tool
async def set_location(coach: int, seat: int, exit_station: str) -> dict[str, Any]:
    """Tell the crew where to bring the order: coach number, seat number, and the station
    where the passenger gets off (pick from get_exit_stations)."""
    config = await _get("/bap/api/config")
    coaches = {c["coachNumber"]: c for c in config["coachList"]["coaches"]}
    if coach not in coaches:
        raise ToolError(f"Coach {coach} not found. Valid coaches: {sorted(coaches)}")
    if not coaches[coach]["hasFirstClass"]:
        raise ToolError(f"Coach {coach} is second class only; ordering at the seat is for 1st class.")
    stops = await get_exit_stations()
    match = next((s for s in stops if s.lower() == exit_station.lower()), None)
    if not match:
        raise ToolError(f"Exit station must be one of {stops}")
    _location.update(coach=coach, seat=seat, exitStation=match)
    return dict(_location)


# ------------------------------------------------------------------------- cart

def _cart_view(cat: dict[int, dict[str, Any]]) -> dict[str, Any]:
    lines, total = [], 0.0
    for i, it in enumerate(_cart):
        p = cat.get(it["ecm_id"])
        base = cat.get(p["articleId"], p) if p and p["productType"] == "ARTICLE_WITH_EXTRAS" else p
        price = (_eur(base) if base else None) or 0.0
        # priced options (e.g. sized coffee for an OPTION_ARTICLE) are summed from their articles
        price += sum((_eur(cat[o]) or 0.0) for o in it["option_ids"] if o in cat) if not price else 0.0
        extras = sum((_eur(cat[e["ecm_id"]]) or 0.0) * e["amount"] for e in it["extras"] if e["ecm_id"] in cat)
        line = (price + extras) * it["quantity"]
        total += line
        lines.append({
            "index": i,
            "title": p["title"] if p else it["ecm_id"],
            "options": [cat[o]["title"] for o in it["option_ids"] if o in cat],
            "extras": [f'{e["amount"]}x {cat[e["ecm_id"]]["title"]}' for e in it["extras"] if e["ecm_id"] in cat],
            "quantity": it["quantity"],
            "line_total_eur": round(line, 2),
        })
    return {"items": lines, "total_eur": round(total, 2), "location": dict(_location) or None}


@mcp.tool
async def add_to_cart(
    ecm_id: int,
    quantity: int = 1,
    option_ids: list[int] | None = None,
    extras: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Add a product to the (local) cart. Nothing is sent to the restaurant yet.

    option_ids: chosen variants — exactly one for OPTION_ARTICLE, one per choice group for MENU.
    extras: {extra_ecm_id: amount} for ARTICLE_WITH_EXTRAS / extras of options.
    Use get_product first to see what is required.
    """
    cat = await _catalog()
    p = cat.get(ecm_id)
    if not p:
        raise ToolError(f"Unknown ecm_id {ecm_id}")
    if not p["live"]:
        raise ToolError(f'"{p["title"]}" is not available right now.')
    if quantity < 1:
        raise ToolError("quantity must be >= 1")
    option_ids = option_ids or []
    extras = extras or {}

    t = p["productType"]
    if t == "OPTION_ARTICLE":
        allowed = p["optionChoice"]["articleIds"]
        if len(option_ids) != 1 or option_ids[0] not in allowed:
            raise ToolError(f"Choose exactly one option out of {allowed}")
        if not cat[option_ids[0]]["live"]:
            raise ToolError("That option is not available right now.")
    elif t == "MENU":
        groups = p.get("optionChoices", [])
        if len(option_ids) != len(groups) or any(o not in g["articleIds"] for o, g in zip(option_ids, groups)):
            raise ToolError(
                "Provide one option per group, in order: " + str([g["articleIds"] for g in groups])
            )
    elif option_ids:
        raise ToolError(f"{t} takes no options")

    allowed_extras = set(p.get("extraChoice", {}).get("articleIds", []))
    bad = [e for e in extras if e not in allowed_extras]
    if bad:
        raise ToolError(f"Extras {bad} not allowed; allowed: {sorted(allowed_extras)}")

    _cart.append({
        "ecm_id": ecm_id,
        "quantity": quantity,
        "option_ids": option_ids,
        "extras": [{"ecm_id": e, "amount": a} for e, a in extras.items() if a > 0],
    })
    return _cart_view(cat)


@mcp.tool
async def view_cart() -> dict[str, Any]:
    """Show the cart with line totals, the total in EUR and the delivery location."""
    return _cart_view(await _catalog())


@mcp.tool
async def remove_from_cart(index: int) -> dict[str, Any]:
    """Remove the cart line with the given index (see view_cart)."""
    if not 0 <= index < len(_cart):
        raise ToolError("No such cart index")
    _cart.pop(index)
    return _cart_view(await _catalog())


@mcp.tool
async def clear_cart() -> str:
    """Empty the cart."""
    _cart.clear()
    return "Cart cleared."


# ------------------------------------------------------------------------ order

def _order_products(cat: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Cart -> request `products`, mirroring the ICE Portal web app (one entry per piece)."""
    out = []
    for it in _cart:
        p = cat[it["ecm_id"]]
        extras = [{"productType": "EXTRA", "ecmId": e["ecm_id"], "amount": e["amount"]} for e in it["extras"]]
        opts = [{"productType": "ARTICLE", "ecmId": o} for o in it["option_ids"]]
        t = p["productType"]
        if t == "ARTICLE":
            entry = {"ecmId": p["ecmId"], "productType": "ARTICLE"}
        elif t == "OPTION_ARTICLE":
            entry = {"ecmId": p["ecmId"], "productType": t, "orderedOption": opts[0], "orderedExtras": extras}
        elif t == "MENU":
            entry = {"ecmId": p["ecmId"], "productType": t, "orderedOptions": opts, "orderedExtras": extras}
        else:  # ARTICLE_WITH_EXTRAS
            entry = {
                "ecmId": p["ecmId"],
                "productType": t,
                "orderedArticle": {"ecmId": p["articleId"], "productType": "ARTICLE"},
                "orderedExtras": extras,
            }
        out.extend([entry] * it["quantity"])
    return out


@mcp.tool
async def place_order(confirm: bool = False) -> dict[str, Any]:
    """Send the cart to the board restaurant. THIS SPENDS REAL MONEY (paid at the seat).

    Only call with confirm=True after the user has seen the cart, total and location and
    explicitly agreed. With confirm=False this just returns a preview.
    """
    global _last_order_id
    cat = await _catalog()
    if not _cart:
        raise ToolError("Cart is empty.")
    if not _location:
        raise ToolError("Set coach, seat and exit station first (set_location).")
    unavailable = [cat[i["ecm_id"]]["title"] for i in _cart if not cat[i["ecm_id"]]["live"]]
    if unavailable:
        raise ToolError(f"No longer available, remove from cart: {unavailable}")
    preview = _cart_view(cat)
    if not confirm:
        return {"preview": preview, "note": "Not sent. Call again with confirm=True after user approval."}

    body = {
        "orderedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "guest": {"seat": _location["seat"], "coach": _location["coach"], "exitStation": _location["exitStation"]},
        "products": _order_products(cat),
    }
    try:
        r = await _client.post("/bap/api/orders", json=body)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ToolError(f"Order rejected: HTTP {e.response.status_code} {e.response.text[:300]}") from e
    except httpx.HTTPError as e:
        raise ToolError(f"Order may NOT have been placed ({e}). Check get_order_status before retrying.") from e
    res = r.json()
    _last_order_id = res.get("id")
    _cart.clear()
    return {"order": res, "ordered": preview}


@mcp.tool
async def get_order_status(order_id: str | None = None) -> Any:
    """Status of an order (defaults to the last one placed in this session)."""
    oid = order_id or _last_order_id
    if not oid:
        raise ToolError("No order id known.")
    return await _get(f"/bap/api/orders/{oid}/status")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
