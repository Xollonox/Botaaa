"""TypedDict schemas for in-memory storage shapes.

Apply gradually; runtime is unaffected (TypedDicts are erased at runtime).
Use these to type service/util signatures and to catch shape drift via mypy.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Card(TypedDict, total=False):
    uid: str
    card_name: str
    rarity: str
    stars: int
    arc: str
    image_url: str
    locked: bool
    squad_locked: bool
    market_locked: bool
    trade_locked: bool
    acquired_at: int
    weapon_uid: str
    keystone_equipped: bool


class WeaponInstance(TypedDict, total=False):
    uid: str
    weapon_name: str
    rarity: str
    stars: int
    locked: bool
    equipped_to: str
    acquired_at: int


class WeaponDef(TypedDict, total=False):
    name: str
    rarity: str
    image_url: str
    emoji: str
    compatible_cards: list
    stat_buffs: dict
    effect: str
    effect_active: bool


class KeystoneDef(TypedDict, total=False):
    name: str
    effect: str
    character: str
    active: bool


class Profile(TypedDict, total=False):
    bio: str
    showcase_uid: str
    badge_id: str
    cosmetics: dict[str, Any]


class RankedStats(TypedDict, total=False):
    wins: int
    losses: int
    streak: int


class UserData(TypedDict, total=False):
    id: str
    balance: int
    coins: int
    xp: int
    level: int
    trophies: int
    rank: str
    inventory: list[Card]
    weapon_inventory: list[WeaponInstance]
    profile: Profile
    achievements: list[Any]
    war_points: int
    registered_at: int
    cpu_win_timestamps: list[int]
    mission_progress: dict[str, dict[str, int]]


class Player(TypedDict, total=False):
    user: UserData
    ranked_stats: RankedStats
    gang_id: str
    is_cpu: bool
    cpu_meta: dict[str, Any]


class Listing(TypedDict, total=False):
    id: str
    seller_id: str
    seller_name: str
    card_name: str
    card_uid: str
    rarity: str
    arc: str
    price: int
    image_url: str
    stock: int
    listed_at: int
    expires_at: int
    sold: bool


class TradeRecord(TypedDict, total=False):
    a_id: str
    b_id: str
    a_name: str
    b_name: str
    a_card: Card
    b_card: Card
    a_coins: int
    b_coins: int
    status: str  # accepted | declined | cancelled | expired
    created_at: int
    expires_at: int
    resolved_at: int


class Season(TypedDict, total=False):
    active: bool
    current_season: int
    name: str
    duration_days: int
    started_at: int
    missions: dict[str, dict[str, Any]]
    pass_tiers: dict[str, dict[str, Any]]


class Battle(TypedDict, total=False):
    id: str
    battle_type: str  # ranked | friendly | cpu | tournament
    status: str
    players: dict[str, dict[str, Any]]
    turn: int
    turn_started_at: int
    winner_id: str
    loser_id: str
    coin_reward: int
    cpu_trophy_change: int
    cpu_opponent_line: str
    pvp_trophy_changes: dict[str, int]


class Storage(TypedDict, total=False):
    players: dict[str, Player]
    cards: dict[str, dict[str, Any]]
    weapons: dict[str, WeaponDef]
    keystones: dict[str, KeystoneDef]
    market: dict[str, Any]
    trades: dict[str, Any]
    battle: dict[str, Battle]
    season: Season
    gangs: dict[str, dict[str, Any]]
    server_settings: dict[str, Any]
    ai: dict[str, Any]
