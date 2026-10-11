# iceicebaby 🚄☕

**EN** · [DE](#deutsch)

An MCP server (Python, [FastMCP](https://gofastmcp.com)) that lets an AI assistant order food and drinks
from the ICE board restaurant to your seat ("Bestellen am Platz", https://iceportal.de/speisekarte).
It talks to the same `/bap/api/*` endpoints as the ICE Portal web app.

## Requirements

- **You must be on the train's WiFi (WIFIonICE).** `iceportal.de` only resolves on board; anywhere else
  every tool fails with "Are you on the train WiFi?".
- You must be on an ICE that offers ordering at your seat (check `get_service_status` → `ACTIVE`),
  and sit in a **first-class** coach.
- [uv](https://docs.astral.sh/uv/) and an MCP client such as Claude Code.

## Install

```sh
git clone https://github.com/tronicum/iceicebaby && cd iceicebaby
claude mcp add iceicebaby -- uv --directory "$(pwd)" run server.py
```

The server speaks MCP over **stdio** (no port). Any other MCP client can launch `uv run server.py` the same way.

## Tools

| Tool | What it does |
|---|---|
| `list_menu` | Live menu by category (only what is orderable right now) |
| `search_menu` | Search by words, e.g. `vegan`, `bier`, `kaffee` |
| `get_product` | Price, additives, and the sizes/extras/menu choices of an item |
| `get_service_status` | Is ordering currently active on this train? |
| `get_exit_stations` | Upcoming stops (valid exit stations) |
| `set_location` | Coach, seat and exit station (validated) |
| `add_to_cart` / `view_cart` / `remove_from_cart` / `clear_cart` | Local cart with EUR total |
| `place_order` | Sends the order. **Only with `confirm=True`**, otherwise a preview |
| `get_order_status` | `OPEN` (crew is checking) → `DECLINED` / `ACCEPTED` |

The menu is the *live* menu: `/bap/api/products` joined with `/bap/api/availabilities`.
Sold-out items are hidden unless you pass `only_available=False`.

## How ordering works

1. Browse: `list_menu`, `search_menu`.
2. `get_product` for items with choices: `OPTION_ARTICLE` (pick one size), `ARTICLE_WITH_EXTRAS`
   (optional extras), `MENU` (one pick per choice group).
3. `add_to_cart`, then `view_cart`.
4. `set_location` with coach, seat and exit station.
5. `place_order` shows a preview; after you agree, `place_order(confirm=True)`.
6. The order starts as `OPEN`: the crew checks whether they can do it and answers shortly.
   Poll with `get_order_status`.

> ⚠️ `place_order(confirm=True)` really orders and you pay at your seat. The assistant should always show
> the cart and total and wait for your explicit OK first.

## Examples

Things you can tell your assistant:

- *"What's on the menu?"* → `list_menu`
- *"Anything vegan and warm?"* → `search_menu("vegan")`
- *"What sizes does the cappuccino come in?"* → `get_product(10579274)`
- *"A buttercroissant with Bionella and a large cappuccino to coach 12, seat 25, I get off in Frankfurt."*

The last one results in these calls:

```python
set_location(coach=12, seat=25, exit_station="Frankfurt(Main)Hbf")
add_to_cart(ecm_id=10563514, extras={13149662: 1})       # Buttercroissant + Bionella
add_to_cart(ecm_id=10579274, option_ids=[10579280])      # Cappuccino, size L
place_order()                                            # preview, 9.50 EUR
place_order(confirm=True)                                # after your OK
get_order_status()                                       # OPEN -> ...
```

Quantity and extras: `add_to_cart(ecm_id=..., quantity=2)`, `extras={extra_ecm_id: amount}`.

## Tested

Verified against the live ICE Portal on an ICE (2026-10-11): menu, cart, location validation, order submission
and status polling all work. The first real order (croissant + Bionella + cappuccino) reached the crew and came
back as `OPEN` ("Wir prüfen Ihre Bestellanfrage") and then `DECLINED`:

> Leider können wir die Bestellung nicht annehmen, da es derzeit nicht möglich ist, zum Platz zu bestellen.
> Für Bestellungen sprechen Sie uns an oder besuchen Sie das Bordbistro.

So the server works, but **ordering at the seat can be paused by the crew at any time**, even while
`get_service_status` says `ACTIVE`. A decline is a normal outcome, not an error: go to the Bordbistro.
A second order with only a cappuccino was then `ACCEPTED` within about 80 seconds
("Ihre Bestellung wurde angenommen und wird bald zu Ihnen gebracht."), so the full flow works end to end.
Why the first one was declined is unknown (possibly the croissant with extra, possibly just crew workload).

## Notes

- Cart and location live in memory of the running server process; restarting it clears them.
- Unofficial, not affiliated with Deutsche Bahn. The API is undocumented and can change at any time.

---

## Deutsch

Ein MCP-Server (Python, [FastMCP](https://gofastmcp.com)), mit dem ein KI-Assistent Speisen und Getränke
aus dem Bordrestaurant im ICE an den Sitzplatz bestellen kann („Bestellen am Platz“,
https://iceportal.de/speisekarte). Er nutzt dieselben `/bap/api/*`-Endpunkte wie das ICE Portal.

### Voraussetzungen

- **Du musst im WLAN des Zuges sein (WIFIonICE).** `iceportal.de` ist nur an Bord erreichbar; sonst
  schlagen alle Tools fehl („Are you on the train WiFi?“).
- Der Zug muss Bestellen am Platz anbieten (`get_service_status` → `ACTIVE`), und du sitzt in einem
  Wagen mit **1. Klasse**.
- [uv](https://docs.astral.sh/uv/) und ein MCP-Client wie Claude Code.

### Installation

```sh
git clone https://github.com/tronicum/iceicebaby && cd iceicebaby
claude mcp add iceicebaby -- uv --directory "$(pwd)" run server.py
```

Der Server spricht MCP über **stdio** (kein Port). Andere MCP-Clients starten einfach `uv run server.py`.

### Tools

| Tool | Funktion |
|---|---|
| `list_menu` | Aktuelle Speisekarte nach Kategorie (nur was gerade bestellbar ist) |
| `search_menu` | Suche, z. B. `vegan`, `bier`, `kaffee` |
| `get_product` | Preis, Zusatzstoffe, Größen/Extras/Menü-Auswahl eines Artikels |
| `get_service_status` | Ist Bestellen im Zug gerade aktiv? |
| `get_exit_stations` | Kommende Halte (gültige Ausstiegsbahnhöfe) |
| `set_location` | Wagen, Sitzplatz und Ausstieg (wird geprüft) |
| `add_to_cart` / `view_cart` / `remove_from_cart` / `clear_cart` | Lokaler Warenkorb mit Summe in EUR |
| `place_order` | Sendet die Bestellung. **Nur mit `confirm=True`**, sonst nur Vorschau |
| `get_order_status` | `OPEN` (Team prüft) → `DECLINED` / `ACCEPTED` |

Die Karte ist die *Live-Speisekarte*: `/bap/api/products` verknüpft mit `/bap/api/availabilities`.
Ausverkauftes wird ausgeblendet, außer du übergibst `only_available=False`.

### Ablauf einer Bestellung

1. Stöbern: `list_menu`, `search_menu`.
2. `get_product` bei Artikeln mit Auswahl: `OPTION_ARTICLE` (genau eine Größe), `ARTICLE_WITH_EXTRAS`
   (optionale Extras), `MENU` (je Auswahlgruppe eine Wahl).
3. `add_to_cart`, dann `view_cart`.
4. `set_location` mit Wagen, Platz und Ausstiegsbahnhof.
5. `place_order` zeigt eine Vorschau; nach deinem OK `place_order(confirm=True)`.
6. Die Bestellung startet als `OPEN`: Das Team prüft, ob es sie umsetzen kann, und meldet sich kurz darauf.
   Status per `get_order_status` abfragen.

> ⚠️ `place_order(confirm=True)` bestellt wirklich, bezahlt wird am Platz. Der Assistent sollte vorher
> immer Warenkorb und Summe zeigen und dein ausdrückliches OK abwarten.

### Beispiele

Das kannst du deinem Assistenten sagen:

- *„Was gibt es auf der Karte?“* → `list_menu`
- *„Gibt es etwas Veganes, Warmes?“* → `search_menu("vegan")`
- *„In welchen Größen gibt es den Cappuccino?“* → `get_product(10579274)`
- *„Ein Buttercroissant mit Bionella und einen großen Cappuccino in Wagen 12, Platz 25, ich steige in Frankfurt aus.“*

Der letzte Satz führt zu diesen Aufrufen:

```python
set_location(coach=12, seat=25, exit_station="Frankfurt(Main)Hbf")
add_to_cart(ecm_id=10563514, extras={13149662: 1})       # Buttercroissant + Bionella
add_to_cart(ecm_id=10579274, option_ids=[10579280])      # Cappuccino, Größe L
place_order()                                            # Vorschau, 9,50 EUR
place_order(confirm=True)                                # nach deinem OK
get_order_status()                                       # OPEN -> ...
```

Menge und Extras: `add_to_cart(ecm_id=..., quantity=2)`, `extras={extra_ecm_id: Anzahl}`.

### Getestet

Gegen das echte ICE Portal im ICE geprüft (11.10.2026): Speisekarte, Warenkorb, Standortprüfung,
Bestellung und Statusabfrage funktionieren. Die erste echte Bestellung (Croissant + Bionella + Cappuccino)
kam beim Team an, war zuerst `OPEN` („Wir prüfen Ihre Bestellanfrage“) und wurde dann `DECLINED`:

> Leider können wir die Bestellung nicht annehmen, da es derzeit nicht möglich ist, zum Platz zu bestellen.
> Für Bestellungen sprechen Sie uns an oder besuchen Sie das Bordbistro.

Der Server funktioniert also, aber **Bestellen am Platz kann vom Team jederzeit pausiert werden**, auch wenn
`get_service_status` `ACTIVE` meldet. Eine Ablehnung ist ein normales Ergebnis, kein Fehler: dann ins Bordbistro.
Eine zweite Bestellung nur mit Cappuccino wurde nach ca. 80 Sekunden `ACCEPTED`
(„Ihre Bestellung wurde angenommen und wird bald zu Ihnen gebracht.“), der gesamte Ablauf funktioniert also.
Warum die erste abgelehnt wurde, ist unklar (evtl. das Croissant mit Extra, evtl. nur Auslastung des Teams).

### Hinweise

- Warenkorb und Standort liegen im Speicher des laufenden Serverprozesses; ein Neustart leert sie.
- Inoffiziell, nicht mit der Deutschen Bahn verbunden. Die API ist undokumentiert und kann sich jederzeit ändern.

## License

AGPL-3.0-or-later, see [LICENSE](LICENSE).
