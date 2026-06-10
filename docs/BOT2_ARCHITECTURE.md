# 🎮 Bot2: Lookism HXCC — Complete Architecture

> **Role:** Full-featured gacha game bot with cards, battles, economy, social systems
> **Files:** `Bot/bot2/` (70+ source files, 17 test files, 127 tests)
> **Entry:** `main.py` → `LookismBot` class

---

## 1. 📁 Complete File Inventory

### Core
| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | ~390 | Bot bootstrap, 32 cogs, SQLite bootstrap, command sync |
| `bot/config.py` | ~20 | **⚠️ HARDCODED TOKEN**, owner IDs, paths |

### Data Layer (`bot/data/`)
| File | Lines | Purpose |
|------|-------|---------|
| `storage.py` | ~160 | Thread-safe JSON storage with cache |
| `sqlite_store.py` | ~700 | SQLite repos: Market, Trade, Battle |
| `supabase_sync.py` | ~70 | Background Supabase sync |
| `constants.py` | ~80 | Ranks, prices, icons, colors |
| `defaults.py` | ~600 | Complete default game state |
| `schemas.py` | ~100 | TypedDict definitions |
| `cards.json` | ~2600 | 26 card definitions |

### Features (`bot/features/`)
| File | Lines | Complexity |
|------|-------|------------|
| `battle.py` | 2922 | **HIGHEST** — queue, turn system, CPU AI, rewards |
| `battle_views.py` | 310 | UI components (selects, buttons, views) |
| `battle_helpers.py` | 230 | CPU AI personalities, move normalization |
| `packs_panel.py` | 590 | Pack animation, open/reveal, post-reveal actions |
| `market_views.py` | 280 | Market browser, buy confirmation |
| `market.py` | 500 | Market commands + owner |
| `trade_views.py` | 520 | Trade panel + confirmation |
| `trades.py` | 310 | Trade commands |
| `profile_render.py` | 700 | PIL-based profile card image |
| `cards_admin.py` | 1308 | Visual card editor |
| `season.py` | 600 | Season pass + missions |
| `gang_war.py` | 520 | Full war system |
| `gangs.py` | 420 | Gang management |
| `inventory.py` | 600 | Card collection browser |
| `squad.py` | 400 | Squad management panel |
| `announce_owner.py` | 250 | Background loops (COTD, bounty) |
| `onboarding.py` | 300 | /start, /help, terms, paginator |

### Utils (`bot/utils/`)
| File | Lines | Purpose |
|------|-------|---------|
| `battle_state.py` | 1371 | Core combat engine |
| `cards_logic.py` | 320 | Card definition/instance/scaling |
| `attacks_logic.py` | 280 | Attack catalog + assignment |
| `market_logic.py` | 300 | Listing/pricing/embeds |
| `xp_logic.py` | 130 | XP/CP tables, milestones |
| `weapon_logic.py` | 120 | Weapon buffs, equip, upgrade |
| `pack_logic.py` | 200 | Pack opening + pity system |
| `squad_logic.py` | 120 | Squad helpers |
| `economy_logic.py` | 80 | Balance/cooldown helpers |
| `typing_matchup.py` | 120 | 6-type system |
| `ui.py` | 250 | Emojis, embeds, boxes, styling |
| `ganG_logic.py` | 120 | Role hierarchy |
| `war_logic.py` | 200 | War matchmaking |
| `season_logic.py` | 100 | Season pass |

---

## 2. 🚀 Startup Sequence (`main.py`)

