# ⚔️ Battle System — Complete Technical Reference

> **Source files:** `battle.py` (2922 lines), `battle_state.py` (1371 lines), `battle_views.py` (310 lines), `battle_helpers.py` (230 lines)
> **Supporting:** `typing_matchup.py`, `battle_engine_pdf.py`, `xp_logic.py`
> **Tests:** `test_battle_engine.py` (73 tests), `test_battle_freeze_regressions.py`, `test_typing_matchup.py` (17 tests)

---

## 1. 📦 Data Structures

### Battle State (`create_battle_state()` returns this)
```python
{
    "battle_id": str,               # UUID
    "type": str,                    # "ranked" | "friendly" | "cpu" | "tournament"
    "players": {
        "user_id_1": {
            "team_uids": [str],      # 1-4 fighter instance UIDs
            "current_index": int,    # Active fighter index
            "active_index": int,     # Mirrors current_index
            "hp": {"uid": int},      # Current HP per fighter
            "hp_max": {"uid": int},  # Max HP per fighter
            "stamina": {"uid": int}, # Current stamina per fighter
            "stamina_max": int,      # Always 100
            "stats": {
                "uid": {
                    "strength": int, "speed": int, "endurance": int,
                    "technique": int, "iq": int, "biq": int,
                    "typing": [str],  # e.g. ["Tank", "Fighter"]
                }
            },
            "fighter_names": {"uid": str},
            "mastery_by_uid": {"uid": [str]},
            "assigned_attacks_by_uid": {"uid": {"normal": [str], ...}},
            "passives_by_uid": {"uid": [{"source": str, "name": str, "effect": str}]},
            "is_cpu": bool,
            "swaps_used": int,        # Human: max 1
            "cpu_meta": {} | None,    # For CPU opponents
        }
    },
    "turn_user_id": str,            # Whose turn it is
    "round": int,                   # Increments each turn
    "log": [str],                   # Max 50 entries
    "ended": bool,
    "winner_id": str,
    "coin_reward": int,
    "cpu_trophy_change": int,
    "pvp_trophy_changes": {str: int},
    "winner_xp": int, "loser_xp": int,
    "winner_cp": int, "loser_cp": int,
    "created_at": int,
    "turn_started_at": int,
    "pending_defense_by_char_uid": {uid: move_type},
    "used_defenses_by_char_uid": {uid: [move_type]},
    "used_unique_skills_by_char_uid": {uid: [attack_key]},
    "used_unique_path_by_char_uid": {uid: bool},
    "guard_broken_by_char_uid": {uid: bool},
    "last_move_group_by_side": {pid: "normal_or_defensive"|"special_like"},
}

### Player Side (opponent dictionary passed to calculate_stat_damage)
{
    "strength": int,  "speed": int,  "endurance": int,
    "technique": int, "iq": int,     "biq": int,
    "typing": [str],                 # Normalized type list
    "mastery": [str],                # Mastery types (for strength bonus)
}
```

---

## 2. 📐 Damage Pipeline (7 Steps)

### Step 0: Mastermind Passive
```python
if Mastermind in typing:
    effective_iq  = iq  + 10
    effective_biq = biq + 10
```
Applied to **both** attacker and defender independently.

### Step 1: Miss Check
```python
if effective_attacker_biq < effective_defender_biq:
    miss_chance = clamp(0, 100, def_biq - att_biq)
    if random(1,100) <= miss_chance:
        damage = 0  → return immediately
```
Equal or higher attacker BIQ = never misses.

### Step 2: Base Roll
```python
x = strength / 2
roll = random(lo, hi)

# By move type:
# Normal:         lo=x-5,  hi=x+5
# Special:        lo=x+20, hi=x+45
# Unique Skill:   lo=3x,   hi=4x
# Path:           lo=3x,   hi=4x
```

### Step 3: Strength Bonus
```python
if strength > 100:
    Normal: +20, Special: +30, Unique Skill/Path: +50
elif Strength mastery:
    Normal: +10, Special: +15, Unique Skill/Path: +30
else: +0
```

### Step 4: Technique Multiplier

| TEC | Normal | Special/Unique Skill/Path |
|-----|--------|---------------------------|
| <50 | 1.04 | 1.06 |
| 50-70 | 1.06 | 1.10 |
| 71-90 | 1.08 | 1.12 |
| 91-95 | 1.10 | 1.13 |
| 96+ | 1.15 | 1.18 |

