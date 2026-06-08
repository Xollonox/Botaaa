# Bot2 README

> `bot2` is the main Lookism game bot.
>
> It is the largest and most important part of this repo.
>
> Main domains:
> - onboarding and account creation
> - collection and squad management
> - economy and rewards
> - packs and shop
> - profile rendering
> - market and trades
> - gangs and alliances
> - season and achievements
> - PvP battle and friendly battle
> - owner/admin control surfaces

## Entry Point

Run from inside `Bot/bot2`:

```bash
cd /data/data/com.termux/files/home/Botaaa/Bot/bot2
python main.py
```

`main.py`:

- boots the `bot` package by adjusting `sys.path`
- creates `LookismBot`
- enables `message_content` and `members`
- creates storage + market/trade/battle repositories
- bootstraps JSON state into SQLite-backed services
- loads all feature cogs from `EXTENSIONS`
- syncs guild-scoped and global slash commands
- performs stale trade unlock on boot
- runs active-battle recovery if the battle cog is loaded

## What Changed Recently

These recent fixes matter for current runtime behavior:

| Commit | Area | Effect |
| --- | --- | --- |
| `d53b810` | command cleanup | removed `/cotd`, `/rival`, `/stats_guide`, `/league overview`, `/tournament_join`, `/season_pass`, `/season_missions`, `/o_card_edit_typing` as standalone commands — all merged into existing panels or parent commands |
| `720660c` | battle stamina | added per-battle stamina system — each fighter starts at 100 stamina, every move drains it, exhausted fighters locked to normal attacks only, stamina bar shown in battle embed |
| `3bc739b` | battle rewards + season UI | fixed crash when battle rewards granted pending milestone packs; fixed `/season_missions` `NameError` for missing `e(...)` |
| `b5a6296` | battle UI | battle message now renders 3 embeds instead of 5 |

If a VPS still shows the old crash stack or old 5-embed battle layout, it is usually running stale code and needs a fresh pull/reset plus restart.

## Directory Layout

| Path | Purpose |
| --- | --- |
| `main.py` | full app bootstrap |
| `bot/config.py` | token, owner IDs, data paths, guild sync config |
| `bot/data/` | JSON defaults, constants, schema, storage, sqlite, sync |
| `bot/features/` | slash command cogs and UI logic |
| `bot/services/` | battle/market/trade service layer |
| `bot/utils/` | shared business logic and helpers |
| `tests/` | regression and subsystem tests |
| `logs/bot.log` | runtime logging output |
| `BATTLE_MECHANICS.md` | battle-specific supporting notes |
| `mindmap.txt` | existing local map / notes |

## Bot2 Architecture

```text
main.py
|
+-- LookismBot
|   +-- storage = JSON state file
|   +-- market_service = SQLite + JSON bootstrap
|   +-- trade_service = SQLite + JSON bootstrap
|   +-- battle_service = SQLite + JSON bootstrap
|
+-- feature cogs
|   +-- onboarding / help
|   +-- profile / inventory / packs / shop
|   +-- market / trades
|   +-- squad / battle / tournament
|   +-- gangs / alliance / gang_war
|   +-- achievements / season / rewards
|   +-- owner admin commands
|
+-- utils
|   +-- card logic
|   +-- attack logic
|   +-- battle state helpers
|   +-- trade logic
|   +-- market logic
|   +-- reward logic
```

## Config Surface

`bot/config.py` currently defines:

| Name | Purpose |
| --- | --- |
| `BOT_TOKEN` | Discord token |
| `OWNER_IDS` | owner user IDs |
| `BASE_DIR` | bot2 base directory |
| `DATA_PATH` | JSON runtime state file |
| `SQLITE_PATH` | SQLite runtime state file, overridable by `LOOKISM_SQLITE_PATH` |
| `GUILD_IDS` | optional fast-sync guild list |
| `OWNER_GUILD_ID` | guild used for owner-only command sync |

## Important Runtime Files

| File | What it stores |
| --- | --- |
| `Bot/bot2/lookism_data.json` | primary JSON state |
| `Bot/bot2/lookism_data.sqlite3` | SQLite state if env override is not used |
| `Bot/bot2/logs/bot.log` | structured log output |

Important runtime note:

- `Bot/bot2/logs/bot.log` is a runtime artifact, not a meaningful source file. If it is tracked on a server checkout, it can make deploy scripts think the repo has local changes and block updates.

## Extension Load Order

`main.py` currently loads these feature modules:

