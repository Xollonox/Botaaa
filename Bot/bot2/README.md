# LOOKISM HXCC — Bot2

Discord card-collection battling game themed around the webtoon *Lookism*. Players collect fighters, build squads, battle PvP/CPU, trade on the market, join gangs and alliances, progress through seasons, and earn achievements.

---

## Quick Start

```bash
cd Bot/bot2
python main.py
```

Requires `BOT_TOKEN` and `LOOKISM_OWNER_IDS` in environment or `.env`. See `bot/config.py`.

---

## Architecture

```
main.py
│
└── LookismBot (discord.Bot subclass)
    ├── storage            # bot/data/storage.py — JSON load/save + with_lock
    ├── market_service     # bot/services/market_service.py — SQLite + JSON
    ├── trade_service      # bot/services/trade_service.py — SQLite + JSON
    └── battle_service     # bot/services/battle_service.py — SQLite + JSON
         │
         └── 30+ feature cogs (bot/features/*.py)
               │
               └── bot/utils/ — shared business logic
```

**Boot order** (main.py):
1. Bootstrap JSON state (`lookism_data.json`) via `build_default_data()` + `ensure_structure()`
2. Bootstrap SQLite repos from JSON state
3. Load all `EXTENSIONS` (feature cogs)
4. Sync guild-scoped and global slash commands
5. Unlock stale trade locks (crashed trades)
6. Recover active battles from persistent state

---

## Directory Layout

| Path | Purpose |
|---|---|
| `main.py` | Full app bootstrap |
| `bot/config.py` | Token, owner IDs, data paths, guild sync config |
| `bot/data/` | JSON defaults, constants, schema, storage, sqlite, sync |
| `bot/data/cards.json` | Seed catalog of 122 card definitions |
| `bot/data/constants.py` | Rarity order, price bands, trophy thresholds, stamina costs |
| `bot/data/defaults.py` | Default player/user data, card normalization, data structure sync |
| `bot/data/schemas.py` | Schema migration helpers |
| `bot/data/storage.py` | Thread-safe JSON load/save with in-memory cache and atomic writes |
| `bot/data/sqlite_store.py` | SQLite-backed service repos with bootstrap from JSON |
| `bot/features/` | All slash command cogs and Discord UI views |
| `bot/services/` | Battle/market/trade persistence service layer |
| `bot/utils/` | Shared business logic and helpers |
| `tests/` | Pytest regression and subsystem tests |
| `logs/bot.log` | Runtime structured log output |
| `lookism_data.json` | Primary JSON runtime state file |
| `lookism_data.sqlite3` | SQLite state file (if no env override) |

---

## Extension Load Order

Extensions load in this order in `main.py`:

| Category | Modules |
|---|---|
| onboarding/help | `onboarding`, `tutorial` |
| profile/identity | `profile`, `profile_owner`, `card_tools` |
| economy/rewards | `economy`, `rewards`, `owner_rewards`, `redeem` |
| inventory/upgrade | `inventory` |
| packs/shop | `packs`, `packs_panel`, `shop` |
| market/trade | `market`, `market_owner`, `trades` |
| squad/battle | `squad`, `battle` |
| tournament/league | `tournament`, `leaderboards` |
| progression | `achievements`, `season` |
| social | `gangs`, `alliance`, `gang_war` |
| settings/admin | `server_settings`, `announce_owner`, `cards_admin`, `attacks_owner`, `emoji_panel` |

---

## Public Command Map

### Player Commands

| Command | Purpose |
|---|---|
| `/start` | Account creation / onboarding panel |
| `/help` | Command browser with Battle Guide button |
| `/tutorial` | Tutorial progress |
| `/profile` | Premium profile card with rival info |
| `/collection` | Browse owned cards with filters/sorts/lock/upgrade |
| `/upgrade` | Directly upgrade a fighter's star level via autocomplete (skips `/collection` browsing) |
| `/card_info` | Inspect catalog card definition |
| `/card_lock` | Lock/unlock a card instance |
| `/card_search` | Search catalog cards by name/rarity/typing |
| `/card_list` | List catalog cards grouped by rarity |
| `/balance` | Show coin and premium gem balances |
| `/squad` | Squad management panel (active/backup/supervisor) |
| `/packs` | View and open owned packs |
| `/shop` | Pack shop with rates display |
| `/hourly` / `/daily` / `/weekly` / `/monthly` | Claim time-based rewards |
| `/redeem` | Redeem a reward code |
| `/weapon` | Weapon inventory gallery (equip/unequip/upgrade) |
| `/keystone_assign` | Equip/unequip keystone on a card |
| `/keystone_info` | View keystone details |
| `/stats` | View star upgrade mechanics reference |