```
LookismBot.__init__()
│
├── 1. Create Storage(DATA_PATH) — thread-safe JSON
│       Sets up threading.Lock, cache, corruption backup
│
├── 2. Create SQLite repositories
│       ├── SQLiteMarketRepository — WAL mode
│       ├── SQLiteTradeRepository
│       └── SQLiteBattleRepository
│
├── 3. Create service wrappers
│       ├── MarketService(repo, storage)
│       ├── TradeService(repo, storage)
│       └── BattleService(repo, storage)
│
└── 4. Setup hook → setup_hook()
    │
    ├── 5. Bootstrap services from JSON → SQLite
    │       ├── market_service.bootstrap_from_json()
    │       │   Check: already completed? → skip
    │       │   Check: SQLite has state? → mark completed, skip
    │       │   Else: read JSON → seed SQLite
    │       ├── trade_service.bootstrap_from_json()
    │       └── battle_service.bootstrap_from_json()
    │
    ├── 6. Load 32 extension cogs (all in bot.features.*)
    │       Failures logged but bot continues
    │
    ├── 7. Sync slash commands
    │       ├── Copy global to guilds (if GUILD_IDS set)
    │       ├── Sync owner-guild commands (o_ prefixed)
    │       └── Sync global commands
    │
    ├── 8. Log all registered commands
    │
    ├── 9. Unlock stale trade-locked cards from crashes
    │
    └── 10. Recover active battles from crash
```

### Extension Load Order & Dependencies
```
1. onboarding       — (none)
2. profile          — onboarding
3. profile_owner    — profile
4. economy          — onboarding
5. inventory        — profile
6. packs            — onboarding
7. cards_admin      — (none)
8. card_tools       — cards_admin
9. market           — economy, cards_admin
10. market_owner    — market
11. trades          — economy
12. rewards         — economy
13. owner_rewards   — rewards
14. redeem          — economy
15. shop            — packs
16. squad           — inventory
17. battle          — squad, economy
18. tutorial        — onboarding
19. tournament      — battle
20. leaderboards    — profile
21. achievements    — profile
22. season          — economy
23. alliance        — gangs
24. gangs           — economy
25. server_settings — (none)
26. announce_owner  — server_settings
27. attacks_owner   — cards_admin
28. confirm         — (none)
29. packs_panel     — packs
30. emoji_panel     — (none)
31. gang_war        — gangs, battle
32. keystones       — cards_admin
33. weapons         — inventory, cards_admin
```

---

## 3. 🔄 Interaction Flow

Every slash command goes through:

```
1. LookismCommandTree.interaction_check()
   │
   ├── Autocomplete? → Allow through
   │
   └── Command?
       ├── Check _terms_cache (in-memory set)
       ├── Cache miss? → storage.load() → check has_user_accepted_terms()
       ├── Not accepted? → Send Terms embed + TermsGateView → BLOCK
       └── Accepted? → Add to cache → ALLOW
           │
2. Cog handler method
   │
   ├── ensure_registered() check
   │   └── Fail? → Send "use /start first" message
   │
   ├── storage.with_lock(mutate_function)
   │   ├── Acquire threading.Lock
   │   ├── Read live data from _cache (or disk if cold)
   │   ├── Execute mutation function
   │   ├── Save data atomically:
   │   │   ├── Sanitize for JSON
   │   │   ├── Write to .tmp file
   │   │   ├── fsync()
   │   │   └── os.replace(.tmp → .json)
   │   └── Release lock
   │
   ├── (Optional) SQLite update via service layer
   │
   └── Send response (embed + view)
```

---

## 4. 💾 Storage Architecture (Dual System)

### JSON Storage (`storage.py`)
```python
class Storage:
    """Thread-safe JSON with in-memory caching."""

    def __init__(self, path):
        self.lock = threading.Lock()
        self._cache = None  # Lazy-loaded

    def load(self):
        return deepcopy(self._live_data())

    def save(self, data):
        self._cache = data  # Update cache immediately
        # Atomic write:
        tmp = path + ".tmp"
        json.dump(sanitized, tmp)
        fsync(tmp)
        os.replace(tmp, path)

    def with_lock(self, fn):
        with self.lock:
            data = self._live_data()
            result = fn(data)  # fn modifies data in-place
            self.save(data)
        return result
```

