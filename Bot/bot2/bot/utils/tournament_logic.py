"""Tournament bracket logic."""

from __future__ import annotations

import math
import random
from typing import Any


def bracket_size_from_players(player_count: int) -> int:
    """Return the next power-of-2 bracket size for *player_count*."""
    if player_count <= 0:
        return 2
    exp = math.ceil(math.log2(max(2, player_count)))
    return 2 ** exp


def total_rounds_from_size(bracket_size: int) -> int:
    """Return total rounds needed for a single-elimination bracket."""
    if bracket_size <= 1:
        return 0
    return int(math.log2(bracket_size))


def build_empty_rounds(total_rounds: int) -> list[list[dict[str, Any]]]:
    """Build empty round lists for a bracket."""
    return [[] for _ in range(total_rounds)]


def build_initial_round(
    players: list[str],
    bracket_size: int,
) -> list[dict[str, Any]]:
    """
    Build the initial round of matches, seeding in byes as needed.

    Returns a list of match dicts.
    """
    shuffled = list(players)
    random.shuffle(shuffled)

    # Pad with byes to fill the bracket
    byes_needed = bracket_size - len(shuffled)
    padded = shuffled + [None] * byes_needed

    matches = []
    for i in range(0, len(padded), 2):
        p1 = padded[i]
        p2 = padded[i + 1] if i + 1 < len(padded) else None
        match: dict[str, Any] = {
            "match_id": f"r1m{i // 2 + 1}",
            "player_a": p1,
            "player_b": p2,
            "winner": None,
            "is_bye": p2 is None or p1 is None,
            "played": False,
        }
        if match["is_bye"]:
            match["winner"] = p1 if p1 is not None else p2
            match["played"] = True
        matches.append(match)
    return matches


def find_match(
    bracket: dict[str, Any],
    player_a_id: str,
    player_b_id: str,
    round_index: int,
) -> dict[str, Any] | None:
    """Find a match in the bracket for the given players in a given round."""
    rounds = bracket.get("rounds", [])
    if not isinstance(rounds, list) or round_index >= len(rounds):
        return None
    matches = rounds[round_index]
    if not isinstance(matches, list):
        return None
    for match in matches:
        if not isinstance(match, dict):
            continue
        a = str(match.get("player_a", ""))
        b = str(match.get("player_b", ""))
        if (a == str(player_a_id) and b == str(player_b_id)) or (a == str(player_b_id) and b == str(player_a_id)):
            return match
    return None


def advance_winner(
    bracket: dict[str, Any],
    match_id: str,
    winner_id: str,
    current_round: int,
) -> bool:
    """
    Record a match winner and advance them to the next round's match.

    Returns True if the match was found and updated.
    """
    rounds = bracket.get("rounds", [])
    if not isinstance(rounds, list):
        return False

    # Find and update the match
    match_idx = None
    round_matches = rounds[current_round] if current_round < len(rounds) else []
    if not isinstance(round_matches, list):
        return False

    for idx, match in enumerate(round_matches):
        if isinstance(match, dict) and str(match.get("match_id", "")) == str(match_id):
            match["winner"] = str(winner_id)
            match["played"] = True
            match_idx = idx
            break

    if match_idx is None:
        return False

    # Advance to next round
    next_round = current_round + 1
    if next_round >= len(rounds):
        return True  # This was the final

    next_match_idx = match_idx // 2
    next_matches = rounds[next_round]
    if not isinstance(next_matches, list):
        return True

    # Pad next round if needed
    while len(next_matches) <= next_match_idx:
        next_matches.append({
            "match_id": f"r{next_round + 1}m{len(next_matches) + 1}",
            "player_a": None,
            "player_b": None,
            "winner": None,
            "is_bye": False,
            "played": False,
        })

    next_match = next_matches[next_match_idx]
    if next_match.get("player_a") is None:
        next_match["player_a"] = str(winner_id)
    else:
        next_match["player_b"] = str(winner_id)
        # Check for auto-bye
        if next_match.get("player_a") and not next_match.get("player_b"):
            pass
        elif next_match.get("player_a") and next_match.get("player_b"):
            pass

    return True


def auto_resolve_byes(rounds: list[list[dict[str, Any]]]) -> list[str]:
    """Auto-resolve all bye matches. Returns list of advanced player IDs."""
    advanced = []
    for round_matches in rounds:
        if not isinstance(round_matches, list):
            continue
        for match in round_matches:
            if not isinstance(match, dict):
                continue
            if bool(match.get("is_bye")) and not match.get("played"):
                winner = match.get("player_a") or match.get("player_b")
                if winner:
                    match["winner"] = str(winner)
                    match["played"] = True
                    advanced.append(str(winner))
    return advanced


def remaining_players(bracket: dict[str, Any], current_round: int) -> list[str]:
    """Return players who haven't been eliminated by the start of *current_round*."""
    rounds = bracket.get("rounds", [])
    if not isinstance(rounds, list):
        return []
    eliminated = set()
    for r_idx, round_matches in enumerate(rounds[:current_round]):
        if not isinstance(round_matches, list):
            continue
        for match in round_matches:
            if not isinstance(match, dict) or not match.get("played"):
                continue
            winner = str(match.get("winner", ""))
            for pid_key in ("player_a", "player_b"):
                pid = str(match.get(pid_key, ""))
                if pid and pid != winner:
                    eliminated.add(pid)
    # Get all entrants from round 1
    all_players: list[str] = []
    if rounds:
        for match in (rounds[0] or []):
            if not isinstance(match, dict):
                continue
            for pid_key in ("player_a", "player_b"):
                pid = str(match.get(pid_key, ""))
                if pid and pid not in all_players:
                    all_players.append(pid)
    return [p for p in all_players if p not in eliminated]


def format_bracket_lines(bracket: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """Format the bracket as display lines."""
    rounds = bracket.get("rounds", [])
    if not isinstance(rounds, list) or not rounds:
        return ["No bracket data."]

    players = data.get("players", {})

    def get_name(uid: str | None) -> str:
        if not uid:
            return "BYE"
        p = players.get(str(uid), {}) if isinstance(players, dict) else {}
        u = p.get("user", {}) if isinstance(p, dict) else {}
        return str(u.get("name", uid)) if isinstance(u, dict) else str(uid)

    lines = []
    for r_idx, round_matches in enumerate(rounds):
        lines.append(f"**Round {r_idx + 1}**")
        if not isinstance(round_matches, list):
            continue
        for match in round_matches:
            if not isinstance(match, dict):
                continue
            a = get_name(match.get("player_a"))
            b = get_name(match.get("player_b"))
            winner = match.get("winner")
            if match.get("played") and winner:
                w = get_name(winner)
                lines.append(f"  {a} vs {b} → 🏆 {w}")
            else:
                lines.append(f"  {a} vs {b} (pending)")
    return lines
