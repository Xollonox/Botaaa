"""Default JSON structure and helper utilities."""

from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any


def _load_card_catalog() -> dict[str, Any]:
    """Load card catalog from cards.json file (not embedded in code for token efficiency)."""
    json_path = Path(__file__).resolve().parent / "cards.json"
    if not json_path.exists():
        return {}
    try:
        with json_path.open("r", encoding="utf-8") as f:
            cards = json.load(f)
        return cards if isinstance(cards, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _sync_catalog_cards(existing_cards: Any, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh known catalog cards while preserving runtime-only admin cards."""
    if not isinstance(existing_cards, dict) or not existing_cards:
        return deepcopy(catalog if catalog is not None else _load_card_catalog())

    catalog_cards = catalog if catalog is not None else _load_card_catalog()
    if not catalog_cards:
        return existing_cards

    synced = deepcopy(existing_cards)
    synced.pop("Changyong ji", None)
    for card_name, card_def in catalog_cards.items():
        if isinstance(card_def, dict):
            synced[card_name] = deepcopy(card_def)
    return synced


def _normalize_card_stats(card: dict[str, Any]) -> None:
    stats = card.get("stats")
    if not isinstance(stats, dict):
        return
    normalized = {
        "strength": int(stats.get("strength", 0) or 0),
        "speed": int(stats.get("speed", 0) or 0),
        "endurance": int(stats.get("endurance", 0) or 0),
        "technique": int(stats.get("technique", 0) or 0),
        "iq": int(stats.get("iq", 0) or 0),
        "battle_iq": int(stats.get("battle_iq", stats.get("biq", 0)) or 0),
    }
    card["stats"] = normalized


DEFAULT_PACK_DEFINITIONS = {
    "newbie_pack": {
        "key": "newbie_pack",
        "name": "Newbie Pack",
        "price": 750,
        "enabled": True,
        "rates": {"Common": 80, "Rare": 20},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "amateur_pack": {
        "key": "amateur_pack",
        "name": "Amateur Pack",
        "price": 3000,
        "enabled": True,
        "rates": {"Common": 50, "Rare": 45, "Epic": 5},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "basic_pack": {
        "key": "basic_pack",
        "name": "Basic Pack",
        "price": 5000,
        "enabled": True,
        "rates": {"Common": 30, "Rare": 60, "Epic": 10},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "intermediate_pack": {
        "key": "intermediate_pack",
        "name": "Intermediate Pack",
        "price": 10000,
        "enabled": True,
        "rates": {"Rare": 40, "Epic": 50, "Legendary": 10},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "experienced_pack": {
        "key": "experienced_pack",
        "name": "Experienced Pack",
        "price": 25000,
        "enabled": True,
        "rates": {"Epic": 60, "Legendary": 30, "Mythical": 10},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "advanced_pack": {
        "key": "advanced_pack",
        "name": "Advanced Pack",
        "price": 40000,
        "enabled": True,
        "rates": {"Legendary": 65, "Mythical": 25, "Infernal": 10},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "veteran_pack": {
        "key": "veteran_pack",
        "name": "Veteran Pack",
        "price": 50000,
        "enabled": True,
        "rates": {"Legendary": 30, "Mythical": 50, "Infernal": 20},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "vip_pack": {
        "key": "vip_pack",
        "name": "VIP Pack",
        "price": 75000,
        "enabled": True,
        "rates": {"Mythical": 50, "Infernal": 40, "Abyssal": 10},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "ranker_pack": {
        "key": "ranker_pack",
        "name": "Ranker Pack",
        "price": 90000,
        "enabled": True,
        "rates": {"Infernal": 50, "Abyssal": 50},
        "cards_per_pack": 1,
        "created_at": 0,
    },
    "war_pack": {
        "key": "war_pack",
        "name": "War Pack",
        "price": 0,
        "enabled": False,
        "shop_visible": False,
        "rates": {"Common": 40, "Rare": 30, "Epic": 28, "Legendary": 2},
        "cards_per_pack": 1,
        "created_at": 0,
    },
}

DEFAULT_CONFIG = {
    "rewards": {
        "hourly": 100,
        "daily": 500,
        "weekly": 2000,
        "monthly": 8000,
    },
    "ui": {
        "footer": "LOOKISM HXCC • /help",
        "emojis": {
            # ── Core UI ──────────────────────────────────────────
            "ok":           "✅",
            "no":           "❌",
            "warning":      "⚠",
            "info":         "ℹ",
            "help":         "📖",
            "dot":          "•",
            "line":         "━",
            "box":          "▣",
            "prev":         "⬅",
            "next":         "➡",
            "cancel":       "🚫",
            "confirm":      "✅",
            "lock":         "<:locked:1470383807311122615>",
            "unlock":       "🔓",
            "settings":     "⚙",
            "create":       "🛠",
            "edit":         "✏",
            "delete":       "🗑",
            "view":         "🔎",
            "list":         "📋",
            "page":         "📄",
            "panel":        "🧩",
            "add":          "➕",
            "remove":       "➖",
            "reset":        "♻",
            "status":       "📌",
            "timer":        "⏳",
            "clock":        "⏱",
            "time":         "⏱",
            "link":         "🔗",
            "announce":     "📣",
            "channel":      "📺",
            "send":         "📤",
            "assign":       "🧷",
            # ── Economy ──────────────────────────────────────────
            "coin":         "<:currency:1469410492010463458>",
            "coins":        "<:currency:1469410492010463458>",
            "currency":     "<:currency:1469410492010463458>",
            "gem":          "💎",
            "premium":      "💎",
            "reward":       "<:gold_bars:1470374537836232785>",
            "store":        "🏬",
            "shop":         "🛒",
            "fee":          "💸",
            "redeem":       "🎟",
            "code":         "🧾",
            "limit":        "⛔",
            "uses":         "🔢",
            # ── Cards & Packs ─────────────────────────────────────
            "card":         "<:catalog:1470375205682548961>",
            "catalog":      "<:catalog:1470375205682548961>",
            "pack":         "🎴",
            "open":         "🎁",
            "roll":         "🎲",
            "featured":     "<:catalog:1470375205682548961>",
            "rarity":       "💠",
            "common":       "⚪",
            "rare":         "🔵",
            "epic":         "🟣",
            "legendary":    "🟠",
            "mythical":     "🔴",
            "infernal":     "🔥",
            "abyssal":      "🌌",
            # ── Market & Trade ────────────────────────────────────
            "market":       "🏪",
            "listing":      "🧾",
            "buy":          "🛍",
            "sell":         "<:gold_bars:1470374537836232785>",
            "price":        "<:gold_bars:1470374537836232785>",
            "gold_bars":    "<:gold_bars:1470374537836232785>",
            "seller":       "🧑",
            "stock":        "📦",
            "quick_sell":   "⚡",
            "trade":        "🔁",
            # ── Battle ────────────────────────────────────────────
            "battle":       "<:battle:1470382015437213697>",
            "vs":           "<:battle:1470382015437213697>",
            "friendly":     "<:battle:1470382015437213697>",
            "ranked":       "🏅",
            "attacks":      "<:battle:1470382015437213697>",
            "normal":       "<:normal:1471030412015960269>",
            "special":      "<:special:1471032701132865566>",
            "skill":        "<:skill:1471196099912929443>",
            "ultimate":     "<:Ultimate:1471032754245337120>",
            "attack_normal":       "<:normal:1471030412015960269>",
            "attack_special":      "<:special:1471032701132865566>",
            "attack_ultimate":     "<:Ultimate:1471032754245337120>",
            "attack_unique_skill": "<:skill:1471196099912929443>",
            "attack_unique_path":  "<:Ultimate:1471032754245337120>",
            "defense":      "<:defense:1471196697659965461>",
            "def_block":    "<:defense:1471196697659965461>",
            "def_dodge":    "<:defense:1471196697659965461>",
            "def_parry":    "<:defense:1471196697659965461>",
            "def_revert":   "<:defense:1471196697659965461>",
            "def_tank":     "<:defense:1471196697659965461>",
            "switch":       "🔄",
            "forfeit":      "🏳",
            "hp":           "<:heart:1470383079548780625>",
            "damage":       "🩸",
            "miss":         "❔",
            "crit":         "💢",
            "winner":       "<:r1:1487355065084936254>",
            "round":        "🔁",
            # ── Stats ─────────────────────────────────────────────
            "strength":     "<:strength:1471199061108588748>",
            "speed":        "<:speed:1471198923665178740>",
            "endurance":    "<:endurance:1471199091483476080>",
            "technique":    "<:technique:1471199020989943975>",
            "iq":           "<:emoji_22:1470382114699743457>",
            "biq":          "<:stats_rank:1470382074086031505>",
            "conviction":   "<:conviction:1471198977859915962>",
            "mastermind":   "<:mastermind:1471199662596816999>",
            "mastery":      "🧬",
            "xp":           "<:boost:1470334901319635108>",
            "level":        "<:boost:1470334901319635108>",
            "boost":        "<:boost:1470334901319635108>",
            # ── Squad ─────────────────────────────────────────────
            "squad":        "🧩",
            "squad_power":  "<:squad_power:1469972804408574033>",
            "active":       "🟢",
            "backup":       "🟡",
            # ── Season / Tournament ───────────────────────────────
            "season":       "🗓",
            "pass":         "🎟",
            "tournament":   "<:Trophy:1469971235453665345>",
            "trophy":       "<:Trophy:1469971235453665345>",
            "tier":         "🧱",
            "rank":         "<:stats_rank:1470382074086031505>",
            "stats_rank":   "<:stats_rank:1470382074086031505>",
            "achievement":  "🏅",
            "earned":       "✅",
            "locked":       "<:locked:1470383807311122615>",
            "cp":           "🎯",
            # ── Gang / Alliance ───────────────────────────────────
            "gang":         "<:gang:1470719084848222368>",
            "alliance":     "<:alliance:1471027139003547732>",
            "head":         "<:head:1470759627238019209>",
            "vice":         "<:vice_head:1470759664999207115>",
            "vice_head":    "<:vice_head:1470759664999207115>",
            "recruiter":    "<:recruiter:1470759718107746441>",
            "elder":        "<:elder:1470762649817186409>",
            "member":       "<:member:1470761309430616259>",
            "members":      "👥",
            "invite":       "✉",
            "leave":        "🚪",
            # ── Profile ───────────────────────────────────────────
            "profile":      "👤",
            "bio":          "📝",
            "social":       "🌐",
            "star":         "<:stars:1471032797551530145>",
            "stars":        "<:stars:1471032797551530145>",
            "top":          "<:Trophy:1469971235453665345>",
            "leaderboard":  "📊",
            "league":       "<:stats_rank:1470382074086031505>",
            "stats":        "<:stats_rank:1470382074086031505>",
            # ── Competitive ranks ────────────────────────────────
            "copper":       "<:copper:1471033174070001849>",
            "iron":         "<:iron:1469956766321344606>",
            "bronze":       "<:bronze:1469956844423221410>",
            "silver":       "<:silver:1469956922454311003>",
            "gold":         "<:gold:1469956985574264874>",
            "diamond":      "<:diamond:1469958014197956659>",
            "platinum":     "<:platinum:1469958087359332415>",
            "sapphire":     "<:sapphire:1469958126462570669>",
            "ruby":         "<:ruby:1470383178374971476>",
            "r1":           "<:r1:1487355065084936254>",
            # ── Misc ──────────────────────────────────────────────
            "grant":        "➕",
            "start":        "🪪",
        },
    },
    "market": {
        "enabled": True,
        "tax_rate": 0.05,
        "max_listings_per_user": 10,
    },
    "reward_card_bonus": {
        "hourly": {"enabled": False, "rates": {}},
        "daily": {"enabled": True, "rates": {"Common": 80, "Rare": 20}},
        "weekly": {"enabled": True, "rates": {"Rare": 50, "Epic": 40, "Legendary": 10}},
        "monthly": {"enabled": True, "rates": {"Legendary": 60, "Mythical": 20, "Infernal": 15, "Abyssal": 5}},
    },
    "packs": {
        "definitions": deepcopy(DEFAULT_PACK_DEFINITIONS),
        "stats": {
            "total_packs_opened": 0,
            "total_spent": 0,
        },
    },
    "profile": {
        "default_background_url": "",
        "default_featured_card_name": "",
    },
}

DEFAULT_UI_EMOJIS = deepcopy(DEFAULT_CONFIG["ui"]["emojis"])

# Custom emojis that are available in the bot's Discord server. Other custom
# emoji IDs must be removed from persisted UI settings because Discord renders
# unavailable IDs as broken text rather than an emoji.
SUPPORTED_CUSTOM_UI_EMOJIS = frozenset(
    value for value in DEFAULT_UI_EMOJIS.values()
    if value.startswith("<:") or value.startswith("<a:")
)
_CUSTOM_EMOJI_PREFIXES = ("<:", "<a:")

# Existing installations persist UI emoji values in lookism_data.json. Upgrade
# only values that still match the former built-in Unicode defaults so owner
# overrides made through /o_emoji_panel remain authoritative.
_LEGACY_UI_EMOJI_DEFAULTS: dict[str, set[str]] = {
    "ok": {"✅"},
    "next": {"➡"},
    "confirm": {"☑"},
    "lock": {"🔒"},
    "coin": {"🪙"},
    "coins": {"🪙"},
    "gem": {"💎"},
    "reward": {"🎁"},
    "card": {"🃏"},
    "featured": {"🃏"},
    "rare": {"🔵"},
    "epic": {"🟣"},
    "legendary": {"🟠"},
    "mythical": {"🔴"},
    "infernal": {"🔥"},
    "abyssal": {"🌌"},
    "sell": {"💰"},
    "price": {"💲"},
    "battle": {"⚔", "⚔️"},
    "vs": {"⚔", "⚔️"},
    "friendly": {"🤝"},
    "attacks": {"⚔", "⚔️"},
    "attack_normal": {"🗡", "🗡️"},
    "attack_special": {"💥"},
    "attack_unique_skill": {"🌀", "✨"},
    "attack_unique_path": {"🛤", "🛤️"},
    "attack_ultimate": {"🌀"},
    "def_block": {"🛡", "🛡️"},
    "def_dodge": {"💨"},
    "def_parry": {"🪃"},
    "def_revert": {"🩹"},
    "def_tank": {"💪"},
    "hp": {"❤", "❤️"},
    "strength": {"💪"},
    "speed": {"🏃"},
    "endurance": {"🧱"},
    "technique": {"🎯"},
    "iq": {"🧠"},
    "biq": {"👁", "👁️"},
    "xp": {"✨"},
    "level": {"📶"},
    "squad_power": {"⚡"},
    "pass": {"🎟", "🎟️"},
    "tournament": {"🏆"},
    "trophy": {"🏆"},
    "rank": {"🏅"},
    "locked": {"🔒"},
    "gang": {"👥"},
    "alliance": {"🤝"},
    "head": {"👑"},
    "vice": {"🛡", "🛡️"},
    "recruiter": {"📨"},
    "elder": {"🧓"},
    "member": {"🙂"},
    "top": {"🏆"},
    "league": {"🏟", "🏟️"},
    "stats": {"📈"},
    "star": {"⭐"},
    "winner": {"🥇"},
}


def _upgrade_legacy_ui_emojis(emojis: dict[str, Any]) -> None:
    for key, legacy_values in _LEGACY_UI_EMOJI_DEFAULTS.items():
        current = str(emojis.get(key, ""))
        if current in legacy_values:
            emojis[key] = DEFAULT_UI_EMOJIS[key]

    # Retire custom emoji IDs from earlier skins unless they are in the
    # supplied allowlist above. Their standard Unicode default remains usable.
    for key, current in list(emojis.items()):
        value = str(current or "")
        if value.startswith(_CUSTOM_EMOJI_PREFIXES) and value not in SUPPORTED_CUSTOM_UI_EMOJIS:
            emojis[key] = DEFAULT_UI_EMOJIS.get(key, "•")


DEFAULT_PLAYER = {
    "user": {
        "id": "",
        "name": "",
        "registered_at": 0,
        "tos_accepted": False,
        "balance": 0,
        "premium_balance": 0,
        "is_premium": False,
        "inventory": [],
        "weapon_inventory": [],
        "trophies": 0,
        "rank": "Copper",
        "profile": {
            "bio": "",
            "background_url": "",
            "showcase_uid": "",
            "cosmetics": {
                "theme": "",
                "border_id": "",
                "badge_id": "",
            },
        },
        "privacy_settings": {
            "show_balance": True,
            "show_trophies": True,
            "show_gang": True,
        },
        "cooldowns": {
            "hourly": 0,
            "daily": 0,
            "weekly": 0,
            "monthly": 0,
        },
        "tutorial": {
            "step": 0,
            "completed": False,
        },
    },
    "gang_id": None,
    "alliance_id": None,
    "squad": {
        "active": [],
        "backup": [],
        "supervisor": "",
    },
    "ranked_stats": {
        "wins": 0,
        "losses": 0,
        "streak": 0,
        "last_10": [],
    },
    "rival": {
        "rival_id": None,
        "rival_name": "",
        "losses_to": 0,
        "wins_vs": 0,
    },
    "season_claims": {},
    "season_pass": {"season": 1, "xp": 0, "level": 1, "claimed": {}},
    "achievements": {"earned": {}},
    "achievement_points": 0,
    "redeemed_codes": {},
    "market": {"active_listing_ids": []},
    "trade_history": [],
    "packs": {"opened": 0, "spent": 0},
    "pity": {},
}

DEFAULT_DATA = {
    "players": {},
    "cards": {},
    "weapons": {},
    "keystones": {},
    "battle": {
        "queue": [],
        "pending_friendly": {},
        "active": {},
        "active_by_user": {},
    },
    "attacks": {
        "catalog": {}
    },
    "cotd": {},
    "active_events": {
        "double_xp": {"active": False, "ends_at": 0},
        "double_coins": {"active": False, "ends_at": 0},
    },
    "ai": {
        "settings": {
            "enabled": True,
            "default_affects_trophies": False,
            "max_ai_battles_per_day": 10,
        },
        "roster": {
            "james_lee_mastermind": {
                "name": "James Lee Mastermind",
                "team_mode": "fixed",
                "team_cards": [],
                "fallback_rarity_min": "Abyssal",
            },
            "james_lee_peak": {
                "name": "James Lee Peak",
                "team_mode": "fixed",
                "team_cards": [],
                "fallback_rarity_min": "Abyssal",
            },
            "kitae_kim_busan": {
                "name": "Kitae Kim Busan",
                "team_mode": "fixed",
                "team_cards": [],
                "fallback_rarity_min": "Abyssal",
            },
            "diego_kang": {
                "name": "Diego Kang",
                "team_mode": "fixed",
                "team_cards": [],
                "fallback_rarity_min": "Abyssal",
            },
        },
        "history": [],
        "stats": {},
    },
    "gangs": {},
    "server_settings": {
        "mode": "all",
        "locked_channel_id": 0,
        "announce_channel_id": 0,
        "battle_channel_id": 0,
    },
    "ui": {
        "emojis": deepcopy(DEFAULT_UI_EMOJIS),
    },
    "config": DEFAULT_CONFIG,
    "market": {
        "settings": {
            "enabled": True,
            "fee_percent": 5,
            "max_listings_per_user": 10,
            "quick_sell_values": {
                "Common": 250,
                "Rare": 1000,
                "Epic": 5000,
                "Legendary": 20000,
                "Mythical": 40000,
                "Infernal": 60000,
                "Abyssal": 80000,
            },
            "price_band": {
                "Common": {"min": 500, "max": 1000},
                "Rare": {"min": 3000, "max": 5000},
                "Epic": {"min": 10000, "max": 20000},
                "Legendary": {"min": 30000, "max": 40000},
                "Mythical": {"min": 50000, "max": 60000},
                "Infernal": {"min": 70000, "max": 80000},
                "Abyssal": {"min": 90000, "max": 100000},
            },
        },
        "listings": {},
        "store": {
            "items": {},
            "volume_traded": 0,
        },
    },
    "trades": {
        "pending": {},
    },
    "packs": {
        "definitions": deepcopy(DEFAULT_PACK_DEFINITIONS),
        "stats": {
            "total_packs_opened": 0,
            "total_spent": 0,
        },
    },
    "confirm_actions": {},
    "gang_invites": {},
    "alliance_invites": {},
    "alliance_cooldowns": {},
    "redeem_codes": {},
    "season": {
        "active":         True,
        "current_season": 1,
        "name":           "Season 1 — Rise of Legends",
        "start_time":     1742169600,
        "end_time":       1749945600,
        "reset_type":     "both",
        "pass_tiers": {
            "1":  {"cp_required": 100,   "free_reward": "500 coins",       "paid_reward": "Newbie Pack"},
            "2":  {"cp_required": 300,   "free_reward": "1000 coins",      "paid_reward": "30 gems"},
            "3":  {"cp_required": 600,   "free_reward": "Amateur Pack",    "paid_reward": "Basic Pack"},
            "4":  {"cp_required": 1000,  "free_reward": "1500 coins",      "paid_reward": "40 gems"},
            "5":  {"cp_required": 1500,  "free_reward": "Basic Pack",      "paid_reward": "Intermediate Pack"},
            "6":  {"cp_required": 2100,  "free_reward": "2000 coins",      "paid_reward": "70 gems"},
            "7":  {"cp_required": 2800,  "free_reward": "2500 coins",      "paid_reward": "Experienced Pack"},
            "8":  {"cp_required": 3600,  "free_reward": "Intermediate Pack","paid_reward": "40 gems"},
            "9":  {"cp_required": 4500,  "free_reward": "3000 coins",      "paid_reward": "Advanced Pack"},
            "10": {"cp_required": 5500,  "free_reward": "Experienced Pack","paid_reward": "Veteran Pack"},
            "11": {"cp_required": 6600,  "free_reward": "5000 coins",      "paid_reward": "30 gems"},
            "12": {"cp_required": 7800,  "free_reward": "Advanced Pack",   "paid_reward": "2x Experienced Pack"},
            "13": {"cp_required": 9100,  "free_reward": "7500 coins",      "paid_reward": "40 gems"},
            "14": {"cp_required": 10500, "free_reward": "Veteran Pack",    "paid_reward": "VIP Pack"},
            "15": {"cp_required": 12000, "free_reward": "10000 coins",     "paid_reward": "Ranker Pack"},
        },
        "missions": {
            "d001": {"title": "Daily Login",          "type": "free", "period": "daily",   "requirement": "daily_login",     "target": 1,  "reward_cp": 50},
            "d002": {"title": "Play a Battle",        "type": "free", "period": "daily",   "requirement": "battles_played",  "target": 1,  "reward_cp": 75},
            "d003": {"title": "Win a Ranked Battle",  "type": "free", "period": "daily",   "requirement": "ranked_wins",     "target": 1,  "reward_cp": 100},
            "d004": {"title": "Open a Pack",          "type": "free", "period": "daily",   "requirement": "packs_opened",    "target": 1,  "reward_cp": 60},
            "d005": {"title": "Win 2 Battles",        "type": "paid", "period": "daily",   "requirement": "ranked_wins",     "target": 2,  "reward_cp": 150},
            "w001": {"title": "Play 10 Battles",      "type": "free", "period": "weekly",  "requirement": "battles_played",  "target": 10, "reward_cp": 400},
            "w002": {"title": "Win 5 Ranked Battles", "type": "free", "period": "weekly",  "requirement": "ranked_wins",     "target": 5,  "reward_cp": 600},
            "w003": {"title": "Open 3 Packs",         "type": "free", "period": "weekly",  "requirement": "packs_opened",    "target": 3,  "reward_cp": 350},
            "w004": {"title": "Complete a Trade",     "type": "free", "period": "weekly",  "requirement": "trades_completed","target": 1,  "reward_cp": 300},
            "w005": {"title": "Win 10 Ranked Battles","type": "paid", "period": "weekly",  "requirement": "ranked_wins",     "target": 10, "reward_cp": 800},
            "w006": {"title": "Win Tournament Battle","type": "paid", "period": "weekly",  "requirement": "tournament_wins", "target": 1,  "reward_cp": 500},
            "mo01": {"title": "Play 50 Battles",      "type": "free", "period": "monthly", "requirement": "battles_played",  "target": 50, "reward_cp": 1500},
            "mo02": {"title": "Win 25 Ranked Battles","type": "free", "period": "monthly", "requirement": "ranked_wins",     "target": 25, "reward_cp": 2000},
            "mo03": {"title": "Open 10 Packs",        "type": "free", "period": "monthly", "requirement": "packs_opened",    "target": 10, "reward_cp": 1200},
            "mo04": {"title": "Win 3 Tournament Battles","type":"paid","period": "monthly","requirement": "tournament_wins", "target": 3,  "reward_cp": 2500},
            "mo05": {"title": "Play 100 Battles",     "type": "paid", "period": "monthly", "requirement": "battles_played",  "target": 100,"reward_cp": 3000},
            "s001": {"title": "First Steps",          "type": "free", "period": "season",  "requirement": "battles_played",  "target": 1,  "reward_cp": 100},
            "s002": {"title": "Ranked Warrior",       "type": "free", "period": "season",  "requirement": "ranked_wins",     "target": 15, "reward_cp": 500},
            "s003": {"title": "Tournament Debut",     "type": "free", "period": "season",  "requirement": "tournament_wins", "target": 1,  "reward_cp": 300},
            "s004": {"title": "Unstoppable",          "type": "paid", "period": "season",  "requirement": "ranked_wins",     "target": 30, "reward_cp": 800},
            "s005": {"title": "Tournament Legend",    "type": "paid", "period": "season",  "requirement": "tournament_wins", "target": 5,  "reward_cp": 1000},
        },
    },
    "season_data": {
        "current_season": 1,
        "start_time": 0,
        "end_time": 0,
        "reset_type": "soft",
        "soft_reset_percent": 50,
        "global_rewards": [],
        "season_rewards": {},
        "season_reward_distributed": False,
        "archived_seasons": {},
        "season_pass_rewards": {},
    },
    "alliances": {},
    "achievement_catalog": {
        "first_blood": {"id": "first_blood", "name": "First Blood", "desc": "Win your first ranked battle.", "tier": "Bronze", "icon_key": "battle", "points": 10},
        "ai_slayer": {"id": "ai_slayer", "name": "AI Slayer", "desc": "Win your first AI battle.", "tier": "Bronze", "icon_key": "ai", "points": 10},
        "collector_10": {"id": "collector_10", "name": "Collector I", "desc": "Own 10 cards.", "tier": "Bronze", "icon_key": "card", "points": 15},
        "collector_50": {"id": "collector_50", "name": "Collector II", "desc": "Own 50 cards.", "tier": "Silver", "icon_key": "card", "points": 30},
        "trader": {"id": "trader", "name": "Trader", "desc": "Complete your first trade.", "tier": "Silver", "icon_key": "trade", "points": 20},
        "market_seller": {"id": "market_seller", "name": "Market Seller", "desc": "Sell your first listing.", "tier": "Bronze", "icon_key": "market", "points": 15},
        "pack_opener": {"id": "pack_opener", "name": "Pack Opener", "desc": "Open your first pack.", "tier": "Bronze", "icon_key": "pack", "points": 15},
        "gang_member": {"id": "gang_member", "name": "Gang Member", "desc": "Join a gang.", "tier": "Silver", "icon_key": "gang", "points": 20},
        "alliance_member": {"id": "alliance_member", "name": "Alliance Member", "desc": "Join an alliance.", "tier": "Gold", "icon_key": "alliance", "points": 35},
        "tournament_entry": {"id": "tournament_entry", "name": "Tournament Entry", "desc": "Join a tournament.", "tier": "Silver", "icon_key": "tournament", "points": 25},
        "tournament_champ": {"id": "tournament_champ", "name": "Tournament Champion", "desc": "Win a tournament.", "tier": "Diamond", "icon_key": "winner", "points": 80},
        "season_claimer": {"id": "season_claimer", "name": "Season Claimer", "desc": "Claim your first season reward.", "tier": "Gold", "icon_key": "season", "points": 40},
        "win_10_battles": {"id": "win_10_battles", "name": "Battle Novice", "desc": "Win 10 ranked battles.", "tier": "Bronze", "icon_key": "battle", "points": 200},
        "win_50_battles": {"id": "win_50_battles", "name": "Battle Warrior", "desc": "Win 50 ranked battles.", "tier": "Silver", "icon_key": "battle", "points": 500},
        "win_100_battles": {"id": "win_100_battles", "name": "Battle Master", "desc": "Win 100 ranked battles.", "tier": "Gold", "icon_key": "battle", "points": 1000},
        "win_streak_5": {"id": "win_streak_5", "name": "On Fire", "desc": "Win 5 ranked battles in a row.", "tier": "Silver", "icon_key": "battle", "points": 300},
        "own_5_cards": {"id": "own_5_cards", "name": "Card Starter", "desc": "Own 5 unique cards.", "tier": "Bronze", "icon_key": "card", "points": 100},
        "own_15_cards": {"id": "own_15_cards", "name": "Card Enthusiast", "desc": "Own 15 unique cards.", "tier": "Silver", "icon_key": "card", "points": 400},
        "own_all_cards": {"id": "own_all_cards", "name": "Card Collector", "desc": "Own all 26 unique cards.", "tier": "Diamond", "icon_key": "card", "points": 2000},
        "reach_silver": {"id": "reach_silver", "name": "Silver Tier", "desc": "Reach Silver rank.", "tier": "Silver", "icon_key": "rank", "points": 200},
        "reach_gold": {"id": "reach_gold", "name": "Gold Tier", "desc": "Reach Gold rank.", "tier": "Gold", "icon_key": "rank", "points": 400},
        "reach_diamond": {"id": "reach_diamond", "name": "Diamond Tier", "desc": "Reach Diamond rank.", "tier": "Diamond", "icon_key": "rank", "points": 800},
        "reach_ruby": {"id": "reach_ruby", "name": "Ruby Tier", "desc": "Reach Ruby rank.", "tier": "Diamond", "icon_key": "rank", "points": 1500},
        "first_fusion": {"id": "first_fusion", "name": "Fusion Master", "desc": "Fuse a card for the first time.", "tier": "Bronze", "icon_key": "card", "points": 150},
        "complete_10_trades": {"id": "complete_10_trades", "name": "Trading Expert", "desc": "Complete 10 trades.", "tier": "Silver", "icon_key": "trade", "points": 300},
        "level_25": {"id": "level_25", "name": "Intermediate Player", "desc": "Reach player level 25.", "tier": "Silver", "icon_key": "level", "points": 500},
        "level_50": {"id": "level_50", "name": "Veteran Player", "desc": "Reach player level 50.", "tier": "Gold", "icon_key": "level", "points": 1000},
        "spend_100k_coins": {"id": "spend_100k_coins", "name": "Big Spender", "desc": "Spend 100,000 total coins.", "tier": "Gold", "icon_key": "coins", "points": 400},
        "win_gang_war": {"id": "win_gang_war", "name": "Gang War Victor", "desc": "Win a gang war.", "tier": "Gold", "icon_key": "gang", "points": 600},
        "land_10_power_moves": {"id": "land_10_power_moves", "name": "Power Striker", "desc": "Land 10 unique skill or path moves in battle.", "tier": "Silver", "icon_key": "battle", "points": 250},
        "perfect_block_10": {"id": "perfect_block_10", "name": "Perfect Defender", "desc": "Successfully block 10 attacks.", "tier": "Silver", "icon_key": "battle", "points": 200},
    },
    "tournament": {
        "active":       True,
        "name":         "Season 1 — Grand Opening Championship",
        "entry_fee":    2000,
        "max_players":  16,
        "prize_pool":   10000,
        "start_time":   1742169600,
        "end_time":     1742256000,
        "participants": {},
        "tid":          "s1-grand",
    },
    "bounty": {
        "target_id": None,
        "target_name": "",
        "streak": 0,
        "reward": 3000,
        "week": 0,
    },
}


_cached_default_data: dict[str, Any] | None = None


def build_default_data() -> dict[str, Any]:
    global _cached_default_data
    if _cached_default_data is not None:
        return deepcopy(_cached_default_data)
    data = deepcopy(DEFAULT_DATA)
    data["cards"] = deepcopy(_load_card_catalog())
    _now = int(time.time())
    season = data.get("season", {})
    if isinstance(season, dict) and season.get("start_time", 0) < 1700000000:
        season["start_time"] = _now - 604800
        season["end_time"] = _now + 5184000
    tournament = data.get("tournament", {})
    if isinstance(tournament, dict) and tournament.get("start_time", 0) < 1700000000:
        tournament["start_time"] = _now
        tournament["end_time"] = _now + 259200
    _cached_default_data = data
    return deepcopy(data)


def build_default_player(user_id: str, username: str, registered_at: int) -> dict[str, Any]:
    player = deepcopy(DEFAULT_PLAYER)
    player["user"]["id"] = user_id
    player["user"]["name"] = username
    player["user"]["registered_at"] = registered_at
    return player


def ensure_structure(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}

    defaults = build_default_data()
    for key, default_value in defaults.items():
        if not _is_compatible(data.get(key), default_value):
            data[key] = deepcopy(default_value)

    if not isinstance(data.get("config"), dict):
        data["config"] = deepcopy(DEFAULT_CONFIG)
    _merge_dict(data["config"], DEFAULT_CONFIG)

    ui_root = data.get("ui")
    if not isinstance(ui_root, dict):
        data["ui"] = {"emojis": deepcopy(DEFAULT_UI_EMOJIS)}
    else:
        emojis = ui_root.get("emojis")
        if not isinstance(emojis, dict):
            ui_root["emojis"] = deepcopy(DEFAULT_UI_EMOJIS)
        else:
            _merge_dict(emojis, DEFAULT_UI_EMOJIS)
            _upgrade_legacy_ui_emojis(emojis)

    players = data.get("players")
    if isinstance(players, dict):
        for player_id, player in players.items():
            if not isinstance(player, dict):
                players[player_id] = build_default_player(str(player_id), "", 0)
                continue
            _merge_dict(player, DEFAULT_PLAYER)
            user = player.get("user")
            if isinstance(user, dict):
                user["id"] = str(user.get("id") or player_id)
                inventory = user.get("inventory", [])
                if isinstance(inventory, list):
                    for item in inventory:
                        if isinstance(item, dict):
                            if str(item.get("card_name", "")) == "Changyong ji":
                                item["card_name"] = "Changyong Ji [HfH Arc]"
                            item.setdefault("squad_locked", False)
                            item.setdefault("market_locked", False)
            packs_profile = player.get("packs")
            if not isinstance(packs_profile, dict):
                player["packs"] = {"opened": 0, "spent": 0}
            else:
                packs_profile.setdefault("opened", 0)
                packs_profile.setdefault("spent", 0)

    data["cards"] = _sync_catalog_cards(data.get("cards"))
    for _, card in data["cards"].items():
        if isinstance(card, dict):
            _normalize_card_stats(card)
            card.setdefault("emoji", "🃏")
            card.setdefault("default_dialogue", str(card.get("dialogue", "The fighter stays focused.")))
            mastery = card.get("mastery")
            if isinstance(mastery, dict):
                card["mastery"] = {
                    "type": mastery.get("type") if mastery.get("type") not in {"", "None"} else None,
                    "description": str(mastery.get("description", "")),
                }
            elif isinstance(mastery, str) and mastery.strip():
                card["mastery"] = {"type": mastery.strip(), "description": ""}
            else:
                card["mastery"] = {"type": None, "description": ""}

            path = card.get("path")
            if isinstance(path, dict):
                card["path"] = {"name": str(path.get("name", "")), "description": str(path.get("description", ""))}
            else:
                card["path"] = {"name": str(path or ""), "description": str(card.get("unique_path_dialogue", ""))}

            uskill = card.get("unique_skill")
            if isinstance(uskill, dict):
                card["unique_skill"] = {"name": str(uskill.get("name", "")), "description": str(uskill.get("description", ""))}
            else:
                card["unique_skill"] = {"name": "", "description": str(card.get("unique_skill_dialogue", ""))}

            card.setdefault("unique_path_dialogue", str(card["path"].get("description", "")))
            card.setdefault("unique_skill_dialogue", str(card["unique_skill"].get("description", "")))
            mv = card.get("moves", [])
            if isinstance(mv, list):
                for m in mv:
                    if isinstance(m, dict):
                        m.setdefault("dialogue", card.get("default_dialogue", ""))
                        m.setdefault("crit_dialogue", "")
                        m.setdefault("miss_dialogue", "")

    # Remove orphan/legacy attack links; keep catalog empty for formula-based move damage.
    attacks = data.get("attacks")
    if not isinstance(attacks, dict):
        data["attacks"] = {"catalog": {}}
    else:
        if "catalog" not in attacks or not isinstance(attacks.get("catalog"), dict):
            attacks["catalog"] = {}

    ai = data.get("ai")
    if not isinstance(ai, dict):
        data["ai"] = deepcopy(DEFAULT_DATA["ai"])
    else:
        _merge_dict(ai, DEFAULT_DATA["ai"])

    server_settings = data.get("server_settings")
    if not isinstance(server_settings, dict):
        data["server_settings"] = deepcopy(DEFAULT_DATA["server_settings"])
    else:
        _merge_dict(server_settings, DEFAULT_DATA["server_settings"])

    market = data.get("market")
    if not isinstance(market, dict):
        data["market"] = deepcopy(DEFAULT_DATA["market"])
    else:
        _merge_dict(market, DEFAULT_DATA["market"])
        settings = market.get("settings")
        if not isinstance(settings, dict):
            market["settings"] = deepcopy(DEFAULT_DATA["market"]["settings"])
        else:
            _merge_dict(settings, DEFAULT_DATA["market"]["settings"])
        if not isinstance(market.get("listings"), dict):
            market["listings"] = {}
        store = market.get("store")
        if not isinstance(store, dict):
            market["store"] = deepcopy(DEFAULT_DATA["market"]["store"])
        else:
            _merge_dict(store, DEFAULT_DATA["market"]["store"])
            if not isinstance(store.get("items"), dict):
                store["items"] = {}

    trades = data.get("trades")
    if not isinstance(trades, dict):
        data["trades"] = deepcopy(DEFAULT_DATA["trades"])
    else:
        _merge_dict(trades, DEFAULT_DATA["trades"])

    packs = data.get("packs")
    if not isinstance(packs, dict):
        data["packs"] = deepcopy(DEFAULT_DATA["packs"])
    else:
        legacy_defs = packs.get("defs") if isinstance(packs.get("defs"), dict) else {}
        _merge_dict(packs, DEFAULT_DATA["packs"])
        if not isinstance(packs.get("definitions"), dict):
            packs["definitions"] = {}
        if isinstance(legacy_defs, dict):
            for k, v in legacy_defs.items():
                if k not in packs["definitions"] and isinstance(v, dict):
                    packs["definitions"][k] = v
        stats = packs.get("stats")
        if not isinstance(stats, dict):
            packs["stats"] = deepcopy(DEFAULT_DATA["packs"]["stats"])
        else:
            _merge_dict(stats, DEFAULT_DATA["packs"]["stats"])

    season_data = data.get("season_data")
    if not isinstance(season_data, dict):
        data["season_data"] = deepcopy(DEFAULT_DATA["season_data"])
    else:
        _merge_dict(season_data, DEFAULT_DATA["season_data"])

    alliances = data.get("alliances")
    if not isinstance(alliances, dict):
        data["alliances"] = {}

    alliance_invites = data.get("alliance_invites")
    if not isinstance(alliance_invites, dict):
        data["alliance_invites"] = {}

    alliance_cooldowns = data.get("alliance_cooldowns")
    if not isinstance(alliance_cooldowns, dict):
        data["alliance_cooldowns"] = {}

    redeem_codes = data.get("redeem_codes")
    if not isinstance(redeem_codes, dict):
        data["redeem_codes"] = {}

    achievement_catalog = data.get("achievement_catalog")
    if not isinstance(achievement_catalog, dict):
        data["achievement_catalog"] = deepcopy(DEFAULT_DATA["achievement_catalog"])
    else:
        _merge_dict(achievement_catalog, DEFAULT_DATA["achievement_catalog"])

    tournament = data.get("tournament")
    if not isinstance(tournament, dict):
        data["tournament"] = deepcopy(DEFAULT_DATA["tournament"])
    else:
        _merge_dict(tournament, DEFAULT_DATA["tournament"])
        if not isinstance(tournament.get("players"), list):
            tournament["players"] = []
        if not isinstance(tournament.get("eliminated"), list):
            tournament["eliminated"] = []
        if not isinstance(tournament.get("entry_fees_paid"), dict):
            tournament["entry_fees_paid"] = {}
        if not isinstance(tournament.get("reward"), dict):
            tournament["reward"] = {"reward_type": "", "reward_value": ""}
        bracket = tournament.get("bracket")
        if not isinstance(bracket, dict):
            tournament["bracket"] = {"rounds": []}
        elif not isinstance(bracket.get("rounds"), list):
            bracket["rounds"] = []

    return data


def _merge_dict(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, source_value in source.items():
        if key not in target:
            target[key] = deepcopy(source_value)
            continue
        target_value = target[key]
        if isinstance(target_value, dict) and isinstance(source_value, dict):
            _merge_dict(target_value, source_value)


def _is_compatible(value: Any, default_value: Any) -> bool:
    if isinstance(default_value, dict):
        return isinstance(value, dict)
    if isinstance(default_value, list):
        return isinstance(value, list)
    return value is not None