### Market

| Command | Purpose |
|---|---|
| `/browse` | Browse market listings with filters/sorts |
| `/add` | List a card for sale |
| `/remove` | Remove your listing |
| `/instant_sell` | Sell a card for instant payout |

### Trade

| Command | Purpose |
|---|---|
| `/trade start` | Start P2P trade session |
| `/trade cancel` | Cancel active trade session |
| `/trade history` | View trade history |
| `/trade post` | Post offer to trade board |
| `/trade board` | Browse open trade offers |
| `/trade accept` | Accept trade offer by ID |
| `/trade cancel_offer` | Cancel your posted offer |

### Battle

| Command | Purpose |
|---|---|
| `/battle` | Enter ranked PvP queue |
| `/battle_cancel` | Cancel ranked queue |
| `/friendly` | Send friendly challenge to a player |
| `/friendly_cancel` | Cancel outgoing friendly challenge |
| `/forfeit` | Forfeit active battle |
| `/battle_cpu` | Fight a CPU opponent |
| `/tournament` | Tournament overview (join/battle inside panel) |
| `/tournament_battle` | Fight tournament participant |

### Leaderboards

| Command | Purpose |
|---|---|
| `/lb global` | Global trophy leaderboard |
| `/lb league` | League leaderboard with overview button |
| `/lb gang` | Gang leaderboard |
| `/lb alliance` | Alliance leaderboard |
| `/lb achievements` | Achievement points leaderboard |
| `/lb xp` | Player XP leaderboard |
| `/lb cp` | Season CP leaderboard |

### Progression

| Command | Purpose |
|---|---|
| `/achievements` | View earned and locked achievements |
| `/season` | Season hub with tabs (Info, Pass, Missions) |

### Gangs & Alliances

**Gang:**
| Command | Purpose |
|---|---|
| `/gang create` | Create gang (10,000 coins) |
| `/gang info` | Inspect gang details |
| `/gang invite` | Invite a player |
| `/gang join` | Join an open gang |
| `/gang leave` | Leave your gang |
| `/gang kick` | Kick a member |
| `/gang promote` / `/gang demote` | Change member role |
| `/gang members` | Member list |
| `/gang transfer_owner` | Transfer leadership |
| `/gang set_description` | Set gang description |
| `/gang set_status` | Toggle open/closed |
| `/gang stats` | Gang statistics |

**Alliance:**
| Command | Purpose |
|---|---|
| `/alliance create` | Create alliance (requires gang leader) |
| `/alliance info` | Inspect alliance |
| `/alliance invite` | Invite a gang |
| `/alliance leave` | Leave alliance |

**Gang War:**
| Command | Purpose |
|---|---|
| `/gang_war start` | Start war matchmaking |
| `/gang_war status` | Current war status |
| `/gang_war attack` | Attack opponent |
| `/gang_war record` | Record battle result |
| `/gang_war cancel_queue` | Cancel matchmaking |
| `/gang_war preference` | Set in/out preference |
| `/defensive_squad_setup` | Set defensive squad |

### Server Settings

| Command | Purpose |
|---|---|
| `/server_mode` | All-channel vs single-channel mode |
| `/server_set_channel` | Locked command channel |
| `/server_set_announce` | Announcement channel |
| `/server_set_battle` | Battle channel |

---

## Owner Command Map

All under the grouped `/o` surface unless noted:

### Card/Content Management

