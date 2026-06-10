# 🎮 Botaaa — Full-Stack Discord Bot Workspace

> **Warning:** This repository contains **hardcoded API tokens** (Discord, Cerebras, Groq, Cloudflare, Supabase) in source files. Do **not** push to a public repo without rotating all secrets first. See [`SECURITY.md`](docs/SECURITY.md).

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Bot1: Miss Kim (Chat/Image AI)](#bot1-miss-kim-chatimage-ai)
- [Bot2: Lookism HXCC (Game Bot)](#bot2-lookism-hxcc-game-bot)
- [Data Layer](#data-layer)
- [Security & Secrets](#security--secrets)
- [Deployment](#deployment)
- [Testing](#testing)
- [Documentation Index](#documentation-index)

---

## 🏗 Overview

This workspace hosts **two production Discord bots** that run concurrently via `launcher.py`:

| Bot | Directory | Purpose | Tech Stack |
|-----|-----------|---------|------------|
| **Miss Kim** (`bot1`) | `Bot/bot1/` | Conversational AI chatbot with image generation, vision analysis, mood system, and Lookism lore | discord.py, OpenAI-compat LLMs (Cerebras, Groq, Ollama), Cloudflare AI, Pollinations |
| **Lookism HXCC** (`bot2`) | `Bot/bot2/` | Full-featured gacha game bot: cards, packs, market, trades, gangs, alliances, war, PvP battles, tournaments, seasons, achievements | discord.py, SQLite + JSON storage, PIL (profile rendering), Supabase sync |
| **Placeholder** (`bot3/4`) | `Bot/bot3/`, `Bot/bot4/` | Not enabled | — |

**Stats:**
- ~95+ source files
- 127 regression tests
- 80+ slash commands across both bots
- 26 card definitions with full stat/move/skill systems
- 4 AI providers (Ollama, Cerebras, Groq, Qwen) with automatic fallback
- 3 data stores (JSON file, SQLite WAL-mode, Supabase REST)

---

## 🏛 Architecture

```
Botaaa/
│
├── launcher.py                    # Process supervisor: spawns bot1 + bot2, restarts on crash
│
├── Bot/
│   ├── bot1/                      # Miss Kim — Conversational AI
│   │   ├── main.py                #   discord.py Bot bootstrap
│   │   ├── config.py              #   Env-based config (tokens, models, URLs)
│   │   ├── commands.py            #   Slash + prefix + hybrid command handlers
│   │   ├── events.py              #   on_message listener, auto-reply, image triggers
│   │   ├── memory.py              #   JSON-backed per-user/channel conversation memory
│   │   ├── persona.py             #   Yeonu Kim persona, mood system, language detection
│   │   ├── image.py               #   Image gen (Cloudflare/Pollinations), vision, Perchance
│   │   ├── llm.py                 #   Multi-provider LLM client with failover chain
│   │   └── tests/                 #   Regression tests
│   │
│   ├── bot2/                      # Lookism HXCC — Game Bot
│   │   ├── main.py                #   LookismBot bootstrap, 32 extension cogs
│   │   ├── bot/
│   │   │   ├── config.py          #   Token, owner IDs, paths (⚠️ HARDCODED TOKEN)
│   │   │   ├── data/              #   Storage layer
│   │   │   │   ├── storage.py     #     Thread-safe JSON with cache + atomic writes
│   │   │   │   ├── sqlite_store.py#     SQLite repos (WAL mode) for market/trade/battle
│   │   │   │   ├── supabase_sync.py#    Background Supabase sync for website
│   │   │   │   ├── defaults.py    #     Complete default game state (3000+ lines)
│   │   │   │   ├── constants.py   #     Rarity icons, price bands, embed colors
│   │   │   │   ├── schemas.py     #     TypedDict schemas for mypy
│   │   │   │   └── cards.json     #     26 card definitions with moves/stats/skills
│   │   │   ├── services/          #   Business logic layer
│   │   │   │   ├── battle_service.py
│   │   │   │   ├── market_service.py
│   │   │   │   └── trade_service.py
│   │   │   ├── features/          #   32 slash-command cogs
│   │   │   │   ├── onboarding.py  #     /start, /help, terms gate
│   │   │   │   ├── battle.py      #     ~2922 lines — ranked PvP, CPU, turn system
│   │   │   │   ├── battle_views.py#     UI components for battles
│   │   │   │   ├── battle_helpers.py#   CPU AI, move normalization
│   │   │   │   ├── trades.py      #     P2P trading system
│   │   │   │   ├── trade_views.py #     Trade panel UI
│   │   │   │   ├── market.py      #     Player marketplace
│   │   │   │   ├── market_views.py#     Market browse/buy UI
│   │   │   │   ├── market_owner.py#     Owner market controls
│   │   │   │   ├── packs.py       #     Pack purchase + management
│   │   │   │   ├── packs_panel.py #     Pack opening animation UI
│   │   │   │   ├── shop.py        #     Pack shop browser
│   │   │   │   ├── inventory.py   #     Card collection browser
│   │   │   │   ├── squad.py       #     Squad management panel
│   │   │   │   ├── profile.py     #     Player profile
│   │   │   │   ├── profile_render.py#   PIL-based profile card image (~700 lines)
│   │   │   │   ├── profile_owner.py#   Owner profile customization
│   │   │   │   ├── economy.py     #     Balance, owner grants
│   │   │   │   ├── rewards.py     #     Hourly/daily/weekly/monthly rewards
│   │   │   │   ├── owner_rewards.py#    Owner reward config
│   │   │   │   ├── season.py      #     Season pass + missions (15 tiers)
│   │   │   │   ├── tournament.py  #     XP race tournaments
│   │   │   │   ├── achievements.py#     Achievement system
│   │   │   │   ├── gangs.py       #     Gang management (roles, invites)
│   │   │   │   ├── alliance.py    #     Alliance system for gangs
│   │   │   │   ├── gang_war.py    #     Full war system (queue, battle, record)
│   │   │   │   ├── leaderboards.py#     Global/league/gang/alliance LBs
│   │   │   │   ├── cards_admin.py #     Visual card editor (add/edit/delete)
│   │   │   │   ├── card_tools.py  #     /card_info lookup
│   │   │   │   ├── weapons.py     #     Weapon inventory + equip/unequip
│   │   │   │   ├── keystones.py   #     Mythical+ card keystones
│   │   │   │   ├── redeem.py      #     Reward code system
│   │   │   │   ├── confirm.py     #     Action confirmation pipeline
│   │   │   │   ├── emoji_panel.py #     UI emoji customizer
│   │   │   │   ├── tutorial.py    #     5-step new player tutorial
│   │   │   │   ├── server_settings.py#  Guild admin settings
│   │   │   │   ├── announce_owner.py#   Card of the Day + Bounty loops
│   │   │   │   └── help_index.py  #     Help category definitions
│   │   │   └── utils/             #   25 utility modules
│   │   │       ├── battle_state.py#     Core combat engine (~1371 lines)
│   │   │       ├── battle_engine_pdf.py#Compatibility damage helpers
│   │   │       ├── typing_matchup.py#   Type system (6 types, multipliers)
│   │   │       ├── cards_logic.py #     Card def/instance/power/scaling
│   │   │       ├── attacks_logic.py#    Attack catalog + assignment
│   │   │       ├── weapon_logic.py#     Weapon buffs + upgrade
│   │   │       ├── squad_logic.py #     Squad helpers
│   │   │       ├── market_logic.py#     Listing/pricing/embed building
│   │   │       ├── trade_logic.py #     Trade card transfer
│   │   │       ├── economy_logic.py#    Balance/cooldown helpers
│   │   │       ├── xp_logic.py    #     XP/CP tables, milestones
│   │   │       ├── pack_logic.py  #     Pack opening + pity system
│   │   │       ├── reward_logic.py#     Rate validation
│   │   │       ├── reward_grant.py#     Reward granting
│   │   │       ├── achievement_logic.py# Achievement CRUD
│   │   │       ├── gang_logic.py  #     Role hierarchy
│   │   │       ├── alliance_logic.py#   Alliance helpers
│   │   │       ├── war_logic.py   #     War matchmaking + scoring
│   │   │       ├── season_logic.py#     Season pass + reset
│   │   │       ├── redeem_logic.py#     Code validation
│   │   │       ├── confirm_pipeline.py# Action staging
│   │   │       ├── profile_logic.py#    Embed profile builder
│   │   │       ├── interaction_visibility.py# Reply helpers
│   │   │       ├── server_rules.py#     Channel mode enforcement
│   │   │       ├── inventory_api.py#    Card instance API
│   │   │       ├── logging_setup.py#    Logging config
│   │   │       ├── timeutil.py   #     now_ts() helper
│   │   │       ├── ui.py         #     Emoji/embed/box helpers
│   │   │       └── checks.py     #     Permission checks
│   │   │
│   │   ├── tests/                 #   17 test files, 127 tests
│   │   ├── logs/bot.log           #   Runtime log output (~3100+ lines)
│   │   ├── BATTLE_MECHANICS.md    #   Damage formula reference
│   │   └── mindmap.txt            #   Architecture mind map
│   │
│   ├── bot3/main.py               # Placeholder (raises SystemExit)
│   └── bot4/main.py               # Placeholder (raises SystemExit)
│
├── lookism_data.json              # JSON game state (4227 lines)
├── lookism_data.sqlite3            # SQLite runtime state
├── bot_memory.json                 # bot1 conversation memory
├── bot_settings.json               # bot1 config overrides
├── requirements.txt                # Shared Python dependencies
└── DISCORD_BOT_REVIEW.md           # External code review
```

---

## 🚀 Quick Start

### One-Command Start (Recommended)
```bash
git clone <repo-url> && cd Botaaa && pip install -r requirements.txt && python launcher.py
```

### Step-by-Step
```bash
# 1. Clone and enter
git clone <repo-url>
cd Botaaa

# 2. (Optional) Virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables (or edit config files)
export DISCORD_TOKEN="your_token_here"

# 5. Run
python launcher.py         # Starts bot1 + bot2
# OR
cd Bot/bot1 && python main.py   # Run only Miss Kim
# OR
cd Bot/bot2 && python main.py   # Run only Lookism HXCC
```

### Environment Variables
| Variable | Required | Default | Used By |
|----------|----------|---------|---------|
| `DISCORD_TOKEN` | **Yes** | — | Both bots |
| `CEREBRAS_API_KEY` | No | — | bot1 |
| `CEREBRAS_API_KEY_2` | No | — | bot1 |
| `GROQ_API_KEY` | No | — | bot1 |
| `GROQ_API_KEY_2` | No | — | bot1 |
| `OLLAMA_API_KEY` | No | — | bot1 (up to 5 keys) |
| `CLOUDFLARE_ACCOUNT_ID` | No | — | bot1 |
| `CLOUDFLARE_API_TOKEN` | No | — | bot1 |
| `LOOKISM_SQLITE_PATH` | No | `bot2/lookism_data.sqlite3` | bot2 |
| `SUPABASE_URL` | No | Hardcoded | bot2 |
| `SUPABASE_SERVICE_ROLE_KEY` | No | Hardcoded | bot2 |

---

## 🤖 Bot1: Miss Kim (Chat/Image AI)

> **Files:** `Bot/bot1/` (9 source files + tests)

### What It Does
Miss Kim is a conversational AI that roleplays as **Yeonu Kim** (a Generation 0 veteran operative from the Lookism webtoon universe). It handles:
- **Chat** — Natural conversation with memory, mood, and persona
- **Image Generation** — Cloudflare Flux + Pollinations (free) backends
- **Vision** — Image analysis via Groq/Ollama vision models
- **Image Enhancement** — Prompt expansion + img2img editing
- **Perchance** — Random output from Perchance generators
- **Auto-Reply** — Keyword triggers, mention replies, DM handling

### AI Provider Chain
The bot tries providers in this order until one succeeds:
```
1. Ollama (Cloud) — primary, 5 API keys rotated
2. Qwen Fallback — secondary Ollama model
3. Cerebras — 2 API keys rotated
4. Groq Search — only for Lookism queries
5. Groq — universal fallback
```

Each provider has a 35-60s timeout. If all fail, returns "I could not reach the AI backend right now."

### Mood System
5 clean moods (no jailbreak—review removed the old "lust" and "dark" moods):
- **calm** — Composed, direct, slightly cryptic
- **warm** — Genuinely caring, mentor-like
- **serious** — Terse, no-nonsense
- **sarcastic** — Dry wit, side-eye energy
- **playful** — Light banter, teasing

### Memory System
- **Scope:** Per-user + per-guild + per-channel
- **Storage:** JSON file (`bot_memory.json`)
- **Limit:** 40 lines/user, trimmed to 300 chars/line
- **Summarization:** Every 10 messages, an LLM call summarizes the conversation
- **Lock:** `asyncio.Lock()` for file writes

### Image Pipeline
```
User Prompt → LLM Enhancement (vision or text)
           → Cloudflare Flux (txt2img) OR Pollinations (free)
           → Optionally: img2img via Flux2 Dev or SD 1.5
           → Return bytes → Discord file attachment
```

### Commands (20+)
| Command | Type | Description |
|---------|------|-------------|
| `/ask <text>` | Hybrid | Main ask-anything command |
| `!kim <text>` | Prefix | Direct conversational reply |
| `/imagine <prompt>` | Slash | Generate image (Cloudflare) |
| `/pollo <prompt>` | Slash | Generate free image (Pollinations) |
| `/vision <image>` | Slash | Analyze an image |
| `/perchance <generator>` | Hybrid | Random Perchance output |
| `/mood <mood>` | Hybrid | Change channel mood |
| `/language <lang>` | Hybrid | Set channel language |
| `/reset_memory` | Slash | Reset conversation memory |
| `/stats` | Slash | Bot statistics |
| `!purge <n>` | Prefix | Bulk delete messages |
| `!say <text>` | Prefix | Speak as the bot |
| `@pollo <prompt>` | Trigger | Auto image generation |
| `@imagine <prompt>` | Trigger | Auto image generation |

---

## 🎮 Bot2: Lookism HXCC (Game Bot)

> **Files:** `Bot/bot2/` (70+ source files, 17 test files)

### Core Game Loop
```
Register (/start) → Get packs (starter/shop/rewards)
→ Open packs (/packs) → Build squad (/squad)
→ Battle (/battle) → Earn rewards (coins/XP/CP/trophies)
→ Progress through seasons, achievements, leaderboards
→ Social: gangs, alliances, war, market, trades
```

### Economy System
- **Coins** — Main currency (earned from battles, rewards, market sales)
- **Premium Gems** — Premium currency (earned from season pass, milestones)
- **Packs** — 10 pack types (Newbie → Ranker), weighted rarity drops
- **Market** — P2P listing marketplace with configurable fee
- **Trades** — P2P card trading with rarity-matching validation
- **Rewards** — Hourly (100 coins), Daily (150 coins or Common card), Weekly, Monthly

### Battle System (Most Complex Subsystem)
**Files:** `battle.py` (~2922 lines) + `battle_views.py` + `battle_helpers.py` + `battle_state.py` (~1371 lines)

**Damage Pipeline (7 steps):**
1. **Miss Check** — BIQ vs BIQ comparison
2. **Base Roll** — STR/2 ± range by move type (Normal: ±5, Special: +20..+45, Ultimate: 3x..4x)
3. **Strength Bonus** — +10/+15/+30 if Strength mastery or STR > 100
4. **Technique Multiplier** — 1.04x to 1.30x based on TEC bands
5. **IQ Scaling** — Attacker +IQ%, Defender −IQ%
6. **Typing Multiplier** — 6-type system (Tank/Fighter/Brawler/Speedster/Assassin/Mastermind)
7. **Defense Resolution** — Block/Dodge/Parry/Revert/Tank

**Stamina System:**
- 100 stamina per fighter per battle
- Normal = 10, Special = 20, Ultimate = 35, Unique Skill/Path = 25, Defense = 15
- Exhausted fighters locked to normal attacks only

**Matchmaking:**
- Adaptive trophy bracket (widens over time up to 60s)
- CPU fallback after 60s (personality-based AI)
- Anti-farm: daily CPU trophy cap (100), scaling rewards after 3/6 recent CPU wins

### Storage Architecture (Dual System)
```
┌─────────────────────┐     ┌─────────────────────┐
│     JSON File        │     │      SQLite DB       │
│  lookism_data.json   │     │  lookism_data.sqlite3│
│                      │     │                      │
│ • Players/inventory  │     │ • Market listings     │
│ • Cards catalog      │     │ • Trade pending/hist  │
│ • Gangs/alliances    │     │ • Battle queue/active │
│ • Season/tournament  │     │ • Battle pending_fr.  │
│ • Config/settings    │     │ • App migrations      │
│ • Achievements       │     │ • Trade offer board   │
│ • Redeem codes       │     │                      │
└─────────────────────┘     └─────────────────────┘
        ↕ (bootstrap)                ↕
   ┌────────────────────────────────────────┐
   │          Storage + Services            │
   │  with_lock(mutate) atomic operations   │
   └────────────────────────────────────────┘
```

### Full Command Map (80+ commands)

**Public Commands:**
| Category | Commands |
|----------|----------|
| Onboarding | `/start`, `/help`, `/confirm` |
| Profile | `/profile`, `/collection`, `/card_info`, `/card_lock` |
| Squad | `/squad`, `/defensive_squad_setup` |
| Economy | `/balance`, `/hourly`, `/daily`, `/weekly`, `/monthly` |
| Battle | `/battle`, `/battle_cancel`, `/friendly`, `/friendly_cancel`, `/forfeit` |
| Market | `/market browse`, `/market add`, `/market remove` |
| Trade | `/trade start`, `/trade cancel`, `/trade history`, `/trade post`, `/trade board`, `/trade accept`, `/trade cancel_offer` |
| Packs | `/packs`, `/shop` |
| Tournament | `/tournament`, `/tournament_battle` |
| Season | `/season` |
| Progression | `/achievements`, `/lb global`, `/lb league`, `/lb gang`, `/lb alliance` |
| Social | `/gang create/info/invite/join/leave/kick/promote/demote/...`, `/alliance create/info/invite/leave`, `/gang_war start/status/attack/record` |
| Items | `/weapon`, `/keystone_assign`, `/keystone_info` |
| Tutorial | `/tutorial` |
| Redeem | `/redeem` |
| Server Admin | `/server_mode`, `/server_set_channel`, `/server_set_announce`, `/server_set_battle` |

**Owner Commands** (all prefixed with `/o` or under `/o` group):
| Category | Commands |
|----------|----------|
| Cards | `/o add_card`, `/o edit_card`, `/o delete_card`, `/o add_attack`, `/o edit_attack`, `/o delete_attack`, `/o list_attacks`, `/o assign_attack`, `/o remove_attack`, `/o view_card_attacks` |
| Economy | `/o_add_balance`, `/o_add_premium`, `/o_set_hourly`, `/o_set_daily`, `/o_set_weekly`, `/o_set_monthly` |
| Market | `/o_market_toggle`, `/o_market_set_fee`, `/o_market_set_max_listings`, `/o_market_remove`, `/o_market_set_quick_sell`, `/o_market_store_add`, `/o_market_store_remove`, `/o_market_store_toggle` |
| Profile | `/o_profile_set_default_bg`, `/o_profile_set_default_featured`, `/o_profile_set_premium`, `/o_profile_theme`, `/o_profile_border`, `/o_profile_badge`, `/o_profile_preview` |
| Season | `/o_season_create`, `/o_season_end`, `/o_season_pass_setup`, `/o_season_add_cp`, `/o_season_mission_create` |
| Tournament | `/o_tournament_create`, `/o_tournament_cancel` |
| War | `/o_war_start`, `/o_war_end`, `/o_war_set_phase`, `/o_war_set_durations`, `/o_war_list` |
| Content | `/o_pack`, `/o_shop_pack_list`, `/o_shop_pack_set_enabled`, `/o_announce`, `/o_event`, `/o_feature_card`, `/o_special_offer` |
| Achievements | `/o_achievement_grant`, `/o_achievement_remove`, `/o_achievement_reset` |
| Redeem | `/o_redeem_create`, `/o_redeem_delete`, `/o_redeem_list` |
| System | `/o_emoji_panel`, `/o_emoji_set`, `/o_emoji_reset`, `/o_emoji_reset_all` |
| Battle | `/o_battle_unstuck` |

---

## 🔐 Security & Secrets

**⚠️ CRITICAL: This repo has hardcoded secrets that MUST be rotated before any public exposure:**

| Location | Secret | Risk |
|----------|--------|------|
| `Bot/bot2/bot/config.py:5` | **Discord BOT_TOKEN** (MTQ2OTM4MzI3MTgyNDQ5MDcxOQ.GJRzn8.dha4uARmFlygx6bG1_YHmkbsumNeLgoBzJ6foQ) | Full bot access |
| `.env` (if committed) | Cerebras/Groq/Ollama API keys | AI API abuse |
| `Bot/bot2/bot/data/supabase_sync.py` | Supabase URL + service role key | Database access |
| `Bot/bot1/config.py` | Default keys (overridable by env) | Multi-provider API access |

See [`SECURITY.md`](docs/SECURITY.md) for the full security audit.

---

## 🧪 Testing

```bash
# Run all tests (from repo root)
cd Bot/bot1 && pytest -q
cd Bot/bot2 && pytest -q

# Compile-check all entrypoints
python3 -m py_compile launcher.py Bot/bot1/main.py Bot/bot2/main.py

# Bot2 focused test suites
cd Bot/bot2
pytest -q tests/test_battle_engine.py tests/test_battle_freeze_regressions.py
pytest -q tests/test_owner_admin_helpers.py
pytest -q tests/test_trade_lifecycle.py tests/test_sqlite_bootstrap.py
pytest -q tests/test_storage.py tests/test_race_conditions.py
pytest -q tests/test_onboarding_starter.py tests/test_tournament_rank_gate.py
pytest -q tests/test_typing_matchup.py
```

**Test Coverage:** 127 tests across 17 test files covering:
- Battle damage formulas (73 tests)
- Typing matchups (17 tests)
- Storage race conditions
- SQLite bootstrap migrations
- Trade lifecycle validation
- Card fusion logic
- Tournament rank gates
- Daily trophy caps
- Shop purchase flows
- Owner admin helpers
- Profile context extraction
- Command text consistency

---

## 📚 Documentation Index

| File | Description |
|------|-------------|
| [`docs/BOT1_ARCHITECTURE.md`](docs/BOT1_ARCHITECTURE.md) | Complete bot1 architecture, AI provider chain, memory system, image pipeline |
| [`docs/BOT2_ARCHITECTURE.md`](docs/BOT2_ARCHITECTURE.md) | Complete bot2 architecture, extension loading, event flow, storage layer |
| [`docs/BATTLE_SYSTEM.md`](docs/BATTLE_SYSTEM.md) | Full battle damage pipeline, stamina, types, defense, ELO, formulas |
| [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) | How data flows through JSON + SQLite dual storage |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Production deployment guide |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Security audit, known vulnerabilities, rotation guide |
| [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) | Complete data structure documentation |
| [`docs/COMMAND_REFERENCE.md`](docs/COMMAND_REFERENCE.md) | All commands for both bots |
| [`docs/ECONOMY_SYSTEM.md`](docs/ECONOMY_SYSTEM.md) | Economy, rewards, packs, market, trades |
| [`docs/API_INTEGRATION.md`](docs/API_INTEGRATION.md) | All external API integrations |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Contribution guidelines |
| [`Bot/bot2/BATTLE_MECHANICS.md`](Bot/bot2/BATTLE_MECHANICS.md) | In-depth battle formulas (existing) |
| [`DISCORD_BOT_REVIEW.md`](DISCORD_BOT_REVIEW.md) | External architecture review |

---

## 🔄 Data Flow Summary

```
User Interaction (Discord)
    │
    ├── bot1 path:
    │   on_message() → rate_limit check → trigger detection
    │   → vision/image handling → LLM fallback chain
    │   → memory update → response
    │
    └── bot2 path:
        LookismBot.interaction_check() → terms gate
        → Cog handler → storage.with_lock(mutate)
        → SQLite update → response + embeds
```

---

## ⚠️ Known Issues & Technical Debt

1. **Hardcoded Secrets** — See [SECURITY.md](docs/SECURITY.md)
2. **No Log Rotation** — `bot.log` grows unbounded
3. **JSON Storage Race** — `bot1` uses `asyncio.Lock()` but `bot2` uses `threading.Lock()`
4. **No Rate Limiting on LLM Calls** — Can hit API limits under load
5. **Profile Rendering Depends on Local Fonts** — Requires specific font paths
6. **Supabase Key in Source** — Service role key with full DB access in `supabase_sync.py`
7. **Test Coverage Gaps** — No integration tests for Discord UI flows
8. **No Graceful Shutdown** — `launcher.py` uses SIGINT, but in-flight battles may corrupt state

---

## 📦 Dependencies

```
discord.py               # Bot framework
openai==1.37.1           # LLM API client
beautifulsoup4           # Web scraping
youtube-search-python    # YouTube search
pydantic==1.10.15        # Data validation
httpx==0.27.2            # HTTP client
aiohttp==3.10.10         # Async HTTP client
Pillow>=10.0.0           # Image processing
python-dotenv>=1.0.0     # .env loading
```

---

## 👥 Maintenance Hotspots

| Area | Files | Why It Matters |
|------|-------|----------------|
| **Battle Engine** | `battle.py`, `battle_state.py`, `battle_views.py` | Most complex code path (~4300 lines combined) |
| **Data Integrity** | `storage.py`, `sqlite_store.py`, `defaults.py` | Corruption = lost player data |
| **Card Catalog** | `cards_admin.py`, `cards_logic.py`, `cards.json` | All 26 card definitions |
| **Economy Balance** | `rewards.py`, `rewards.py`, `economy.py` | Inflation/deflation risk |
| **AI Fallback** | `llm.py`, `image.py` | All 5 providers must be reliable |
| **Secrets** | `config.py` (both) | Token rotation + .env migration |
