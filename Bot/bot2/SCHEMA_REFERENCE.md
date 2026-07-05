# LOOKISM HXCC — Schema Reference

Single source of truth for all data structures, constants, formulas, and thresholds. If the code disagrees with this file, the code wins — patch this file.

---

## Rarity System

### Rarity Rank (index = tier)

```python
RARITY_RANK = ["Common", "Rare", "Epic", "Legendary", "Mythical", "Infernal", "Abyssal"]
```

### Per-Star Flat Stat Bonus

| Rarity | Bonus per star per stat |
|---|---|
| Common, Rare, Epic | +1 |
| Legendary, Mythical, Infernal, Abyssal | +2 |

### Upgrade Base Costs

| Rarity | Cost |
|---|---|
| Common | 500 |
| Rare | 1,200 |
| Epic | 3,000 |
| Legendary | 6,000 |
| Mythical | 9,000 |
| Infernal | 14,000 |
| **Abyssal** | **20,000** |

Cost formula: `int(round(base * 1.6 ** current_stars))`

### Market Price Bands (min–max)

| Rarity | Price Band |
|---|---|
| Common | 500 – 1,000 |
| Rare | 3,000 – 5,000 |
| Epic | 10,000 – 20,000 |
| Legendary | 30,000 – 40,000 |
| Mythical | 50,000 – 60,000 |
| Infernal | 70,000 – 80,000 |
| Abyssal | 90,000 – 100,000 |

### Instant Sell Values

| Rarity | Payout |
|---|---|
| Common | 250 |
| Rare | 1,000 |
| Epic | 5,000 |
| Legendary | 20,000 |
| Mythical | 40,000 |
| Infernal | 60,000 |
| Abyssal | 80,000 |

---

## Card Catalog Schema (`data["cards"]`)

Keyed by unique storage name (e.g. `"Gun Park Shiro Oni"`). Each value:

```python
{
    # Identity
    "name": str,                    # Display name, e.g. "Gun Park"
    "title": str,                   # Subtitle/epithet, e.g. "Shiro Oni"
    "description": str,             # Flavor/lore text
    "rarity": str,                  # One of RARITY_RANK

    # Stats (0–100 base)
    "stats": {
        "strength": int,
        "speed": int,
        "endurance": int,
        "technique": int,
        "iq": int,
        "battle_iq": int,
    },

    "image_url": str,               # Discord CDN image URL
    "emoji": str,                   # Display emoji (default "🃏")

    # Mastery
    "mastery": {"type": str|None, "description": str},
    # Possible mastery types: "Strength", "Speed", "Endurance",
    #   "Technique", "IQ", "BIQ"

    # Combat
    "typing": list[str],            # 0-2 entries from TYPES
    "attacks": list[str],           # Attack keys assigned

    # Equipment
    "weapon_user": bool,            # Can equip weapons (default False)

    # Special stat (Abyssal cards)
    "special_stat": str|None,       # One of the 6 stat keys, or None
    # When set, that stat = 100 at stars 0-4, 110 at star 5

    # Keystone
    "keystone_name": str|None,      # Linked keystone (Mythical+ only)

    # Skills (unlock at star 3/4/5 depending on count)
    "unique_skill": {               # Unlocks at star 3
        "name": str,
        "description": str,
        "active": bool,
    }|None,
    "unique_skill_2": {             # Unlocks at star 4
        "name": str,
        "description": str,
        "active": bool,
    }|None,
    "unique_skill_3": {             # Unlocks at star 5
        "name": str,
        "description": str,
        "active": bool,
    }|None,

    # Path (always unlocks at star 5)
    "unique_path": {
        "name": str,
        "description": str,
        "active": bool,
    }|None,

    # Dialogue
    "default_dialogue": str,        # "The fighter stays focused."
    "unique_skill_dialogue": str,
    "unique_path_dialogue": str,
}
```

**Card counts:** 122 total — 38 Common, 35 Rare, 29 Epic, 13 Legendary, 5 Mythical, 1 Infernal, 1 Abyssal.

---

## Inventory Item Schema (Card Instance)

Created by `build_card_instance()` in `cards_logic.py:370`. Each entry in `player["user"]["inventory"]`:

```python
{
    "uid": str,                     # uuid4 hex
    "card_name": str,               # Card display name (NOT the catalog key)
    "rarity": str,
    "stars": int,                   # 0–5
    "locked": bool,                 # User-applied lock
    "market_locked": bool,          # Currently listed on market
    "squad_locked": bool,           # Currently in squad
    "favourite": bool,              # User favorited
    "trade_locked": bool,           # In pending trade (runtime, added by ensure_structure)
    "acquired_at": int,             # Unix timestamp
    "weapon_uid": str|None,         # Equipped weapon UID
    "keystone_equipped": bool,      # Keystone toggled on
    "keystone_skill_name": str|None,# Keystone ability name (runtime)
}
```

