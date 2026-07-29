# Bot2 Fix Notes

## Battle Block Fix, Persona Cleanup, Rebrand, Dead-Code Purge

Date: 2026-07-29

### Summary

Combined review-driven fixes across both bots plus a full rebrand:

- **Battle engine:** a successful Block subtracted the 20 HP impact penalty from
  the *attacker* (`me`/`my_uid`) instead of the blocker. Now applied to
  `opp`/`opp_uid`, matching `Bot/bot2/BATTLE_MECHANICS.md`. Elimination flow
  re-reads HP after the defense step, so an impact kill still eliminates.
- **Interaction gates:** the 5 cmd/10s rate limiter in `main.py` now runs before
  the restriction/terms gates (which can cost a full `storage.load()` deepcopy),
  and the per-user deque map is pruned past 10k entries.
- **Firebase credentials:** `FIREBASE_CREDENTIALS_JSON` (raw service-account
  JSON) is actually supported again in `get_firestore_client()` — the 2026-07
  docs always claimed it; the revert made them wrong until now.
- **Storage layer:** `with_lock` no longer deep-copies twice (diffs against the
  cache snapshot); `_commit_diff` commits players + global doc in one atomic
  Firestore batch on the common path; set sanitizer preserves element types.
- **Rewards:** `/hourly`, `/daily`, `/weekly`, `/monthly` now honor amounts set
  via `/o_set_*` (they previously read hardcoded/static constants).
- **Trade service:** offer-expiry sweeps triggered by reads are rate-limited to
  once per 60s (repo already filters expired offers client-side).
- **Quick-sell** (pack roll view) now also excludes `market_locked` /
  `trade_locked` cards, not just user/squad locks.
- **Bot1 Ollama client:** keys are sticky on success and rotate only on failure
  (429/error/exception), mirroring the Cerebras/Groq clients.
- **Bot1 jailbreak removal:** `roast_low/medium/extreme` moods, the `/roast`
  command, and the "ALL SAFETY RULES SUSPENDED" prompt-override block were
  removed (exposed via `/mood` **and** `/roast`). Normal moods kept.
- **Dead code removed:** `trade_logic.py` (193 lines, zero callers), empty
  `attacks_owner.py` cog, `build_weapon_instance`, `format_rates_table`,
  `_ensure_inventory_defaults`, `participant_a` param, ~12 stale imports.
- **Launcher:** preflight env checks incl. Firebase credentials variants;
  exponential restart backoff (10s→300s, reset after 60s stable).
- **Rebrand:** Lookism HXCC → **Lookism CG** in all user-facing strings and
  docs. The `HXCC_CLEAR_GLOBAL_COMMANDS_ONCE` env var name is unchanged for
  deployment compatibility.

### Verification

```bash
cd Bot/bot2 && pytest -q   # 162 passed
cd Bot/bot1 && pytest -q   # 10 passed
cd ../.. && pytest tests/ -q  # 13 passed (root suite)
vulture bot/ main.py --min-confidence 90   # clean
```

---


## Pack Inventory and New-Card Stat Lookup Fix

Date: 2026-07-07

### Summary

Fixed two connected runtime issues in the Lookism CG bot:

- Pack rewards were granted into `user["owned_packs"]`, but the pack opener reads
  `user["pack_inventory"]`, making rewarded packs invisible in the packs panel.
- New/custom cards could show `0` power in squad and battle when the inventory
  instance `card_name` matched the card display name but the catalog entry used a
  different storage key.

### Files Updated

- `Bot/bot2/bot/utils/reward_grant.py` now grants pack rewards through
  `pack_logic._add_packs_to_inventory()`, so reward packs are openable.
- `Bot/bot2/bot/features/packs.py` validates pack definitions and eligible cards
  before consuming a pack from `pack_inventory`.
- `Bot/bot2/bot/utils/cards_logic.py` now resolves catalog cards by storage key,
  display `name`, or legacy `card_name`, and includes `special_stat` in the scaled
  stat cache key.
- `Bot/bot2/bot/utils/battle_state.py`, `Bot/bot2/bot/features/battle.py`,
  `Bot/bot2/bot/features/battle_embeds.py`, and `Bot/bot2/bot/features/squad.py`
  now use `find_catalog_card()` for battle/squad card definition lookups instead
  of direct `catalog.get(card_name)` access.

### Verification

```bash
cd Bot/bot2
python3 -m py_compile bot/utils/cards_logic.py bot/utils/battle_state.py bot/features/squad.py bot/features/packs.py bot/utils/reward_grant.py bot/features/battle.py bot/features/battle_embeds.py
pytest -q
```

Output: `172 passed`

---

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