### Step 5: Attacker IQ Scaling
```python
damage *= (1 + effective_attacker_iq / 500)
# At IQ 100 → +20% damage
```

### Step 6: Defender IQ Mitigation
```python
damage *= (1 - effective_defender_iq / 500)
# At IQ 100 → -20% damage
```

### Step 7: Typing Multiplier
```python
# For each (attacker_type, defender_type) pair:
damage *= type_multiplier(att_types, def_types)
damage *= defensive_multiplier(att_types, def_types)
```

---

## 3. 🔤 Type System (`typing_matchup.py`)

### 6 Types
```python
TYPES = ("Tank", "Fighter", "Brawler", "Speedster", "Assassin", "Mastermind")
```

### Offensive Multipliers (attacker → defender)
| Attacker | Defender | Outgoing Damage |
|----------|----------|-----------------|
| Brawler | Fighter | ×1.15 |
| Speedster | Brawler | ×1.30 |
| Assassin | Tank | ×1.30 |
| Fighter | Brawler | ×0.85 (penalty) |
| anything ↔ Mastermind | ×1.00 (neutral) |

### Defensive Multipliers (incoming damage reduction)
| Attacker | Defender | Damage Taken |
|----------|----------|--------------|
| Speedster | Tank | ×0.70 (-30%) |
| Assassin | Fighter | ×0.70 (-30%) |
| Fighter | Brawler | ×0.85 (-15%) |

### Special Rule (Case 4)
```python
if len(A) == 2 and len(D) == 2 and set(A) == set(D):
    all multipliers = 1.00  # Nullification
```

---

## 4. 🛡 Defense System

### Defense Types
| Defense | Condition for 0 Damage | Rejection Condition | Side Effect |
|---------|----------------------|---------------------|-------------|
| **Block** | `def_end > atk_str` | `atk_str - def_end ≥ 30` | Blocker loses 20 HP |
| **Dodge** | `def_spd > atk_spd` | `atk_spd - def_spd ≥ 30` | — |
| **Parry** | (not rejected) | `atk_str - def_end ≥ 30` | Attacker = guard-broken (+50% dmg next hit) |
| **Revert** | `def_tec > atk_str` | `atk_str - def_tec ≥ 30` | Attacker takes recoil = original damage |
| **Tank** | Always partial | — | `damage *= end/(end+str)` (Damage Reduction) |

### Key Constant
```python
REJECTION_THRESHOLD = 30  # stat gap above which defense is rejected
```

### Defense Usage
- Each defense type can be used **once per fighter per battle**
- Exceptions: parry, dodge, tank, block = 1 use each
- Stored in `used_defenses_by_char_uid`

---

## 5. ❤️ HP Calculation

```python
def _build_hp(stats, mastery):
    endurance = stats.get("endurance", 0)
    if "endurance" in mastery:
        multiplier = 8
    else:
        multiplier = 7
    return max(1, endurance * multiplier)
```

### Examples
| Endurance | Mastery | HP |
|-----------|---------|----|
| 50 | None | 350 |
| 50 | Endurance | 400 |
| 100 | Endurance | 800 |

---

## 6. ⚡ Stamina System

### Per-Battle Stamina
- **Start:** 100 stamina per fighter
- **Reset:** Swapping in a fresh fighter resets to 100

### Stamina Costs
| Action | Cost |
|--------|------|
| Normal Attack | 10 |
| Special | 20 |
| Unique Skill | 25 |
| Path | 25 |
| Block/Dodge/Parry/Revert/Tank | 15 |

### Exhaustion
- When stamina ≤ 0, fighter is **exhausted**
- Exhausted = locked to **normal attacks only**
- Cannot use specials, unique skills, path attacks, or defenses

---

## 7. 📊 Trophy & Ranking System

### Rank Thresholds
| Rank | Trophies Required |
|------|------------------|
| Copper | 0-199 |
| Iron | 200-399 |
| Bronze | 400-799 |
| Silver | 800-1,199 |
| Gold | 1,200-1,599 |
| Diamond | 1,600-2,399 |
| Platinum | 2,400-3,199 |
| Sapphire | 3,200-3,999 |
| Ruby | 4,000+ |