**Note:** Instances use `card_name` as the key. The catalog uses a different key. Always use `find_catalog_card()` (not raw `catalog.get()`) to look up the definition.

---

## Weapon System

### Weapon Instance (`weapon_logic.py:21`)

```python
{
    "uid": str,                     # uuid4
    "weapon_name": str,             # From weapon def
    "rarity": str,
    "stars": int,                   # 0–5
    "locked": bool,
    "equipped_to": str|None,        # Card UID
    "acquired_at": int,             # Unix timestamp
}
```

### Weapon Definition (`data["weapons"]`)

```python
{
    "name": str,
    "rarity": str,
    "image_url": str,
    "emoji": str,
    "compatible_cards": list[str],  # Empty = compatible with all weapon_users
    "stat_buffs": dict,             # e.g. {"strength": 20, "speed": 10}
    "effect": str,                  # Flavor text
    "effect_active": bool,          # True = active ability
}
```

### Weapon Buff Calculation

Same flat bonus as card logic (per rarity):
- Common/Rare/Epic: +1 per star
- Legendary+: +2 per star

```python
total_buff = base_buff + (flat_bonus_per_star * stars)
# For negative buffs, absolute bonus is subtracted.
```

Equipped weapon must match `weapon_user=True` on card (or be in `compatible_cards`). Cannot upgrade while equipped.

---

## Keystone System

Mythical+ cards only. Stored in `data["keystones"]`:

```python
{
    "name": str,                    # Display name
    "effect": str,                  # Effect description
    "character": str,               # Associated character
    "active": bool,                 # True = active, False = passive
}
```

Linked via `card_def["keystone_name"]`. Runtime toggle: `instance["keystone_equipped"]`. Passive keystone effect in battle: +10% to all stats.

---

## Player Schema

Full player dict (created by `build_default_player()` in `defaults.py:334`):

```python
{
    "user": {
        # Identity
        "id": str,                  # Discord user ID
        "name": str,                # Display name
        "registered_at": int,       # Unix timestamp
        "tos_accepted": bool,

        # Economy
        "balance": int,             # Coins (primary key; "coins" is legacy alias)
        "premium_balance": int,     # Gems
        "is_premium": bool,

        # Inventory
        "inventory": list[dict],    # Card instances (see above)
        "weapon_inventory": list[dict],  # Weapon instances

        # PvP
        "trophies": int,
        "rank": str,                # One of RANK_ORDER

        # Profile
        "profile": {
            "bio": str,
            "background_url": str,
            "showcase_uid": str,
            "cosmetics": {
                "theme": str,
                "border_id": str,
                "badge_id": str,
            },
        },
        "privacy_settings": {
            "show_balance": bool,
            "show_trophies": bool,
            "show_gang": bool,
        },

        # Cooldowns
        "cooldowns": {
            "hourly": int,          # Unix timestamp
            "daily": int,
            "weekly": int,
            "monthly": int,
        },

        # Tutorial
        "tutorial": {"step": int, "completed": bool},

        # XP/Level
        "xp": int,                  # Total XP (permanent, never resets)
        "level": int,               # 1–100
        "pending_milestone_packs": list[str],

        # Packs
        "pack_inventory": list[dict],   # [{key, name, acquired_at}]
        "owned_packs": dict[str, int],  # pack_key → quantity
        "pity": dict,                   # Per-pack pity counters

        # Season
        "season_cp": dict[str, int],    # season_number → CP
        "season_pass_paid": dict[str, bool],
        "season_pass_claimed": dict[str, list[str]],

        # War
        "war_preference": str,          # "in" | "out"
        "war_defense_squad": list[str], # Card UIDs
        "war_cooldown_until": int,
    },

    "gang_id": str|None,
    "alliance_id": str|None,

    "squad": {
        "active": list[str],        # Card UIDs (max 4)
        "backup": list[str],        # Card UIDs
        "supervisor": str,          # Card UID
    },

    "ranked_stats": {
        "wins": int,
        "losses": int,
        "streak": int,
        "last_10": list,            # Recent battle results
    },

    "rival": {
        "rival_id": str|None,
        "rival_name": str,
        "losses_to": int,
        "wins_vs": int,
    },

    "achievements": {"earned": dict},   # achievement_id → 1
    "achievement_points": int,

    "market": {"active_listing_ids": list[str]},
    "trade_history": list[dict],

    "season_claims": dict,              # season → reward_id → claimed
    "season_pass": {                    # Legacy; replaced by season_cp
        "season": int, "xp": int, "level": int, "claimed": dict,
    },
    "packs": {"opened": int, "spent": int},
    "pity": dict,
    "redeemed_codes": dict,             # code → timestamp
}
```

