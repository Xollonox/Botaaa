"""Market listing and store logic."""

from __future__ import annotations

import uuid
from typing import Any

import discord

from bot.data.constants import (
    PRICE_RANGES,
    rarity_icon as _ri,
    rarity_rank as _rr,
)
from bot.utils.cards_logic import RARITIES
from bot.utils.timeutil import now_ts
from bot.utils.ui import make_embed

RARITY_CHOICES = RARITIES

PAGE_SIZE = 5

SORT_LABELS = {
    "latest":      "📋 Latest First",
    "name_az":     "🔤 Name: A → Z",
    "rarity_high": "💎 Rarity: High → Low",
    "rarity_low":  "💎 Rarity: Low → High",
    "price_low":   "💰 Price: Low → High",
    "price_high":  "💰 Price: High → Low",
    "arc_az":      "🌍 Arc: A → Z",
    "seller":      "👤 By Seller",
}


def ensure_market_structure(data: dict[str, Any]) -> None:
    """Ensure market structure exists in data."""
    market = data.get("market")
    if not isinstance(market, dict):
        from bot.data.defaults import DEFAULT_DATA
        from copy import deepcopy
        data["market"] = deepcopy(DEFAULT_DATA["market"])
        return
    market.setdefault("listings", {})
    if not isinstance(market.get("listings"), dict):
        market["listings"] = {}
    market.setdefault("settings", {})
    settings = market.get("settings", {})
    if not isinstance(settings, dict):
        market["settings"] = {}
        settings = market["settings"]
    settings.setdefault("enabled", True)
    settings.setdefault("fee_percent", 5)
    settings.setdefault("max_listings_per_user", 10)


def is_market_open(data: dict[str, Any]) -> bool:
    """Return True if the market is open."""
    ensure_market_structure(data)
    return bool(data["market"]["settings"].get("enabled", True))


def create_listing_id() -> str:
    """Generate a unique listing ID."""
    return str(uuid.uuid4())


def listing_id_short(listing_id: str) -> str:
    """Return shortened listing ID."""
    return str(listing_id)[:8]


def resolve_listing_id(market: dict[str, Any], query: str) -> str | None:
    """Find a full listing ID from a partial/full ID query."""
    listings = market.get("listings", {})
    if not isinstance(listings, dict):
        return None
    q = str(query).strip().lower()
    # Exact match
    if q in listings:
        return q
    # Prefix match
    for lid in listings:
        if str(lid).lower().startswith(q):
            return lid
    return None


def seller_payout(price: int, fee_percent: int) -> int:
    """Calculate seller payout after fee."""
    fee = int(price * fee_percent / 100)
    return max(0, price - fee)


def quick_sell_value(data: dict[str, Any], rarity: str) -> int:
    """Return the quick sell value for a given rarity."""
    ensure_market_structure(data)
    qsv = data["market"]["settings"].get("quick_sell_values", {})
    if not isinstance(qsv, dict):
        return 0
    return int(qsv.get(rarity, 0))


def get_store_price(data: dict[str, Any], item_key: str) -> int | None:
    """Get store item price."""
    ensure_market_structure(data)
    store = data["market"].get("store", {})
    if not isinstance(store, dict):
        return None
    items = store.get("items", {})
    if not isinstance(items, dict):
        return None
    item = items.get(str(item_key))
    if not isinstance(item, dict):
        return None
    return int(item.get("price", 0))


def listing_age_text(listed_at: int, now: int | None = None) -> str:
    """Return human-readable listing age."""
    from bot.utils.economy_logic import fmt_duration
    if now is None:
        now = now_ts()
    age = max(0, now - int(listed_at))
    return fmt_duration(age) + " ago"