### SQLite Repositories (`sqlite_store.py`)
All repositories use WAL mode with `NORMAL` synchronous:
- `market_settings` — 1 row, market config
- `market_store_items` — Official store items
- `market_listings` — Active listings
- `trade_pending` — User IDs in active trades
- `trade_history` — Completed trade records
- `trade_offer_board` — Open trade offers
- `battle_queue` — Ranked queue entries
- `battle_pending_friendly` — Friendly challenges
- `battle_active_by_user` — User→battle mapping
- `app_migrations` — Bootstrap migration tracking

### Supabase Sync (`supabase_sync.py`)
```
Fire-and-forget background thread:
1. Serialize data to JSON
2. POST to Supabase REST API
3. dedup: skip if a sync is already pending
4. 5-second timeout
```

---

## 5. 🧠 Battle Engine Architecture

### State Object Structure
```python
battle_state = {
    "battle_id": str,
    "type": "ranked|friendly|cpu|tournament",
    "players": {
        "player_id": {
            "team_uids": ["uid1", "uid2", ...],    # 1-4 fighters
            "current_index": 0,                      # Active fighter
            "hp": {"uid1": 350, "uid2": 280, ...},
            "hp_max": {"uid1": 350, ...},
            "stamina": {"uid1": 100, ...},
            "stamina_max": 100,
            "stats": {"uid1": {"strength": 50, ...}, ...},
            "fighter_names": {"uid1": "James Lee", ...},
            "mastery_by_uid": {"uid1": ["speed"], ...},
            "assigned_attacks_by_uid": {"uid1": {...}},
            "passives_by_uid": {"uid1": [...]},
            "is_cpu": False,
            "swaps_used": 0,
            "cpu_meta": {...},  # Only for CPU opponents
        }
    },
    "turn_user_id": str,         # Whose turn it is
    "round": 1,
    "log": ["action:move:damage", ...],
    "ended": False,
    "winner_id": "",
    "pending_defense_by_char_uid": {},
    "used_defenses_by_char_uid": {},
    "used_unique_skills_by_char_uid": {},
    "guard_broken_by_char_uid": {},
    "used_ultimate_count_by_side": {},
    "created_at": timestamp,
    "turn_started_at": timestamp,
    "coin_reward": 0,
    "cpu_trophy_change": 0,
    "pvp_trophy_changes": {},
}
```

### apply_move() Flow
```
apply_move(data, battle_id, actor_id, move_type, value)
│
├── 1. Validate battle context
│       - State exists?
│       - Battle hasn't ended?
│       - Is it this player's turn?
│       - Is player part of this battle?
│
├── 2. Forfeit? → end_battle (winner = other)
│
├── 3. Switch?
│       - Check swap cap (1 per battle for humans)
│       - Check target alive
│       - Update active_index
│       - Reset target stamina to 100
│       - Pass turn to enemy
│
├── 4. Defense (block/dodge/parry/revert/tank)?
│       - Check if this defense type already used this battle
│       - Store as pending_defense_by_char_uid
│       - Deduct stamina (15 per defense)
│       - Pass turn to enemy
│
├── 5. Attack
│       - Check stamina > 0 (exhausted = normal only)
│       - Check usage rules (ultimate limit, unique skill once, etc.)
│       - Deduct stamina (10/20/35/25 based on move)
│       - compute_attack_damage()
│       - apply_defense()
│       - apply_damage_and_check_elimination()
│       - Pass turn or end battle
│
└── Return result dict
```

### CPU AI Personalities
| Personality | Behavior |
|-------------|----------|
| **Aggressive** | Always use highest-power move available |
| **Defensive** | Block when HP < 70%, dodge when HP < 50% |
| **Trickster** | Dodge when healthy, unpredictable attacks |
| **Finisher** | Save ultimate for when enemy HP < 30% |
| **Balanced** | Mix of offense and defense |

---

## 6. 💰 Economy System

