# LOOKISM HXCC — Battle Mechanics Reference

Single source of truth for how stats turn into damage. All numbers here are pulled directly from `bot/utils/battle_state.py` (`calculate_stat_damage`, `_apply_defense_and_finalize_damage`, `_build_hp`, `_get_technique_bonus_multiplier`, `_strength_bonus`) and `bot/utils/typing_matchup.py`. If this file disagrees with code, code wins — patch this file.

---

## 1. Card stats

Every card has six stats on a 0–100 scale (stored under `card["stats"]`):

| Stat        | Key         | Role                                                              |
|-------------|-------------|-------------------------------------------------------------------|
| Strength    | `strength`  | Base damage roll (most weight).                                   |
| Speed       | `speed`     | Powers Dodge defense; resists Dodge rejection.                    |
| Endurance   | `endurance` | Drives HP pool; powers Block/Tank/Parry defenses.                 |
| Technique   | `technique` | Damage multiplier band per move type.                             |
| IQ          | `iq`        | Offense scaling and defensive IQ mitigation.                      |
| Battle IQ   | `biq`       | Drives miss chance and resists missing.                           |

Plus card-level fields used by the pipeline:

- `rarity` — Common → Abyssal (caps stats via `stats_max`)
- `stars` — 0–5, scales stats via `compute_scaled_stats`
- `mastery` — one of `Strength / Speed / Endurance / Technique / IQ / BIQ / None`
- `typing` — list of 1–2 of `Tank / Fighter / Brawler / Speedster / Assassin / Mastermind`
- `moves` — Normal / Special / Unique Skill / Ultimate / Path Attack pools

---

## 2. HP

`_build_hp(stats, mastery)` in `battle_state.py:150`:

```
HP = endurance × multiplier
multiplier = 8  if card has "Endurance" mastery
            = 7  otherwise
```

So at endurance 100 with Endurance mastery, HP = 800; without, HP = 700.

---

## 3. Damage pipeline (turn-by-turn)

The whole pipeline lives in `calculate_stat_damage` (`battle_state.py:348`). Order matters.

### Step 0 — Mastermind passive

If the card's `typing` includes `Mastermind`, treat:

```
effective_iq  = iq  + 10
effective_biq = biq + 10
```

Applied on **both** sides — Mastermind attacker AND Mastermind defender enjoy the bonus.

Source: `bot/utils/typing_matchup.py` → `MASTERMIND_IQ_BONUS = 10`, `MASTERMIND_BIQ_BONUS = 10`.

### Step 1 — Miss check (BIQ vs BIQ)

```
if effective_attacker_biq < effective_defender_biq:
    miss_chance = clamp(0, 100, def_biq - att_biq)   # percent
    roll = randint(1, 100)
    if roll <= miss_chance:
        damage = 0  →  return immediately
```

Equal or higher attacker BIQ never misses.

### Step 2 — Base roll (Strength × move type)

Let `x = strength / 2`. Roll a uniform integer in `[lo, hi]`:

| Move type          | lo            | hi              |
|--------------------|---------------|-----------------|
| Normal             | `x − 5`       | `x + 5`         |
| Special            | `x + 20`      | `x + 45`        |
| Ultimate           | `3x`          | `4x`            |
| Unique Skill / Path| `x + 40`      | `x + 80`        |

Result floored at 1.

### Step 3 — Strength bonus (flat)

Only fires if strength > 100 OR card has `Strength` mastery (`_strength_bonus`, `battle_state.py:330`):

| Move type          | No mastery (str>100) | With Strength mastery |
|--------------------|----------------------|------------------------|
| Normal             | +5                   | +10                    |
| Special / Unique   | +10                  | +15                    |
| Ultimate           | +20                  | +30                    |

### Step 4 — Technique multiplier (bands)

`_get_technique_bonus_multiplier(technique, move_type)`:

| technique | Normal | Special / Unique | Ultimate |
|-----------|--------|------------------|----------|
| <50       | 1.04   | 1.06             | 1.10     |
| 50–70     | 1.06   | 1.10             | 1.13     |
| 71–90     | 1.08   | 1.12             | 1.15     |
| 91–95     | 1.10   | 1.13             | 1.18     |
| 96+       | 1.15   | 1.18             | 1.30     |

