# Rank / League Ordering Fix Notes

Date: 2026-06-13

## Summary

Audited the three rank / league ordering lists in the Discord bot card game and verified
they are all aligned with the trophy-based ground truth.

## Ground Truth

`Bot/bot2/bot/utils/battle_state.py::_rank_from_trophies()` assigns a player's rank
purely from their trophy count. Low-to-high order:

| Rank      | Min Trophies |
|-----------|-------------:|
| Copper    | 0            |
| Iron      | 200          |
| Bronze    | 400          |
| Silver    | 800          |
| Gold      | 1200         |
| Diamond   | 1600         |
| Platinum  | 2400         |
| Sapphire  | 3200         |
| Ruby      | 4000         |

## Audited Files (current state)

1. **`Bot/bot2/bot/data/constants.py`** — `RANK_ORDER`
   ```python
   RANK_ORDER: list[str] = [
       "Copper", "Iron", "Bronze", "Silver", "Gold", "Diamond", "Platinum", "Sapphire", "Ruby",
   ]
   ```
   Matches battle_state ordering. Used by `tournament.py` for `min_rank` gating via
   `RANK_ORDER.index()` comparison.

2. **`Bot/bot2/bot/utils/season_logic.py`** — `LEAGUE_ORDER`
   ```python
   LEAGUE_ORDER = [
       "Copper", "Iron", "Bronze", "Silver", "Gold", "Diamond", "Platinum", "Sapphire", "Ruby",
   ]
   ```
   Matches `RANK_ORDER` exactly. Used by `league_meets()` for season-reward gating
   and by `leaderboards.py` for the `/lb league` autocomplete dropdown.
   The `_rank_from_trophies` helper at the bottom mirrors `battle_state._rank_from_trophies`.

3. **`Bot/bot2/bot/utils/battle_state.py`** — `_rank_from_trophies()` (ground truth, unchanged).

## Verification

```bash
python -c "
from bot.data.constants import RANK_ORDER
from bot.utils.season_logic import LEAGUE_ORDER
assert RANK_ORDER == LEAGUE_ORDER
"
```
Output: `Lists match - OK`

## Phantom Ranks

The original prompt referenced now-removed phantom ranks **Master**, **Grandmaster**,
**Champion** that previously appeared in `LEAGUE_ORDER`. A repo-wide search confirms
no rank-string occurrences of these names remain:

- "Mastermind" — a card *typing*, unrelated.
- "Mastery" / "Master" / "Champion" — appear only inside achievement *names*
  ("Battle Master", "Fusion Master", "Tournament Champion") and the season name
  "Season 1 — Grand Opening Championship". None are used as rank tier values.
- No `"rank": "Master"`, `"rank": "Grandmaster"`, or `"rank": "Champion"` strings
  found in any `.py` or `.json` file.
- No `"required_rank"` references to the phantom ranks.
- No `_rank_from_season_xp` function exists.

## Migration Impact

Any persisted player record that *previously* stored `user.rank` as one of the phantom
strings ("Master", "Grandmaster", "Champion") would now be treated as an unrecognized
rank by `league_meets()` (defaults its index to 0 = Copper) and by tournament gating
(`player_rank in RANK_ORDER` → False, treated as tier 0).

Mitigation: `apply_season_reset_to_players()` in `season_logic.py` recomputes
`user.rank` from trophies on every soft/hard reset via `_rank_from_trophies`, so a
single season rollover will heal any legacy data. Additionally, every battle resolution
in `battle_state.py` (`_resolve_cpu_outcome`, `_resolve_pvp_outcome`) overwrites
`user.rank` from the trophy total. No explicit migration script is required.

## Files Changed in This Audit

None. Both `constants.py` and `season_logic.py` were already in the correct state at
the start of the audit.