| Area | Modules |
| --- | --- |
| onboarding/help | `onboarding`, `tutorial` |
| player identity/profile | `profile`, `profile_owner`, `card_tools` |
| economy/rewards | `economy`, `rewards`, `owner_rewards`, `redeem` |
| packs/shop | `packs`, `packs_panel`, `shop` |
| market/trade | `market`, `market_owner`, `trades` |
| squad/battle/tournament | `squad`, `battle`, `tournament` |
| league/season/achievement | `leaderboards`, `achievements`, `season` |
| gangs/alliance/war | `gangs`, `alliance`, `gang_war` |
| settings/admin | `server_settings`, `announce_owner`, `cards_admin`, `attacks_owner`, `confirm`, `emoji_panel` |

## Public Command Map

### Onboarding and help

| Command | Purpose |
| --- | --- |
| `/start` | opens account panel / onboarding entry |
| `/help` | browse commands by category — includes ⚔️ Battle Guide button for damage pipeline and typing chart |
| `/tutorial` | tutorial progress |
| `/confirm` | confirm pending action by action ID |

### Profile, collection, squad

| Command | Purpose |
| --- | --- |
| `/profile` | premium profile card — includes rival info if a rival exists |
| `/collection` | browse owned cards |
| `/card_info` | inspect catalog card |
| `/card_lock` | lock owned card instance |
| `/fuse` | fuse three copies into higher star |
| `/squad` | squad management panel |

### Economy, packs, shop, rewards

| Command | Purpose |
| --- | --- |
| `/balance` | show currency |
| `/packs` | pack inventory |
| `/shop` | pack shop and rates |
| `/hourly` | claim hourly reward |
| `/daily` | claim daily reward |
| `/weekly` | claim weekly reward |
| `/monthly` | claim monthly reward |
| `/redeem` | redeem reward code |

### Market and trade

Market:

| Command | Purpose |
| --- | --- |
| `/browse` | browse market — also shows Card of the Day buff |
| `/add` | list card for sale |
| `/remove` | remove own listing |

Trade:

| Command | Purpose |
| --- | --- |
| `/trade start` | start a player-to-player trade session |
| `/trade cancel` | cancel active trade session |
| `/trade history` | trade history |
| `/trade post` | post trade offer board listing |
| `/trade board` | browse open trade offers |
| `/trade accept` | accept trade offer by ID |
| `/trade cancel_offer` | cancel your posted offer |

### Battle and tournament

| Command | Purpose |
| --- | --- |
| `/battle` | enter ranked queue |
| `/battle_cancel` | cancel ranked queue |
| `/friendly` | send friendly challenge |
| `/friendly_cancel` | cancel outgoing friendly challenge |
| `/forfeit` | forfeit active battle |
| `/tournament` | tournament overview — includes Join and Battle buttons inside the panel |
| `/tournament_battle` | fight tournament participant |

### League, leaderboards, season, achievements

Achievements:

| Command | Purpose |
| --- | --- |
| `/achievements` | earned and locked achievements |

Leaderboards:

| Command | Purpose |
| --- | --- |
| `/lb global` | global trophies |
| `/lb league` | league leaderboard — includes 🏅 League Overview button |
| `/lb gang` | gang leaderboard |
| `/lb alliance` | alliance leaderboard |

Season:

| Command | Purpose |
| --- | --- |
| `/season` | season hub — tabs for Season Info, Season Pass, and Missions |

### Gangs, alliances, war

Gang:

| Command | Purpose |
| --- | --- |
| `/gang create` | create gang |
| `/gang info` | inspect gang |
| `/gang invite` | invite player |
| `/gang join` | join open gang |
| `/gang leave` | leave gang |
| `/gang kick` | kick member |
| `/gang promote` | promote member |
| `/gang demote` | demote member |
| `/gang members` | member list |
| `/gang transfer_owner` | transfer ownership |
| `/gang set_description` | set gang description |
| `/gang set_status` | open/closed state |
| `/gang stats` | gang stats |

Alliance:

| Command | Purpose |
| --- | --- |
| `/alliance create` | create alliance |
| `/alliance info` | inspect alliance |
| `/alliance invite` | invite gang |
| `/alliance leave` | leave alliance |

Gang war:

| Command | Purpose |
| --- | --- |
| `/gang_war start` | start matchmaking |
| `/gang_war status` | current war status |
| `/gang_war attack` | attack opponent |
| `/gang_war record` | record battle result |
| `/gang_war cancel_queue` | cancel matchmaking |
| `/gang_war preference` | set participation preference |
| `/defensive_squad_setup` | set defensive squad |

### Server admin commands