def paginate_lines(lines: list[str], page: int, page_size: int = 10) -> tuple[list[str], int]:
    """Paginate a list of lines. Returns (page_lines, total_pages)."""
    total = max(1, (len(lines) + page_size - 1) // page_size)
    page = max(1, min(page, total))
    start = (page - 1) * page_size
    return lines[start: start + page_size], total


def market_root(data: dict[str, Any]) -> dict[str, Any]:
    ensure_market_structure(data)
    m = data.setdefault("market", {})
    m.setdefault("listings", {})
    m.setdefault("featured", None)
    m.setdefault("special_offer", None)
    return m


def get_active_listings(data: dict[str, Any]) -> list[dict[str, Any]]:
    m = market_root(data)
    listings = m.get("listings", {})
    if not isinstance(listings, dict):
        return []
    now = now_ts()
    return [
        v for v in listings.values()
        if isinstance(v, dict)
        and not v.get("sold")
        and (v.get("expires_at", now + 1) or now + 1) > now
    ]


def apply_sort(listings: list[dict[str, Any]], sort_key: str) -> list[dict[str, Any]]:
    if sort_key == "name_az":
        return sorted(listings, key=lambda l: str(l.get("card_name", "")).lower())
    if sort_key == "rarity_high":
        return sorted(listings, key=lambda l: _rr(str(l.get("rarity", ""))), reverse=True)
    if sort_key == "rarity_low":
        return sorted(listings, key=lambda l: _rr(str(l.get("rarity", ""))))
    if sort_key == "price_low":
        return sorted(listings, key=lambda l: int(l.get("price", 0)))
    if sort_key == "price_high":
        return sorted(listings, key=lambda l: int(l.get("price", 0)), reverse=True)
    if sort_key == "arc_az":
        return sorted(listings, key=lambda l: str(l.get("arc", "")).lower())
    if sort_key == "seller":
        return sorted(listings, key=lambda l: str(l.get("seller_name", "")).lower())
    return sorted(listings, key=lambda l: int(l.get("listed_at", 0)), reverse=True)


def time_left_text(expires_at: int) -> str:
    remaining = max(0, int(expires_at) - now_ts())
    if remaining <= 0:
        return "Expired"
    h, m = divmod(remaining // 60, 60)
    if h > 24:
        return f"{h // 24}d {h % 24}h left"
    return f"{h}h {m}m left"


def price_range_for_settings(settings: dict[str, Any], rarity: str) -> tuple[int, int]:
    pb = settings.get("price_band", {}) if isinstance(settings, dict) else {}
    row = pb.get(rarity, {}) if isinstance(pb, dict) else {}
    if isinstance(row, dict):
        try:
            lo = int(row.get("min", 0))
            hi = int(row.get("max", 0))
            if lo <= hi and hi > 0:
                return lo, hi
        except (TypeError, ValueError):
            pass
    return PRICE_RANGES.get(rarity, (0, 999_999_999))


def fee_percent_for_settings(settings: dict[str, Any]) -> int:
    try:
        return int(settings.get("fee_percent", 5))
    except (TypeError, ValueError):
        return 5


def build_market_embed(
    data: dict[str, Any],
    page: int,
    sort_key: str,
    selected_id: str | None,
) -> tuple[discord.Embed, str | None]:
    m = market_root(data)
    featured = m.get("featured")
    special  = m.get("special_offer")
    all_listings    = get_active_listings(data)
    sorted_listings = apply_sort(all_listings, sort_key)

    blocks: list[str] = []
    image_url: str | None = None

    if isinstance(featured, dict) and int(featured.get("expires_at", 0)) > now_ts():
        rarity = str(featured.get("rarity", ""))
        if not rarity:
            cards_cat = data.get("cards", {})
            card_def_f = cards_cat.get(str(featured.get("card_name", "")), {}) if isinstance(cards_cat, dict) else {}
            rarity = str(card_def_f.get("rarity", "")) if isinstance(card_def_f, dict) else ""
        icon       = _ri(rarity)
        rarity_tag = f"  [{rarity}]" if rarity else ""
        price      = int(featured.get("price", 0))
        tl         = time_left_text(int(featured.get("expires_at", 0)))
        stock      = featured.get("stock", -1)
        stock_disp = "∞" if int(stock) == -1 else str(stock)
        arc_disp   = str(featured.get("arc", "—")).strip() or "—"
        blocks.append(
            f"╭─ ⭐ Featured Card\n"
            f"│ {icon} {featured.get('card_name', '?')}{rarity_tag}\n"
            f"│ 💰 {price:,} coins\n"
            f"│ 📦 Stock: {stock_disp}\n"
            f"│ 🌍 Arc: {arc_disp}\n"
            f"│ ⏳ {tl}\n"
            "╰────────────────"
        )
        image_url = str(featured.get("image_url", "")).strip() or None

    if isinstance(special, dict) and int(special.get("expires_at", 0)) > now_ts():
        rarity = str(special.get("rarity", ""))
        if not rarity:
            cards_cat = data.get("cards", {})
            card_def_s = cards_cat.get(str(special.get("card_name", "")), {}) if isinstance(cards_cat, dict) else {}
            rarity = str(card_def_s.get("rarity", "")) if isinstance(card_def_s, dict) else ""
        icon       = _ri(rarity)
        rarity_tag = f"  [{rarity}]" if rarity else ""
        price      = int(special.get("price", 0))
        tl         = time_left_text(int(special.get("expires_at", 0)))
        stock      = special.get("stock", -1)
        stock_disp = "∞" if int(stock) == -1 else str(stock)
        arc_disp   = str(special.get("arc", "—")).strip() or "—"
        blocks.append(
            f"╭─ 🎁 Special Offer\n"
            f"│ ✨ LIMITED  •  {icon} {special.get('card_name', '?')}{rarity_tag}\n"
            f"│ 💰 {price:,} coins  •  📦 {stock_disp}  •  🕐 {tl}\n"
            f"│ 🌍 Arc: {arc_disp}\n"
            "╰────────────────"
        )
        if not image_url:
            image_url = str(special.get("image_url", "")).strip() or None

    total_pages = max(1, (len(sorted_listings) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_items = sorted_listings[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    if not page_items:
        blocks.append("╭─ 🔥 Latest Listings\n│ No listings yet.\n╰────────────────")
    else:
        lines = []
        for i, listing in enumerate(page_items, start=page * PAGE_SIZE + 1):
            lid    = str(listing.get("id", ""))
            icon   = _ri(str(listing.get("rarity", "")))
            name   = str(listing.get("card_name", "?"))
            price  = int(listing.get("price", 0))
            seller = str(listing.get("seller_name", "?"))
            marker = "▶ " if lid == selected_id else f"{i}. "
            lines.append(f"│ {marker}{name}  {icon}  {price:,} coins  @{seller}")
        blocks.append("╭─ 🔥 Latest Listings\n" + "\n".join(lines) + "\n╰────────────────")

    if selected_id:
        listings_map = market_root(data).get("listings", {})
        sel = listings_map.get(selected_id) if isinstance(listings_map, dict) else None
        if isinstance(sel, dict):
            rarity = str(sel.get("rarity", ""))
            blocks.append(
                f"╭─ 🃏 {sel.get('card_name', '?')}\n"
                f"│ {_ri(rarity)} Rarity: {rarity}\n"
                f"│ 💰 Price: {int(sel.get('price', 0)):,} coins\n"
                f"│ 👤 Seller: @{sel.get('seller_name', '?')}\n"
                f"│ 🌍 Arc: {sel.get('arc', '—')}\n"
                "╰────────────────"
            )
            sel_img = str(sel.get("image_url", "")).strip()
            if sel_img:
                image_url = sel_img

    embed = make_embed(
        None, "LOOKISM HXCC • MARKET", "\n\n".join(blocks),
        color=0x2B2D31,
        footer=f"Market  •  {SORT_LABELS.get(sort_key, sort_key)}  •  Page {page + 1}/{total_pages}",
        image_url=image_url,
    )
    return embed, image_url