| Command | Purpose |
|---|---|
| `/o add_card` | Create fighter card (optional type1/type2 for typing) |
| `/o edit_card` | Edit fighter card fields |
| `/o delete_card` | Delete fighter card |
| `/o add_attack` | Create attack or defense |
| `/o edit_attack` | Edit attack fields |
| `/o delete_attack` | Delete attack and unassign |
| `/o list_attacks` | List catalog attacks |
| `/o assign_attack` | Assign attack to card |
| `/o remove_attack` | Remove assigned attack |
| `/o view_card_attacks` | Inspect card's attack loadout |
| `/o add_weapon` | Add weapon to catalog |
| `/o add_keystone` | Add keystone to catalog |

### Economy

| Command | Purpose |
|---|---|
| `/o_add_balance` | Add coins to player |
| `/o_add_premium` | Add premium gems to player |

### Packs & Market

| Command | Purpose |
|---|---|
| `/o_pack` | Pack management panel |
| `/o_feature_card` | Set featured card in market |
| `/o_special_offer` | Post special offer |
| `/o_market_remove` | Force-remove listing |
| `/o_market_set_quick_sell` | Set quick-sell payout values |
| `/o_market_toggle` | Enable/disable market |
| `/o_market_set_fee` | Set market fee percent |
| `/o_market_set_max_listings` | Set listing cap per user |
| `/o_market_store_add` | Add store item |
| `/o_market_store_remove` | Remove store item |
| `/o_market_store_toggle` | Toggle store item visibility |

### Profile Cosmetics

| Command | Purpose |
|---|---|
| `/o_profile_set_default_bg` | Default profile background |
| `/o_profile_set_default_featured` | Default featured card |
| `/o_profile_set_premium` | Set premium status |
| `/o_profile_theme` | Set cosmetic theme |
| `/o_profile_border` | Set border cosmetic |
| `/o_profile_badge` | Set badge cosmetic |
| `/o_profile_preview` | Preview any profile |

### Rewards & Codes

| Command | Purpose |
|---|---|
| `/o_redeem_create` | Create reward code |
| `/o_redeem_delete` | Delete reward code |
| `/o_redeem_list` | List reward codes |
| `/o_set_hourly` / `/o_set_daily` / `/o_set_weekly` / `/o_set_monthly` | Configure reward rates |
| `/o_achievement_grant` | Grant achievement to player |
| `/o_achievement_remove` | Remove achievement |
| `/o_achievement_reset` | Reset all achievements |

### Season & Tournaments

| Command | Purpose |
|---|---|
| `/o_season_create` | Create new season |
| `/o_season_end` | End current season |
| `/o_season_pass_setup` | Configure pass tiers |
| `/o_season_add_cp` | Add season CP to player |
| `/o_season_mission_create` | Create mission |
| `/o_tournament_create` | Create tournament |
| `/o_tournament_cancel` | Cancel tournament |

### Gang War

| Command | Purpose |
|---|---|
| `/o_war_start` | Force-start war |
| `/o_war_end` | Force-end war |
| `/o_war_set_phase` | Phase override |
| `/o_war_set_durations` | Set phase durations |
| `/o_war_list` | List wars and queue |

### Utility

| Command | Purpose |
|---|---|
| `/o_announce` | Post server announcement |
| `/o_event` | Activate event multiplier |
| `/o_emoji_panel` | Interactive emoji config panel |
| `/o_emoji_set` | Set one emoji |
| `/o_emoji_reset` | Reset one emoji |
| `/o_emoji_reset_all` | Reset all emojis |
| `/o_battle_unstuck` | Clear stuck battle state |

---

## Config Surface (`bot/config.py`)

| Name | Purpose |
|---|---|
| `BOT_TOKEN` | Discord bot token (env or .env) |
| `LOOKISM_OWNER_IDS` | Comma-separated owner user IDs |
| `BASE_DIR` | bot2 base directory |
| `DATA_PATH` | Path to `lookism_data.json` |
| `SQLITE_PATH` | Path to SQLite file (overridable by `LOOKISM_SQLITE_PATH`) |
| `GUILD_IDS` | Optional fast-sync guild list |
| `OWNER_GUILD_ID` | Guild for owner-only command sync |