### PvP Trophy Delta
```python
# Equal trophies (within 50):
Winner gains 25-40, Loser loses same amount (zero-sum)
# Unequal (higher vs lower):
Higher beats Lower: +20-30 for higher, -20-30 for lower
Lower beats Higher (upset): +30-50 for lower, -30-50 for higher
Draw (equal): both +10
Draw (unequal): higher +10-20, lower loses 0-10
```

### CPU Trophy Delta
```python
# ELO-based with K-factor:
K = 28 if trophies < 500
K = 22 if 500-2000
K = 16 if trophies > 2000

delta = round(K * (1 - expected_win_probability | 0 - expected_win_probability))
```

### Anti-Farm Measures
```python
# After 3 CPU wins in 10 minutes → 50% reduction
# After 6 CPU wins in 10 minutes → 75% reduction
# Daily CPU trophy cap: +100 total (resets at UTC midnight)
```

---

## 8. 🎯 Move Types & Rarity Slots

### Move Types
| Move type    | Description                                              |
|--------------|----------------------------------------------------------|
| Normal       | Standard attack, low cost.                               |
| Special      | Mid-power move with moderate stamina cost.               |
| Unique Skill | High-power move for Legendary/Mythical+ cards (3x–4x scaling). |
| Path         | High-power move exclusive to Infernal/Abyssal cards (3x–4x scaling). |

### Move Slots by Rarity
| Rarity              | Normal | Special | Unique Skill | Path |
|---------------------|--------|---------|--------------|------|
| Common              | 3      | 1       | —            | —    |
| Rare                | 4      | 2       | —            | —    |
| Epic                | 5      | 3       | 1 (if applicable) | —    |
| Legendary / Mythical| 5      | 4       | ✓            | —    |
| Infernal / Abyssal  | 5      | 4       | ✓            | ✓    |

### Unique Skill Usage
- Tracked per fighter in `used_unique_skills_by_char_uid`
- Each unique skill can be used once per battle per fighter

### Path Usage
- Tracked per fighter in `used_unique_path_by_char_uid`
- Can be used once per battle per fighter
- Only available to Infernal/Abyssal rarity cards

---

## 8b. 🔥 Conviction Mastery

When a fighter with **Conviction Mastery** drops to ≤25% HP, their STR, SPD, and END are permanently doubled for the rest of the battle. This triggers once and does not reset.

- **Activation condition:** `current_hp <= hp_max * 0.25`
- **Stats doubled:** `strength`, `speed`, `endurance`
- **One-time trigger** per fighter per battle (tracked by flag)
- Does **not** reset on swap-out or heal

---

## 9. 🤖 CPU Opponents

### CPU Team Building
```python
def _build_cpu_side(data, team_size=4, min_rarity="Rare", player_trophies=0):
    # 1. Pool cards from catalog with stats
    # 2. Select random subset matching team_size
    # 3. Scale stars based on player trophies:
    #    <400:     stars 1-2
    #    400-1200: stars 1-3
    #    1200-2400:stars 2-4
    #    2400+:    stars 3-5
    # 4. Build synthetic UIDs (cpu:Card_Name)
    # 5. Calculate HP, stats, stamina
```

### CPU Move Selection (5 Personalities)
```python
def _cpu_pick_move(personality, available_moves, fighter_hp%, enemy_hp%, stamina):
    if stamina <= 0: return "normal"

    if personality == "Aggressive":   → highest power move available
    if personality == "Defensive":     → block/dodge when damaged
    if personality == "Trickster":     → unpredictable, dodge when healthy
    if personality == "Finisher":      → save unique skill for low enemy HP
    if "Balanced":                     → mixed offense/defense
```

---

## 10. 💰 Battle Rewards

### Coin Rewards
```
Win (PvP or CPU): 50-90 coins (random)
Loss: 0 coins
```

### XP & CP Gains
```python
XP_TABLE = {
    "ranked_win": 200, "ranked_loss": 75,
    "friendly_win": 100, "friendly_loss": 40,
    "tournament_win": 250, "tournament_loss": 100,
}
CP_TABLE = {
    "ranked_win": 50, "ranked_loss": 20,
    "friendly_win": 25, "friendly_loss": 10,
    "tournament_win": 75, "tournament_loss": 30,
}
```

### Event Buffs
```python
if double_xp event active:  xp_gain *= 2
if double_coins event active: cp_gain *= 1.5
```

---

## 11. 🛠 Matchmaking System

