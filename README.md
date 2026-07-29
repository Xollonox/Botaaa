<p align="center">
  <img src="assets/logo.svg" alt="Botaaa" width="180" height="180">
</p>

<h1 align="center">Botaaa</h1>
<p align="center"><strong>Full-Stack Discord Bot Workspace</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/discord.py-latest-5865F2.svg" alt="discord.py">
  <img src="https://img.shields.io/badge/tests-185-green.svg" alt="185 tests">
  <img src="https://img.shields.io/badge/commands-100+-purple.svg" alt="100+ commands">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT">
</p>

---

## Overview

This workspace hosts two Discord bots that run concurrently via `launcher.py`:

| Bot | Directory | Purpose | Stack |
|-----|-----------|---------|-------|
| **Miss Kim** | `Bot/bot1/` | Conversational AI with image generation, vision, mood system | discord.py, OpenAI-compat LLMs (Cerebras, Groq, Ollama), Cloudflare AI |
| **Lookism CG** | `Bot/bot2/` | Gacha game bot: cards, battles, market, trades, gangs, wars, tournaments | discord.py, Firestore |

Each bot owns its commands, tests, and runtime data.

---

## Quick Start

```bash
git clone https://github.com/Xollonox/Botaaa.git
cd Botaaa
pip install -r requirements.txt
python launcher.py
```

### Environment Variables

| Variable | Required | Used By |
|----------|:--------:|---------|
| `DISCORD_TOKEN` | Yes | bot1 |
| `BOT_TOKEN` | Yes | bot2 |
| `LOOKISM_OWNER_IDS` | Yes | bot2 owner commands |
| `CEREBRAS_API_KEY` | No | bot1 |
| `GROQ_API_KEY` | No | bot1 |
| `OLLAMA_API_KEY` | No | bot1 (up to 5 keys) |
| `CLOUDFLARE_API_TOKEN` | No | bot1 |
| `FIREBASE_PROJECT_ID` | Yes | bot2 |
| `FIREBASE_CREDENTIALS_PATH` | Yes* | bot2 (path to service account JSON) |
| `FIREBASE_CREDENTIALS_JSON` | Yes* | bot2 (raw JSON alternative to path) |

*One of `FIREBASE_CREDENTIALS_PATH` or `FIREBASE_CREDENTIALS_JSON` is required.

See `.env.example` files in each bot directory for the full list.

---

## Architecture

```
Botaaa/
│
├── launcher.py                   # Process supervisor
├── requirements.txt
│
├── Bot/
│   ├── bot1/                     # Miss Kim — Conversational AI
│   │   ├── main.py               # Bot bootstrap
│   │   ├── config.py             # Env-based config
│   │   ├── commands.py           # Slash + prefix commands
│   │   ├── events.py             # Message listeners, auto-reply
│   │   ├── memory.py             # JSON per-user/channel memory
│   │   ├── persona.py            # Persona and mood system
│   │   ├── image.py              # Image gen + vision
│   │   ├── llm.py                # Multi-provider LLM with failover
│   │   └── tests/                # Regression tests
│   │
│   ├── bot2/                     # Lookism CG — Game Bot
│       ├── main.py               # LookismBot bootstrap (33 cogs)
│       ├── bot/
│       │   ├── config.py
│       │   ├── data/             # Firestore-backed storage + repos
│       │   ├── services/         # Battle, market, trade logic
│       │   ├── features/         # 32 slash-command cogs
│       │   └── utils/            # 29 utility modules
│       └── tests/                # Pytest regression suite
│   │
│
├── assets/                       # Logo and branding
└── docs/                         # Full documentation
```

---

## Bot1: Miss Kim

Conversational AI that roleplays as Yeonu Kim from the Lookism universe.

**Capabilities:**
- **Chat** — Natural conversation with memory, mood, and persona
- **Image Generation** — Cloudflare Flux + Pollinations backends
- **Vision** — Image analysis via Groq/Ollama vision models
- **Auto-Reply** — Keyword triggers, mention replies, DM handling