### Step 5 — Attacker IQ scaling

```
damage *= 1 + (effective_attacker_iq / 500)
```

(Implemented as `iq_bonus = iq / 5.0`, then `× (1 + iq_bonus/100)`. Same thing.)
At IQ 100 → +20% damage. At IQ 50 → +10%.

### Step 6 — Defender IQ mitigation

```
damage *= 1 − (effective_defender_iq / 500)
```

At defender IQ 100 → −20%. Symmetric to step 5.

### Step 7 — Typing offensive multiplier

`type_multiplier(attacker.typing, defender.typing)` from `bot/utils/typing_matchup.py`. Look up every (attacker_type, defender_type) pair in this table; multiply the matches into `damage`:

| Attacker → Defender   | Multiplier |
|-----------------------|------------|
| Brawler  → Fighter    | ×1.15      |
| Speedster → Brawler   | ×1.30      |
| Assassin → Tank       | ×1.30      |
| Fighter  → Brawler    | ×0.85      |
| anything ↔ Mastermind | ×1.00      |
| no relation           | ×1.00      |

**Special case (Case 4):** if attacker and defender share the **exact same** two-type set (e.g. both are `[Brawler, Speedster]`), the multiplier is forced to 1.00 (nullification).

### Step 8 — Typing defensive multiplier

`defensive_multiplier(attacker.typing, defender.typing)`. Same pair-product logic, different table — these reductions land **on the defender**:

| Attacker → Defender | Multiplier |
|---------------------|------------|
| Speedster → Tank    | ×0.70 (Tank takes 30% less)    |
| Assassin  → Fighter | ×0.70 (Fighter takes 30% less) |
| Fighter   → Brawler | ×0.85 (Brawler takes 15% less) |
| anything else       | ×1.00                          |

Identical-set rule also applies here.

### Step 9 — Defense reaction (if the defender queued one)

`_apply_defense_and_finalize_damage` (`battle_state.py:635`). The defender may have set a pending defense move last turn. `REJECTION_THRESHOLD = 30` means defenses **fail** when the attacker's relevant stat is 30+ higher than the defender's gating stat.

| Defense | Condition to take **0 damage**            | Rejected if                    | Side effect |
|---------|-------------------------------------------|--------------------------------|-------------|
| Block   | `def_end > atk_str`                       | `atk_str − def_end ≥ 30`       | Blocker still loses 20 HP from the impact. |
| Dodge   | `def_spd > atk_spd`                       | `atk_spd − def_spd ≥ 30`       | — |
| Parry   | (not rejected)                            | `atk_str − def_end ≥ 30`       | Attacker is **guard-broken** → next hit on them gets a flag (engine consumes it). |
| Revert  | `def_tec > atk_str` (damage reflected)    | `atk_str − def_tec ≥ 30`       | Attacker takes the original damage as recoil. |
| Tank    | always partial — `damage *= end/(end+str)` | —                              | Pure DR; never zeroes. |

### Final

```
final_damage = max(0, round(damage))
```

Logged into `detail` dict with keys: `miss`, `base_roll`, `strength_bonus`, `technique_mult`, `attacker_iq_bonus_pct`, `defender_iq_reduce_pct`, `typing_mult`, `typing_defensive_mult`, `attacker_typing`, `defender_typing`, `final_damage`.

---

## 4. Worked examples

### Example A — straightforward normal punch

- Attacker: STR 100, TEC 90, IQ 70, BIQ 60, `typing = [Fighter]`, no mastery
- Defender: END 90, IQ 50, BIQ 60, `typing = [Assassin]`