---

## Trophy / Rank System

### Thresholds

| Rank | Min Trophies |
|---|---|
| Copper | 0 |
| Iron | 200 |
| Bronze | 400 |
| Silver | 800 |
| Gold | 1,200 |
| Diamond | 1,600 |
| Platinum | 2,400 |
| Sapphire | 3,200 |
| Ruby | 4,000 |

```python
RANK_ORDER = ["Copper", "Iron", "Bronze", "Silver", "Gold",
              "Diamond", "Platinum", "Sapphire", "Ruby"]
```

### PvP Trophy Delta

| Scenario | Delta |
|---|---|
| Same-bracket gap | 50 trophies |
| Same-rank win | 25–40 |
| Draw | 10 |
| Upset (underdog win) | 30–50 |
| Favourite win | 20–30 |

### ELO Constants

| Parameter | Value |
|---|---|
| K (default) | 22 |
| K (below 500 trophies) | 28 |
| K (above 2000 trophies) | 16 |
| Denominator | 400 |
| Win clamp | 4–22 |
| Loss clamp | -4 to -22 |

### Anti-Farm

| Condition | Trophy Multiplier |
|---|---|
| 3+ wins in 10-min rolling window | 0.5× |
| 6+ wins in 10-min rolling window | 0.25× |
| Daily CPU cap | 100 trophies |

### CPU Difficulty

| Player Trophies | CPU Star Range |
|---|---|
| < 400 | 1–2 |
| < 1,200 | 1–3 |
| < 2,400 | 2–4 |
| ≥ 2,400 | 3–5 |

---

## Battle System

### Stamina

| Action | Cost |
|---|---|
| Normal Attack | 10 |
| Special | 20 |
| Ultimate | 35 |
| Unique Skill / Path | 25 |
| Block / Dodge / Parry / Revert / Tank | 15 |

Base stamina per fighter: **100**. Exhausted (≤0) → locked to normal attacks only. Switching resets to 100.

### Defense Rejection

Threshold: stat gap of **30** between attacker's relevant stat and defender's gating stat causes defense to be rejected (damage is not reduced).

| Defense | Gate Condition | Rejected When |
|---|---|---|
| Block | def_end > atk_str | atk_str − def_end ≥ 30 |
| Dodge | def_spd > atk_spd | atk_spd − def_spd ≥ 30 |
| Parry | — | atk_str − def_end ≥ 30 |
| Revert | def_tec > atk_str | atk_str − def_tec ≥ 30 |
| Tank | always partial | — |

### Typing Matchups

**Types:** Tank, Fighter, Brawler, Speedster, Assassin, Mastermind

**Offensive multipliers:**
| Attacker → Defender | × |
|---|---|
| Brawler → Fighter | 1.15 |
| Speedster → Brawler | 1.30 |
| Assassin → Tank | 1.30 |
| Fighter → Brawler | 0.85 |
| Mastermind ↔ any | 1.00 |

**Defensive multipliers:**
| Attacker → Defender | × |
|---|---|
| Speedster → Tank | 0.70 |
| Assassin → Fighter | 0.70 |
| Fighter → Brawler | 0.85 |

**Nullification rule:** If attacker and defender share the exact same two-type set, all multipliers are forced to 1.00.

### Mastermind Passive

- IQ +10
- BIQ +10
- Applied on both sides (attacker AND defender)

### Card of the Day

- +15% damage if fighter matches COTD

### HP Formula

```
HP = endurance × 7
HP = endurance × 8  (with Endurance mastery)
```

### Battle XP/CP

| Outcome | XP | CP |
|---|---|---|
| Ranked win | 200 | 50 |
| Ranked loss | 75 | 20 |
| Friendly win | 100 | 25 |
| Friendly loss | 40 | 10 |
| Tournament win | 250 | 75 |
| Tournament loss | 100 | 30 |

### CPU Win Coin Reward

50–90 coins per win.

---

## XP / Level System

### Formula

```python
def xp_for_level(level):
    return sum(500 * 1.2 ** (lvl - 2) for lvl in range(2, level + 1))

def xp_to_next_level(level):
    return 500 * 1.2 ** (level - 1)
```

Max level: **100**. XP is permanent (never resets across seasons).

### Level Milestones