### Queue Flow
```
1. Player uses /battle
2. Check: already in battle? → reject
3. Check: has squad? → reject
4. Add to SQLite battle_queue
5. Start 60-second timer
6. Every 10 seconds, try to match:
   - Find other queued player
   - Trophy bracket adaptive window:
     base = 200
     window = base + seconds_waited * 3 (max 500)
   - If matched → create_battle_state(), remove from queue
7. After 60 seconds → fallback to CPU opponent
```

### Friendly Challenge Flow
```
1. Player uses /friendly @user
2. Check: target registered? not already in battle?
3. Create FriendlyInviteView with 60s timeout
4. Send to target's DMs (or channel fallback)
5. Target accepts → create friendly battle
6. Target declines or timeout → cleanup
```

---

## 12. 🎨 Battle UI (3 Embeds)

```
Embed A — Side A Info:
  - Player name + display
  - Active fighter card name, rarity, HP bar, stamina bar, stats
  - Full squad lineup (active, HP status)

Embed B — Side B Info:
  - Same layout as Embed A, for opponent

Embed C — Battle Log:
  - Last 3 action log entries
  - Turn number and timer
```

### Views
- **TurnView:** Attack select (1), Defense select (2), Switch select (3), Forfeit button
- **FriendlyInviteView:** Accept/Decline buttons
- **RankedQueueView:** CPU Battle / Forfeit buttons

### Turn Timer
```
TURN_TIMEOUT = 60 seconds
TURN_VIEW_TIMEOUT = 90 seconds
CPU_STALL_TIMEOUT = 180 seconds
IDLE_SKIP_LIMIT_VS_CPU = 2 (after 2 idle skips, CPU auto-forfeits)
```

---

## ⚠️ Known Bug: Missing IQ/BIQ in cards.json (FIXED)

**Commit:** `f889cf6`

The `cards.json` source file was missing `iq` and `battle_iq` fields in the `stats` object for **all 26 cards**. Only `strength`, `speed`, `endurance`, and `technique` were present.

**Impact on Battle:**
- **Step 1 (Miss Check):** `effective_attacker_biq` was 0, so EVERY attack by ANY card had a chance to miss (and higher-BIQ enemies always got a miss chance)
- **Step 5 (Attacker IQ Scaling):** `iq_bonus = 0 / 500 = 0%` — no damage bonus
- **Step 6 (Defender IQ Mitigation):** `def_iq_reduce = 0 / 500 = 0%` — no damage reduction
- **Mastermind passive:** +10 IQ/BIQ on top of 0 = only 10, instead of e.g. 95+10=105

**Fix:** Correct IQ/BIQ values extracted from `lookism_data.json` and added to all 26 cards. Requires bot restart to clear stat cache.

---

## 13. 🧪 Battle-Specific Tests

### test_battle_engine.py (73 tests)

**Normalization:** 10 tests
- Canonical types, case, whitespace, hyphens, unknown fallback, switch/forfeit

**Damage Calc:** 6 tests
- Basic normal, zero defense, zero power, high defense, special uses TEC, unique skill uses scaling, stat scaling

**Defense Reduction:** 6 tests
- Block (40%), Parry (20%), Revert (60%), Dodge (50% RNG), zero handling, no defense

**Technique Bonus:** 6 tests
- Low/normal/unique skill/special, boundary checks at 50 and 90

**Strength Bonus:** 6 tests
- Low STR no bonus, mastery normal/unique skill, over-100 normal/unique skill, defense type

**HP:** 4 tests
- Basic, endurance mastery, other mastery, minimum

**Rank from Trophies:** 9 parametrized tests
- All 9 rank thresholds

**Move Slot Limits:** 5 tests
- Rarity-based move slot verification

**ELO Delta:** 5 tests
- Equal win/loss, low rank, high rank, underdog bonus

**PvP Delta:** 5 tests
- Equal draw, equal win, higher wins, lower wins, draw with diff

**Stat Damage:** 9 tests
- Returns damage+detail, high BIQ avoids miss, low BIQ can miss, special>normal, unique skill>special, miss=zero, IQ boost, mastery boost

### test_typing_matchup.py (17 tests)
- Normalization (case, caps at 2, unknown dropped, CSV/slash input)
- 1v1 baseline (no relation, Speedster→Tank def only, Assassin→Tank off, Brawler↔Fighter both)
- 2-type vs 1-type cases
- 2-type vs 2-type (stacking, mixed, shared, nullification)
- Mastermind neutrality
- Relations table sanity