---

## Important Runtime Files

| File | Role |
|---|---|
| `lookism_data.json` | Primary JSON state — players, cards, market, gangs, etc. |
| `lookism_data.sqlite3` | SQLite state for services (market listings, trades, battles) |
| `data/cards.json` | Seed card catalog (read at boot, merged into data) |
| `logs/bot.log` | Structured runtime log |

---

## Testing

```bash
# Full suite
cd Bot/bot2
pytest -q

# Focused suites
pytest -q tests/test_battle_engine.py tests/test_battle_freeze_regressions.py
pytest -q tests/test_owner_admin_helpers.py
pytest -q tests/test_trade_lifecycle.py tests/test_command_text_and_queue.py
pytest -q tests/test_sqlite_bootstrap.py
pytest -q tests/test_storage.py tests/test_race_conditions.py
pytest -q tests/test_onboarding_starter.py tests/test_tournament_rank_gate.py

# Syntax check
python3 -m py_compile main.py bot/config.py bot/features/battle.py
```

---

## Deployment

```bash
git fetch origin main
git reset --hard origin/main
pip install -U --prefix .local -r requirements.txt
python main.py
```

---

## Maintenance Hotspots

| Area | Files | Why |
|---|---|---|
| Startup/sync | `main.py`, `config.py` | Extension load, command sync, token/paths |
| Content/admin | `cards_admin.py`, `cards_logic.py`, `attacks_logic.py` | Card and attack mutation |
| Persistence | `storage.py`, `sqlite_store.py` | State integrity, atomic writes |
| Battle runtime | `battle.py`, `battle_views.py` | Timers, live-edited embeds, views |
| Market/trade | `market.py`, `trades.py`, `trade_logic.py` | Locked cards, listing state |
| Social | `gangs.py`, `alliance.py`, `gang_war.py` | Multi-user state changes |
| Season/rewards | `season.py`, `rewards.py` | Recurring progression |

---

## Investigation Checklist

```text
When bot2 breaks:

1. Read logs/bot.log for traceback
2. Confirm config/data paths exist
3. Check extension load failures in startup logs
4. Run focused pytest for affected subsystem
5. Inspect matching feature file
6. Inspect matching utils helper
7. Inspect service/data layer if persistence is involved
```

---

## File Map

### `bot/features/` — Slash command cogs

| File | Role |
|---|---|
| `achievements.py` | Achievement listing + grant commands |
| `alliance.py` | Alliance CRUD, invites, management |
| `announce_owner.py` | Owner announcement commands |
| `attacks_owner.py` | Owner attack catalog CRUD |
| `battle.py` | PvP/friendly battle queueing, turns, timers |
| `battle_cpu.py` | CPU battle commands |
| `battle_embeds.py` | Battle embed rendering |
| `battle_helpers.py` | Battle UI helpers |
| `battle_views.py` | Battle button/select views |
| `card_tools.py` | Card info, search, list |
| `cards_admin.py` | Owner card catalog CRUD |
| `economy.py` | Balance, reward claims |
| `emoji_panel.py` | Server emoji config |
| `gang_war.py` | Gang war queue/attack/status |
| `gangs.py` | Gang CRUD, invites, roles |
| `help_index.py` | Help command |
| `inventory.py` | Collection browser, lock, upgrade, `/upgrade` autocomplete |
| `keystones.py` | Keystone equip/unequip |
| `leaderboards.py` | Trophy/XP/CP leaderboards |
| `market.py` | Market browse, add, buy, sell |
| `market_owner.py` | Owner market config |
| `market_views.py` | Market browse panel, buy confirm |
| `moderation_owner.py` | Owner ban/warn |
| `onboarding.py` | Registration + tutorial |
| `owner_rewards.py` | Owner reward granting |
| `packs.py` | Pack opening |
| `packs_panel.py` | Pack shop UI |
| `profile.py` | Profile display |
| `profile_owner.py` | Owner profile config |
| `profile_render.py` | Profile image rendering |
| `redeem.py` | Code redemption |
| `rewards.py` | Hourly/daily/weekly/monthly |
| `season.py` | Season pass, missions |
| `server_settings.py` | Channel locks, mode |
| `shop.py` | Store shop |
| `squad.py` | Squad management |
| `stats_preview.py` | Stats reference command |
| `tournament.py` | Tournament brackets |
| `trade_views.py` | Trade panel UI |
| `trades.py` | Trade commands |
| `tutorial.py` | Tutorial guide |
| `weapons.py` | Weapon gallery/equip |