| Command | Purpose |
| --- | --- |
| `/server_mode` | all-channel vs single-channel mode |
| `/server_set_channel` | locked command channel |
| `/server_set_announce` | announcement channel |
| `/server_set_battle` | battle channel |

## Owner Command Map

### Main owner card/admin group

These are under the grouped `/o ...` surface:

| Command | Purpose |
| --- | --- |
| `/o add_card` | create fighter card — optional `type1`/`type2` params for typing |
| `/o edit_card` | edit fighter card fields — optional `type1`/`type2` params to update typing |
| `/o delete_card` | delete fighter card |
| `/o add_attack` | create attack or defense |
| `/o edit_attack` | edit attack fields |
| `/o delete_attack` | delete attack and unassign it |
| `/o list_attacks` | list catalog attacks |
| `/o assign_attack` | assign attack to card |
| `/o remove_attack` | remove assigned attack |
| `/o view_card_attacks` | inspect card attack loadout |

### Additional owner commands

| Command | Purpose |
| --- | --- |
| `/o_add_balance` | add coins |
| `/o_add_premium` | add premium |
| `/o_pack` | pack management panel |
| `/o_feature_card` | set featured card |
| `/o_special_offer` | post special offer |
| `/o_market_remove` | force-remove listing |
| `/o_market_set_quick_sell` | set quick-sell values |
| `/o_market_toggle` | enable/disable market |
| `/o_market_set_fee` | set fee |
| `/o_market_set_max_listings` | listing cap |
| `/o_market_store_add` | add store item |
| `/o_market_store_remove` | remove store item |
| `/o_market_store_toggle` | toggle store item |
| `/o_profile_set_default_bg` | default profile background |
| `/o_profile_set_default_featured` | default featured card |
| `/o_profile_set_premium` | premium status |
| `/o_profile_theme` | cosmetic theme |
| `/o_profile_border` | border cosmetic |
| `/o_profile_badge` | badge cosmetic |
| `/o_profile_preview` | owner preview |
| `/o_redeem_create` | create reward code |
| `/o_redeem_delete` | delete reward code |
| `/o_redeem_list` | list reward codes |
| `/o_set_hourly` | tune hourly rewards |
| `/o_set_daily` | tune daily rewards |
| `/o_set_weekly` | tune weekly rewards |
| `/o_set_monthly` | tune monthly rewards |
| `/o_announce` | post announcement |
| `/o_event` | activate event multiplier |
| `/o_emoji_panel` | interactive emoji panel |
| `/o_emoji_set` | set one emoji |
| `/o_emoji_reset` | reset one emoji |
| `/o_emoji_reset_all` | reset all emojis |
| `/o_achievement_grant` | grant achievement |
| `/o_achievement_remove` | remove achievement |
| `/o_achievement_reset` | reset achievements |
| `/o_season_create` | create season |
| `/o_season_end` | end season |
| `/o_season_pass_setup` | configure pass tier |
| `/o_season_add_cp` | add season CP |
| `/o_season_mission_create` | create mission |
| `/o_tournament_create` | create tournament |
| `/o_tournament_cancel` | cancel tournament |
| `/o_war_start` | force-start war |
| `/o_war_end` | force-end war |
| `/o_war_set_phase` | phase override |
| `/o_war_set_durations` | set phase durations |
| `/o_war_list` | list wars and queue |
| `/o_battle_unstuck` | clear stuck battle state |

## Subsystem Map by Directory

### `bot/data/`

| File | Role |
| --- | --- |
| `storage.py` | JSON load/save and lock management |
| `sqlite_store.py` | SQLite repos and bootstrap behavior |
| `supabase_sync.py` | extra sync surface |
| `defaults.py` / `schemas.py` / `constants.py` | default state and schema helpers |

### `bot/services/`

| File | Role |
| --- | --- |
| `market_service.py` | market bootstrapping and service logic |
| `trade_service.py` | trade bootstrapping and service logic |
| `battle_service.py` | battle bootstrapping and active-state syncing |

### `bot/utils/`

Start here when debugging system rules:

| File | Role |
| --- | --- |
| `cards_logic.py` | card creation/edit normalization |
| `attacks_logic.py` | attack catalog and assignment rules |
| `battle_state.py` | battle state helpers |
| `battle_engine_pdf.py` | battle compatibility helpers |
| `market_logic.py` | market rule helpers |
| `trade_logic.py` | trade state helpers |
| `pack_logic.py` | pack reward logic |
| `reward_logic.py` / `reward_grant.py` | reward handling |
| `profile_logic.py` | profile render helpers |
| `ui.py` | embed and UI helper functions |