```
1. Miss check          : att_biq == def_biq → no miss
2. Base roll (normal)  : strength/2 = 50 → roll in [45, 55] → say 50
3. Strength bonus      : str > 100? no, no mastery → +0
4. Technique (90,norm) : ×1.08            → 54.0
5. Attacker IQ (70)    : ×(1 + 70/500)=1.14 → 61.56
6. Defender IQ (50)    : ×(1 − 50/500)=0.90 → 55.4
7. Typing offense      : Fighter→Assassin = ×1.00 → 55.4
8. Typing defense      : Fighter→Assassin (defensive table) = ×1.00 → 55.4
9. Defense reaction    : none queued
→ final ≈ 55 damage
```

### Example B — counter matchup (Speedster slamming Brawler)

- Attacker: STR 90, TEC 85, IQ 80, BIQ 70, `typing = [Speedster]`
- Defender: END 80, IQ 70, BIQ 60, `typing = [Brawler]`, Special move

```
2. Base roll (special) : x=45, lo=65 hi=90 → say 80
3. Strength bonus      : no mastery, str≤100 → +0
4. Technique (85,spec) : ×1.12              → 89.6
5. Att IQ 80           : ×1.16              → 103.9
6. Def IQ 70           : ×0.86              → 89.3
7. Typing offense      : Speedster→Brawler  ×1.30 → 116.1
8. Typing defense      : Speedster→Brawler  ×1.00 → 116.1
→ final ≈ 116 damage  (a clean 30% bump from typing)
```

### Example C — Mastermind support

- Attacker: STR 100, TEC 80, IQ 60, BIQ 50, `typing = [Mastermind]`
- Defender: STR/END 90, IQ 60, BIQ 50, `typing = [Fighter]`

```
Step 0 : Mastermind → effective att IQ=70, att BIQ=60
                       effective def IQ=60 (no mastermind on def)
Step 5 : ×(1 + 70/500) = ×1.14   (not 1.12 — the +10 IQ kicked in)
Step 6 : ×(1 − 60/500) = ×0.88
Step 7 : Mastermind has no relations → ×1.00
```

So Mastermind = ~+2% damage out, ~+2% miss-defense, on every swing.

### Example D — dual-typing nullification

- Attacker `typing = [Speedster, Brawler]`
- Defender `typing = [Brawler, Speedster]`
- Step 7 short-circuits: identical type set → ×1.00.
- Step 8 same → ×1.00. Vanilla damage exchange — neither side gets a typing edge.

---

## 5. The state object passed to `calculate_stat_damage`

`attacker` / `defender` are dicts with these keys (built in `_build_player_side` / `_build_cpu_side`):

```python
{
    "strength":  int,
    "speed":     int,
    "endurance": int,
    "technique": int,
    "iq":        int,
    "biq":       int,
    "typing":    list[str],   # 0..2 entries from TYPES
    "mastery":   list[str],   # injected by caller for strength-bonus check
}
```

If `typing` is missing or empty, both typing steps return ×1.00 — backward compatible with cards that haven't been tagged yet.

---

## 6. Where to balance what

| You want to change…           | Edit this                                                                  |
|-------------------------------|-----------------------------------------------------------------------------|
| Move-type ranges (lo/hi)      | `calculate_stat_damage` step 2 in `battle_state.py:368`                     |
| Strength bonus values         | `_strength_bonus` in `battle_state.py:330`                                  |
| Technique bands               | `_get_technique_bonus_multiplier` in `battle_state.py:49`                   |
| IQ scaling slope              | constants `/ 500` in steps 5 & 6 of `calculate_stat_damage`                 |
| Typing matchup multipliers    | `_OFFENSIVE` / `_DEFENSIVE` dicts in `bot/utils/typing_matchup.py`          |
| Mastermind passive            | `MASTERMIND_IQ_BONUS` / `MASTERMIND_BIQ_BONUS` in `typing_matchup.py`       |
| Defense rejection threshold   | `REJECTION_THRESHOLD` in `battle_state.py:27`                               |
| HP multiplier (endurance × N) | `_build_hp` in `battle_state.py:150`                                        |

---

## 7. Tests

- `tests/test_battle_engine.py` — base damage pipeline (73 tests, frozen behaviour).
- `tests/test_typing_matchup.py` — 17 tests covering every spec case for typings.

Run everything: `pytest -q` from `Bot/bot2/`.