### Currency Flow
```
                 ┌─────────────────┐
                 │   User Action    │
                 └────────┬────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                  ▼
   ┌─────────┐    ┌──────────────┐    ┌──────────┐
   │ Battles │    │   Rewards    │    │  Market  │
   │ +coins  │    │  +coins/card │    │ +-coins  │
   │ +XP/CP  │    │  +XP/CP      │    │          │
   └─────────┘    └──────────────┘    └──────────┘
        │                 │                  │
        └─────────┬───────┘                  │
                  ▼                          │
           ┌──────────┐                     │
           │  Player   │◄────────────────────┘
           │  Wallet   │
           │ coins: X  │
           │ gems: Y   │
           └────┬─────┘
                │
        ┌───────┼───────────┐
        ▼       ▼           ▼
   ┌──────┐ ┌──────┐ ┌──────────┐
   │Packs │ │Fuse  │ │Tournament│
   │ -coins│ │-coins│ │ -coins   │
   └──────┘ └──────┘ └──────────┘
```

### Reward Cooldowns
| Type | Cooldown | Base Coins | Card Chance | Card Rarity Pool |
|------|----------|------------|-------------|-------------------|
| Hourly | 1h | 100 | 0% | — |
| Daily | 24h | 150 | 50% | Common (100%) |
| Weekly | 7d | 1,500 | 50% | Common (70%) + Rare (30%) |
| Monthly | 30d | 10,000 | 50% | Rare (60%) + Epic (35%) + Legendary (5%) |

### Login Streak Multipliers (Daily)
| Streak | Multiplier | Effective Coins |
|--------|------------|-----------------|
| 1-2 days | 1.0x | 150 |
| 3-6 days | 1.25x | 187 |
| 7-13 days | 1.5x | 225 |
| 14-29 days | 2.0x | 300 |
| 30+ days | 3.0x | 450 |

---

## 7. 📦 Pack System

### Pack Catalog
| Pack | Price | Rarity Pool | Pity System |
|------|-------|-------------|-------------|
| Newbie | 750 | Common 80%, Rare 20% | — |
| Amateur | 3,000 | Common 50%, Rare 45%, Epic 5% | Rare at 15 pulls |
| Basic | 5,000 | Common 30%, Rare 60%, Epic 10% | Epic at 20 pulls |
| Intermediate | 10,000 | Rare 40%, Epic 50%, Legendary 10% | Legendary at 30, Epic at 15 |
| Experienced | 25,000 | Epic 60%, Legendary 30%, Mythical 10% | Mythical at 40, Legendary at 20 |
| Advanced | 40,000 | Legendary 65%, Mythical 25%, Infernal 10% | — |
| Veteran | 50,000 | Legendary 30%, Mythical 50%, Infernal 20% | Infernal at 50, Mythical at 30, Legendary at 15 |
| VIP | 75,000 | Mythical 50%, Infernal 40%, Abyssal 10% | — |
| Ranker | 90,000 | Infernal 50%, Abyssal 50% | — |
| War | 0 (event) | Common 40%, Rare 30%, Epic 28%, Legendary 2% | — |

### Pity System
Tracks pulls-since-last-rare for specific rarities. When counter hits threshold, forces that rarity:
```python
PITY_THRESHOLDS = {
    "veteran_pack": {"Infernal": 50, "Mythical": 30, "Legendary": 15},
    "experienced_pack": {"Mythical": 40, "Legendary": 20},
    "intermediate_pack": {"Legendary": 30, "Epic": 15},
    "basic_pack": {"Epic": 20},
    "amateur_pack": {"Rare": 15},
}
```

---

## 8. 👥 Social Systems

### Gang Roles (Hierarchy)
```
👑 Head         — Full control, can do everything
⚔️ Vice Head    — Can promote/demote/invite/kick (except other Vice Heads)
📣 Recruiter    — Can invite and kick regular Members only
🏅 Elder        — Honorary role, no special permissions
👤 Member       — Base role
```

### Alliance
- Max 5 gangs per alliance
- 24h cooldown after leaving
- Alliance trophies = sum of all members' trophies