## Battle-Specific Notes

`battle.py` is one of the highest-complexity files in the repo.

Important behavior to remember:

- ranked and friendly battles are both managed there
- battle UI is live-edited
- turn timers are owned by the battle cog
- runtime tasks are tracked and canceled by the cog
- active battle state is synced back into service/storage layers
- the current UI now renders as `3` embeds, not `5`

### Stamina System

Each fighter enters a battle with **100 stamina**. Every action drains it:

| Action | Stamina cost |
| --- | --- |
| Normal attack | 10 |
| Special | 20 |
| Ultimate | 35 |
| Unique Skill / Unique Path | 25 |
| Block / Dodge / Parry / Revert / Tank | 15 |

When stamina hits 0 the fighter is **exhausted** — locked to normal attacks only for the rest of the battle. Switching in a fresh fighter resets their stamina to 100. Stamina bar is shown in the battle embed alongside HP.

Stamina constants and deduction logic live in `bot/utils/battle_state.py` (`STAMINA_BASE`, `STAMINA_COST`). The embed rendering for the stamina bar is in `_build_embed_view` inside `bot/features/battle.py`.

Battle debugging files:

| File | Why you open it |
| --- | --- |
| `bot/features/battle.py` | queueing, battle UI, turn flow, timers |
| `bot/features/battle_views.py` | view/button/select components |
| `bot/features/battle_helpers.py` | helper glue |
| `bot/utils/battle_state.py` | state transitions and helpers |
| `tests/test_battle_engine.py` | battle rules regression |
| `tests/test_battle_freeze_regressions.py` | timeout/freeze regressions |

## Testing

### Full suite

```bash
cd /data/data/com.termux/files/home/Botaaa/Bot/bot2
pytest -q
```

### Compile check

```bash
cd /data/data/com.termux/files/home/Botaaa/Bot/bot2
python3 -m py_compile main.py bot/config.py bot/features/battle.py
```

### Focused suites

```bash
cd Bot/bot2
pytest -q tests/test_battle_engine.py tests/test_battle_freeze_regressions.py
pytest -q tests/test_owner_admin_helpers.py
pytest -q tests/test_trade_lifecycle.py tests/test_command_text_and_queue.py tests/test_sqlite_bootstrap.py
pytest -q tests/test_storage.py tests/test_race_conditions.py
pytest -q tests/test_onboarding_starter.py tests/test_tournament_rank_gate.py
```

### After reward or season fixes

Use this focused command:

```bash
cd Bot/bot2
pytest -q tests/test_onboarding_starter.py tests/test_battle_engine.py tests/test_battle_freeze_regressions.py tests/test_tournament_rank_gate.py
```

## Operator Checklist

```text
When bot2 breaks:

1. read logs/bot.log
2. confirm config/data paths
3. confirm extension load failures in startup logs
4. run focused pytest for the affected subsystem
5. inspect matching feature file
6. inspect matching utils helper
7. inspect service/data layer if persistence is involved
```

## Deploy Checklist

```text
For VPS/panel deploys:

1. fetch latest main
2. hard reset to origin/main
3. install requirements
4. restart launcher
5. if battle behavior still looks old, verify deployed commit hash
```

Recommended commands:

```bash
git fetch origin main
git reset --hard origin/main
pip install -U --prefix .local -r requirements.txt
python main.py
```

## Maintenance Hotspots

| Area | Files | Why it matters |
| --- | --- | --- |
| startup and sync | `main.py`, `bot/config.py` | extension load, command sync, token/path issues |
| content/admin | `bot/features/cards_admin.py`, `bot/utils/cards_logic.py`, `bot/utils/attacks_logic.py` | card and attack mutation |
| persistence | `bot/data/storage.py`, `bot/data/sqlite_store.py` | state integrity |
| battle runtime | `bot/features/battle.py`, `bot/features/battle_views.py` | timers, views, live updates |
| market/trade | `bot/features/market.py`, `bot/features/trades.py`, `bot/utils/trade_logic.py` | locked cards, listing state, trade lifecycle |
| social systems | `bot/features/gangs.py`, `alliance.py`, `gang_war.py` | large multi-user state changes |
| season/rewards | `bot/features/season.py`, `rewards.py`, `owner_rewards.py` | recurring progression systems |

## Final Memory Aid

```text
bot2 review order:

main.py
-> bot/config.py
-> bot/data/
-> bot/services/
-> bot/features/<affected system>
-> bot/utils/<matching logic helper>
-> tests/<matching regression file>
```

That order is usually the fastest way to understand or fix a bot2 issue without rereading the whole project.