| Level | Reward |
|---|---|
| 5 | 500 coins, Amateur Pack |
| 10 | 1,000 coins, Basic Pack |
| 15 | 1,500 coins, Basic Pack |
| 20 | 2,000 coins, Intermediate Pack |
| 25 | 2,500 coins, Intermediate Pack |
| 30 | 3,000 coins, Experienced Pack |
| 40 | 5,000 coins, Veteran Pack, 10 gems |
| 50 | 10,000 coins, Veteran Pack, 25 gems |
| 75 | 15,000 coins, 50 gems |
| 100 | 20,000 coins, 100 gems |

---

## Upgrade System (Card Stars)

### Star Upgrade

- Cards start at **0 stars**, max **5 stars**.
- Each star requires **1 duplicate card** (same `card_name`, different `uid`).
- Cost formula: `int(round(base_cost * 1.6 ** current_stars))`
- Safe duplicate filter checks: different UID, not squad_locked, not market_locked, not user-locked, not trade_locked, not weapon-equipped.

### Skill Unlock by Star

| Unique Skills Count | Star 3 | Star 4 | Star 5 |
|---|---|---|---|
| 1 skill | skill_1 | — | — |
| 2 skills | skill_1 | skill_2 | — |
| 3 skills | skill_1 | skill_2 | skill_3 |

`unique_path` always unlocks at **star 5** regardless of skill count.
Ultimates per team: 1 for 1-2 members, 2 for 3 members, 3 for 4+ members.

---

## Market Schema

### Listing

```python
{
    "id": str,                  # uuid4
    "card_name": str,
    "card_uid": str,            # Card instance UID
    "rarity": str,
    "price": int,
    "seller_id": str,           # Discord user ID
    "seller_name": str,
    "arc": str,                 # "—" or arc name
    "image_url": str,
    "listed_at": int,
    "expires_at": int,          # 7 days (604800s)
    "sold": bool,
    "stock": int,               # -1 = unlimited
}
```

### Featured / Special Offer

Same as listing plus:
```python
{
    "seller_id": "owner",
    "seller_name": "HXCC Staff",
}
```

### Settings

```python
{
    "enabled": bool,
    "fee_percent": int,             # 5% default
    "max_listings_per_user": int,   # 10 default
    "quick_sell_values": dict,      # rarity → payout
    "price_band": dict,             # rarity → {min, max}
}
```

### Seller Payout

```python
payout = price - int(price * fee_percent / 100)
```

---

## Trade Schema

### Trade Offer

```python
{
    "trade_id": str,            # uuid4 (first 8 chars = offer ID)
    "initiator_id": str,        # Discord user ID
    "target_id": str,           # Discord user ID
    "offer_uids": list[str],    # Card UIDs from initiator
    "request_uids": list[str],  # Card UIDs from target
    "created_at": int,
    "status": str,              # "pending" | "completed" | "declined" | "cancelled" | "expired"
    "completed_at": int,        # Set when completed
}
```

TTL: **86,400s** (24h). UI timeout: **600s** (10min).

---

## Gang Schema

### Gang

```python
{
    "gang_id": str,             # uuid4
    "name": str,                # 1-32 chars
    "leader_id": str,           # Discord user ID
    "members": list[str],       # Discord user IDs
    "roles": dict,              # user_id → role string
    "description": str,         # max 200 chars
    "status": str,              # "open" | "closed"
    "wins": int,
    "losses": int,
    "created_at": int,
    "alliance_id": str|None,
}
```

### Gang Roles (priority order)

`head` > `vice` > `recruiter` > `elder` > `member`

Max members: **20**. Creation cost: **10,000 coins**.

### Invite

```python
{
    "invite_id": str,           # uuid4
    "gang_id": str,
    "from_id": str,             # Inviter
    "to_id": str,               # Invitee
    "created_at": int,
    "expires_at": int,          # 10 minutes
    "status": str,              # pending | accepted | declined | expired
}
```

---

## Alliance Schema

### Alliance

```python
{
    "alliance_id": str,         # uuid4
    "name": str,
    "leader_gang_id": str,
    "gang_ids": list[str],      # Max 5
    "created_at": int,
}
```

Create/join cooldown: **86,400s** (24h).

### Invite

```python
{
    "invite_id": str,
    "alliance_id": str,
    "from_gang_id": str,
    "to_gang_id": str,
    "from_id": str,             # Head of from_gang
    "to_id": str,               # Head of to_gang
    "created_at": int,
    "expires_at": int,
    "status": str,
}
```

---

## Season Schema

### Season Config (`data["season"]`)