### Gang War Phases
```
Queue → Match Found → Prep Phase (5 min)
                     → Battle Phase (5 min, auto-ends)
                     → Winner determined → Rewards granted
```

---

## 9. 🏆 Achievement Catalog

| Achievement | Tier | Points | Requirement |
|-------------|------|--------|-------------|
| First Blood | Bronze | 10 | Win first ranked battle |
| AI Slayer | Bronze | 10 | Win first AI battle |
| Collector I | Bronze | 15 | Own 10 cards |
| Collector II | Silver | 30 | Own 50 cards |
| Trader | Silver | 20 | Complete first trade |
| Market Seller | Bronze | 15 | Sell first listing |
| Pack Opener | Bronze | 15 | Open first pack |
| Gang Member | Silver | 20 | Join a gang |
| Alliance Member | Gold | 35 | Join an alliance |
| Tournament Entry | Silver | 25 | Join a tournament |
| Tournament Champion | Diamond | 80 | Win a tournament |
| Season Claimer | Gold | 40 | Claim first season reward |
| Battle Novice | Bronze | 200 | Win 10 ranked battles |
| Battle Warrior | Silver | 500 | Win 50 ranked battles |
| Battle Master | Gold | 1000 | Win 100 ranked battles |
| On Fire | Silver | 300 | Win 5 in a row |
| Card Collector | Diamond | 2000 | Own all 26 cards |
| Ruby Tier | Diamond | 1500 | Reach Ruby rank |
| Ultimate Striker | Silver | 250 | Land 10 ultimates |
| Perfect Defender | Silver | 200 | Block 10 attacks |
| Big Spender | Gold | 400 | Spend 100k coins |

---

## 10. 🔄 Background Tasks

| Task | Interval | What It Does |
|------|----------|-------------|
| `card_of_the_day` | 24h | Picks random card, gives +15% damage buff, announces |
| `weekly_bounty` | 168h | Finds highest win streak (≥5), posts bounty |
| `war_monitor` | 60s | Matches queue entries, transitions phases |
| `season_timer` | On create | Auto-ends tournament at duration |

---

## 11. 🧪 Test Suite

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_battle_engine.py` | 73 | Damage formulas, miss, defense, ELO, etc. |
| `test_typing_matchup.py` | 17 | All type combinations |
| `test_battle_freeze_regressions.py` | — | Timeout/freeze scenarios |
| `test_card_fusion.py` | — | Star upgrade |
| `test_onboarding_starter.py` | — | Starter pack grants |
| `test_shop_purchase_flow.py` | — | Pack buying |
| `test_trade_lifecycle.py` | — | Trade validation |
| `test_sqlite_bootstrap.py` | — | JSON→SQLite migration |
| `test_storage.py` | — | Cache consistency |
| `test_race_conditions.py` | — | Concurrent mutations |
| `test_daily_trophy_cap.py` | — | CPU trophy cap |
| `test_tournament_rank_gate.py` | — | Min-rank filter |
| `test_swap_cap.py` | — | 1-swap limit |
| `test_profile_context.py` | — | Profile data extraction |
| `test_owner_admin_helpers.py` | — | Card/attack admin |
| `test_constants.py` | — | Rarity/color checks |
| `test_command_text_and_queue.py` | — | Command registry |

---

## 12. ⚠️ Critical Issues

| Issue | Location | Impact |
|-------|----------|--------|
| **Hardcoded Discord Token** | `config.py:5` | Account takeover risk |
| **Supabase Service Role Key** | `supabase_sync.py` | Full database access |
| **JSON file corruption risk** | `storage.py` | Race on crash during write |
| **No input rate limiting** | All commands | API abuse potential |
| **SQLite + JSON dual state drift** | `services/` | Possible inconsistency |
| **No graceful shutdown** | `launcher.py` | Stale state on restart |
| **Bot log unbounded growth** | `logs/bot.log` | Disk space exhaustion |