### `bot/utils/` — Logic and helpers

| File | Role |
|---|---|
| `achievement_logic.py` | Achievement grant/remove/format |
| `alliance_logic.py` | Alliance helpers, cooldowns |
| `attacks_logic.py` | Attack CRUD, assignment |
| `battle_engine_pdf.py` | Damage calculation compat helpers |
| `battle_state.py` | Full battle state + damage pipeline |
| `cards_logic.py` | Card build, stat scaling, catalog queries |
| `checks.py` | Registration, owner, permission checks |
| `confirm_pipeline.py` | Multi-step confirmation |
| `economy_logic.py` | Balance add/deduct, cooldowns |
| `gang_logic.py` | Gang roles, permissions |
| `interaction_visibility.py` | Smart reply/error helpers |
| `inventory_api.py` | Inventory add/find/remove |
| `logging_setup.py` | Logging config |
| `market_logic.py` | Listing helpers, sorting, embeds |
| `pack_logic.py` | Pack opening, pity, rarity rolling |
| `profile_logic.py` | Profile data assembly |
| `redeem_logic.py` | Code generation/validation |
| `reward_grant.py` | Generic reward granting |
| `reward_logic.py` | Reward rate building |
| `season_logic.py` | Season data, pass XP, trophies |
| `server_rules.py` | Server config enforcement |
| `squad_logic.py` | Squad get/set, power compute |
| `timeutil.py` | `now_ts()` helper |
| `tournament_logic.py` | Tournament bracket generation |
| `trade_logic.py` | Trade CRUD, atomic card transfer |
| `typing_matchup.py` | Type system multipliers |
| `ui.py` | Embed builder, emoji resolution |
| `war_logic.py` | Gang war queue, scoring |
| `weapon_logic.py` | Weapon instance, buffs, upgrade |
| `xp_logic.py` | XP/level with milestones |

### `bot/services/`

| File | Role |
|---|---|
| `battle_service.py` | Battle state persistence |
| `market_service.py` | SQLite market listings |
| `trade_service.py` | SQLite trade state |

### `bot/data/`

| File | Role |
|---|---|
| `storage.py` | JSON load/save + lock management |
| `sqlite_store.py` | SQLite repos + bootstrap |
| `supabase_sync.py` | Extra sync surface |
| `defaults.py` | Default state + card normalization |
| `schemas.py` | Schema migration helpers |
| `constants.py` | All game constants |
| `cards.json` | Seed card catalog (122 cards) |

---

## Key Design Notes

- **State is JSON-first.** All runtime state lives in `lookism_data.json`. SQLite is a secondary service layer for market/trade/battle persistence.
- **All writes go through `with_lock`.** The storage layer acquires a thread lock, deep-copies the data dict, passes it to the mutation closure, writes the result atomically.
- **Cog pattern:** Each feature file exports a `setup(bot)` function that `add_cog(bot, CogClass(bot))`. The `main.py` extension loader calls `bot.load_extension()` for each.
- **Card catalog vs card instances:** Card *definitions* live under `data["cards"]` (keyed by unique name). Card *instances* in player inventory have a `card_name` field pointing to the definition. Always use `find_catalog_card()` (not raw `catalog.get()`) to handle key/name mismatches.
- **Pack rewards:** Openable packs live in `user["pack_inventory"]` as pack-entry dicts. Reward flows should grant packs through `pack_logic._add_packs_to_inventory()` so `/packs` can open them; do not write new rewards only to legacy `owned_packs`.
- **Read-only paths** (like `server_rules.py` interaction checks) should use `storage.load_readonly()` to avoid the full deepcopy cost of `storage.load()`.
