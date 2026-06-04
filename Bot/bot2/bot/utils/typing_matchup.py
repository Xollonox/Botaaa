from __future__ import annotations

from typing import Iterable

TYPES: tuple[str, ...] = (
    "Tank",
    "Fighter",
    "Brawler",
    "Speedster",
    "Assassin",
    "Mastermind",
)

# (attacker, defender) -> outgoing damage multiplier for attacker
_OFFENSIVE: dict[tuple[str, str], float] = {
    ("Brawler", "Fighter"): 1.15,
    ("Speedster", "Brawler"): 1.30,
    ("Assassin", "Tank"): 1.30,
    ("Fighter", "Brawler"): 0.85,
}

# (attacker, defender) -> incoming damage multiplier applied on the defender
_DEFENSIVE: dict[tuple[str, str], float] = {
    ("Speedster", "Tank"): 0.70,
    ("Assassin", "Fighter"): 0.70,
    ("Fighter", "Brawler"): 0.85,
}

MASTERMIND_IQ_BONUS: int = 10
MASTERMIND_BIQ_BONUS: int = 10


def normalize_typing(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for t in raw:
        if not isinstance(t, str):
            continue
        name = t.strip().title()
        if name in TYPES and name not in out:
            out.append(name)
        if len(out) == 2:
            break
    return out


def parse_typing_input(text: str) -> list[str]:
    parts = [p.strip() for p in str(text or "").replace("/", ",").split(",") if p.strip()]
    return normalize_typing(parts)


def has_mastermind(types: Iterable[str]) -> bool:
    return any(str(t).title() == "Mastermind" for t in types)


def type_multiplier(attacker_types: Iterable[str], defender_types: Iterable[str]) -> float:
    A = normalize_typing(list(attacker_types))
    D = normalize_typing(list(defender_types))
    if not A or not D:
        return 1.0
    # Case 4: identical two-type sets nullify
    if len(A) == 2 and len(D) == 2 and set(A) == set(D):
        return 1.0
    mult = 1.0
    for at in A:
        for dt in D:
            mult *= _OFFENSIVE.get((at, dt), 1.0)
    return mult


def defensive_multiplier(attacker_types: Iterable[str], defender_types: Iterable[str]) -> float:
    A = normalize_typing(list(attacker_types))
    D = normalize_typing(list(defender_types))
    if not A or not D:
        return 1.0
    if len(A) == 2 and len(D) == 2 and set(A) == set(D):
        return 1.0
    mult = 1.0
    for at in A:
        for dt in D:
            mult *= _DEFENSIVE.get((at, dt), 1.0)
    return mult


def relations_table() -> list[tuple[str, str, float, float]]:
    """Returns (attacker, defender, offensive_mult, defensive_mult) rows for display."""
    rows: list[tuple[str, str, float, float]] = []
    keys = set(_OFFENSIVE.keys()) | set(_DEFENSIVE.keys())
    for at, dt in sorted(keys):
        rows.append((at, dt, _OFFENSIVE.get((at, dt), 1.0), _DEFENSIVE.get((at, dt), 1.0)))
    return rows