```python
{
    "active": bool,
    "current_season": int,
    "name": str,
    "start_time": int,
    "end_time": int,
    "reset_type": str,          # "both" | "hard" | "soft"
    "pass_tiers": dict,         # tier_number → {cp_required, free_reward, paid_reward}
    "missions": dict,           # mission_id → mission config
}
```

15 pass tiers per season. `cp_required` ranges from 100 (tier 1) to 12,000 (tier 15).
Pass cost: **200 gems**.

### Season Data (`data["season_data"]`)

```python
{
    "current_season": int,
    "start_time": int,
    "end_time": int,
    "reset_type": str,
    "soft_reset_percent": int,      # 50
    "global_rewards": list,
    "season_rewards": dict,
    "season_reward_distributed": bool,
    "archived_seasons": dict,
    "season_pass_rewards": dict,
}
```

### Pass XP Formula

```python
XP_PER_LEVEL = 100
level = xp // 100 + 1
```

### Reset Types

| Type | Effect |
|---|---|
| `"hard"` | trophies → 0, rank → Copper |
| `"soft"` | `new_trophies = int(trophies * 50 / 100)`, rank recalculated |
| Always | `ranked_stats` reset to `{wins:0, losses:0, streak:0, last_10:[]}` |

### Mission Periods

daily (UTC day), weekly (ISO week), monthly (UTC month), season (season duration).

---

## Achievement Schema

### Catalog Entry

```python
{
    "id": str,              # Unique key, e.g. "first_blood"
    "name": str,            # Display name
    "desc": str,            # Description
    "tier": str,            # "Bronze" | "Silver" | "Gold" | "Diamond"
    "icon_key": str,        # Emoji reference key
    "points": int,          # Achievement points awarded
}
```

### Player Storage

```python
player["achievements"] = {"earned": {"achievement_id": 1, ...}}
player["achievement_points"] = int  # Sum of all earned
```

**Total: 27 achievements**, 10–2000 points each.

---

## Data Flow

### Boot-Time Data Initialization

1. `main.py` calls `build_default_data()` → `ensure_structure()`
2. `build_default_data()` loads `data/cards.json`, `data/defaults.py` constants
3. `ensure_structure()` normalizes every card definition (adds defaults, fixes keys)
4. `_sync_catalog_cards()` merges current `cards.json` into existing `lookism_data.json`:
   - New cards are added to `data["cards"]`
   - Existing cards are NOT overwritten (preserves edits)
   - Deleted cards are NOT removed from existing data
5. SQLite services (market, trade, battle) are bootstrapped from JSON state

### Catalog Key vs Card Name

The catalog (`data["cards"]`) is keyed by storage keys (e.g. `"Diego Kang Idol of PTJ Company"`). Card `name` fields are shorter (e.g. `"Diego Kang"`). When looking up a card by name, always use `find_catalog_card()` which:
1. Tries exact key match first
2. Falls back to case-insensitive name match across all card values

### State File

`lookism_data.json` is the primary state file. It contains everything: players, cards, gangs, market, season, etc. The storage layer provides thread-safe reads/writes with atomic file replacement on save.

---

## Economy Constants

| Item | Value |
|---|---|
| Gang creation cost | 10,000 coins |
| Market fee | 5% |
| Max listings per user | 10 |
| Listing duration | 7 days (604,800s) |
| Trade TTL | 24h (86,400s) |
| Trade UI timeout | 10 min (600s) |
| Alliance cooldown | 24h (86,400s) |
| Gang invite expiry | 10 min |
| ELO K (default) | 22 |
| ELO K (<500 trophies) | 28 |
| ELO K (>2000 trophies) | 16 |
| Defense rejection stat gap | 30 |
| Season pass cost | 200 gems |

---

## Common Pitfalls

| Issue | Cause | Fix |
|---|---|---|
| Card shows name but no stats in collection | `_get_card_def()` used `catalog.get()` which fails when catalog key ≠ card name | Use `find_catalog_card()` |
| Trade can't find card | Searching by `"name"` but instances use `"card_name"` | Check both: `item.get("card_name", item.get("name", ""))` |
| Storage deepcopy on every command | `server_rules.py` called `storage.load()` (full deepcopy) in `interaction_check` | Use `storage.load_readonly()` for read-only checks |
| Upgrade consumes protected card | Dup filter didn't check `locked`, `trade_locked`, `weapon_uid` | Add all safety checks to the filter |
| Abyssal costs less than Infernal | Upgrade cost tables had values swapped | Abyssal should cost more than Infernal |
| Missing `user` key crash | `data["players"][id]["user"]` accessed directly | Chain `.get()` calls safely |