**AI Provider Chain:** Ollama → Qwen → Cerebras → Groq (automatic failover, 35-60s timeouts)

**Commands:** `/ask`, `/imagine`, `/pollo`, `/vision`, `/perchance`, `/mood`, `/language`, `/stats`, `/reset_memory`, `!kim`, `!purge`, `!say`

---

## Bot2: Lookism CG

Full-featured gacha card game bot with 80+ slash commands.

**Core Loop:** Register → Get packs → Open packs → Build squad → Battle → Earn rewards → Progress through seasons, achievements, leaderboards

**Feature Categories:**

| Category | Features |
|----------|----------|
| **Battle** | Ranked PvP, CPU battles, friendly duels, stamina system, 7-step damage pipeline, 6-type matchup system |
| **Economy** | Coins, premium gems, hourly/daily/weekly/monthly rewards, 10 pack types |
| **Market** | P2P marketplace with configurable fees, quick-sell, store listings |
| **Trades** | P2P card trading with rarity validation, trade offers board |
| **Social** | Gangs, alliances, gang wars with queue/battle/record system |
| **Progression** | Season pass (15 tiers), XP tournaments, achievements, 4 leaderboard types |
| **Squad** | Squad management, defensive setup, weapon equipping, keystone system |
| **Admin** | Visual card editor, owner economy controls, emoji customizer, server settings |

**Storage:** Firestore-backed persistence via the Firebase Admin SDK. The same `Storage` public API (`load`, `load_readonly`, `with_lock`, `save`, `async_save`) is preserved, and market/trade/battle repos have Firestore equivalents (`firestore_market_repo`, `firestore_trade_repo`, `firestore_battle_repo`). Requires `FIREBASE_PROJECT_ID` plus either `FIREBASE_CREDENTIALS_PATH` or `FIREBASE_CREDENTIALS_JSON`.

---

## Testing

```bash
# Run all tests
cd Bot/bot1 && pytest -q
cd Bot/bot2 && pytest -q

# Focused suites
cd Bot/bot2
pytest -q tests/test_battle_engine.py
pytest -q tests/test_trade_lifecycle.py
```

Tests across the workspace cover Discord command registration, AI routing,
reminders, event automation, battle formulas, trade lifecycle, and more.

---

## Dependencies

```
discord.py               # Bot framework
openai==1.37.1           # LLM API client (bot1)
aiohttp==3.10.10         # Async HTTP
pydantic==1.10.15        # Data validation
python-dotenv>=1.0.0     # .env loading
firebase-admin>=6.0.0    # Firestore persistence (bot2)
```

---

## Documentation

| File | Description |
|------|-------------|
| [`docs/BOT1_ARCHITECTURE.md`](docs/BOT1_ARCHITECTURE.md) | Bot1 architecture, AI provider chain, memory system, image pipeline |
| [`docs/BOT2_ARCHITECTURE.md`](docs/BOT2_ARCHITECTURE.md) | Bot2 architecture, extension loading, event flow, storage layer |
| [`docs/BATTLE_SYSTEM.md`](docs/BATTLE_SYSTEM.md) | Full battle damage pipeline, stamina, types, defense, ELO |
| [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) | Data flow through JSON + SQLite dual storage |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Production deployment guide |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Security audit and rotation guide |
| [`docs/ECONOMY_SYSTEM.md`](docs/ECONOMY_SYSTEM.md) | Economy, rewards, packs, market, trades |
| [`docs/API_INTEGRATION.md`](docs/API_INTEGRATION.md) | External API integrations |
| [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) | Data structure documentation |
| [`docs/COMMAND_REFERENCE.md`](docs/COMMAND_REFERENCE.md) | All commands for both bots |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Contribution guidelines |

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Built with discord.py · Powered by Cerebras, Groq, Ollama, Cloudflare</sub>
</p>
