# Botaaa

> Repo guide for the full Discord bot workspace.
>
> This repository currently has two real bots:
> - `Bot/bot1` -> Miss Kim chat/image bot
> - `Bot/bot2` -> Lookism card/economy/battle bot
>
> `Bot/bot3` and `Bot/bot4` exist but are placeholders only.

## Quick Start

```bash
cd /data/data/com.termux/files/home/Botaaa
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python launcher.py
```

## Startup Modes

Use the mode that matches where you are running the repo.

| Environment | Recommended start path | Notes |
| --- | --- | --- |
| Termux / local CLI | `python launcher.py` from repo root | starts `bot1` and `bot2` together |
| Desktop terminal | `python launcher.py` or run each bot separately | same behavior as local CLI |
| VPS / panel startup command | pull/reset repo, install deps, then `python launcher.py` | avoid dirty-worktree deploy scripts that skip pulls |
| Debugging one bot only | `cd Bot/bot1 && python main.py` or `cd Bot/bot2 && python main.py` | best for focused logs |

## Start Guide

### Local CLI / Termux

```bash
cd /data/data/com.termux/files/home/Botaaa
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python launcher.py
```

### Desktop terminal

```bash
git clone <repo-url>
cd Botaaa
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python launcher.py
```

### Run a single bot

```bash
cd Bot/bot1
python main.py
```

```bash
cd Bot/bot2
python main.py
```

### VPS / panel deploy flow

Minimum safe sequence:

```bash
git fetch origin main
git reset --hard origin/main
pip install -U --prefix .local -r requirements.txt
python launcher.py
```

Avoid using deploy scripts that:

- skip pulls because `git status` is dirty from logs or cache folders
- embed a live GitHub token directly in the script
- treat tracked runtime logs as normal source files

## Recent Fixes

Recent repo fixes worth knowing before debugging runtime behavior:

| Commit | Area | Fix |
| --- | --- | --- |
| `3bc739b` | `bot2` rewards / season | fixed battle reward crash from missing milestone-pack helper and fixed `/season_missions` missing `e(...)` import |
| `b5a6296` | `bot2` battle UI | reduced live battle panel from 5 embeds to 3 embeds |
| `dd34919` | docs | expanded repo, `bot1`, and `bot2` READMEs |

## What This Repo Contains

| Path | Purpose | Status |
| --- | --- | --- |
| `launcher.py` | Starts multiple bot processes and restarts them if they exit | Active |
| `requirements.txt` | Shared top-level Python dependencies | Active |
| `Bot/bot1/` | Miss Kim AI chat/image bot | Active |
| `Bot/bot2/` | Lookism game bot with cards, market, trade, gangs, season, battle | Active |
| `Bot/bot3/` | Placeholder bot | Inactive |
| `Bot/bot4/` | Placeholder bot | Inactive |

## Repo Mindmap

```text
Botaaa
|
+-- launcher.py
|   +-- starts bot1
|   +-- starts bot2
|   +-- restarts crashed child process after 3s
|
+-- Bot/
|   +-- bot1/
|   |   +-- main.py
|   |   +-- commands.py
|   |   +-- events.py
|   |   +-- memory.py
|   |   +-- persona.py
|   |   +-- image.py
|   |   +-- llm.py
|   |   +-- README.md
|   |
|   +-- bot2/
|   |   +-- main.py
|   |   +-- bot/config.py
|   |   +-- bot/data/
|   |   +-- bot/features/
|   |   +-- bot/services/
|   |   +-- bot/utils/
|   |   +-- tests/
|   |   +-- README.md
|   |
|   +-- bot3/
|   +-- bot4/
|
+-- README.md
```

## How Startup Works

### `launcher.py`

`launcher.py` is the repo-level entrypoint.

Behavior:

1. Resolves repo root.
2. Looks only at `Bot/bot1` and `Bot/bot2`.
3. Runs each bot with its own working directory.
4. Watches child processes forever.
5. If a child exits, waits 3 seconds and restarts it.
6. On `Ctrl+C`, sends `SIGINT`, then terminates remaining children.

Important detail:

- `Bot/bot3` and `Bot/bot4` are not included in `BOT_DIRS`, so the launcher ignores them.

## Standard Commands

### Run the whole repo

```bash
python launcher.py
```

### Run only bot1

```bash
cd Bot/bot1
python main.py
```

### Run only bot2

```bash
cd Bot/bot2
python main.py
```

### Compile-check main entrypoints

```bash
python3 -m py_compile launcher.py Bot/bot1/main.py Bot/bot2/main.py
```

### Install shared repo deps

```bash
pip install -r requirements.txt
```

### Pull latest code safely

```bash
git fetch origin main
git reset --hard origin/main
```

## Validation Commands

Use these before pushing bot changes.

### Root-level quick checks

```bash
python3 -m py_compile launcher.py Bot/bot1/main.py Bot/bot2/main.py
git diff --check
git status --short
```

### Bot1 checks

```bash
cd Bot/bot1
pytest -q
```

### Bot2 checks

```bash
cd Bot/bot2
pytest -q
```

Focused bot2 examples:

```bash
cd Bot/bot2
pytest -q tests/test_battle_engine.py tests/test_battle_freeze_regressions.py
pytest -q tests/test_owner_admin_helpers.py
pytest -q tests/test_trade_lifecycle.py tests/test_sqlite_bootstrap.py
```

## Dependency Notes

Top-level `requirements.txt` currently installs:

| Package | Why it exists |
| --- | --- |
| `discord.py` | Discord bot framework |
| `openai==1.37.1` | LLM/image client surface |
| `beautifulsoup4` | Parsing / scraping helper usage |
| `youtube-search-python` | Search utility |
| `pydantic==1.10.15` | Data validation models |
| `httpx==0.27.2` | HTTP client |
| `aiohttp==3.10.10` | Async HTTP client |
| `Pillow>=10.0.0` | Image processing |
| `python-dotenv>=1.0.0` | `.env` loading for env-based config |

## Bot Ownership Map

| Bot | Role | Primary Interface |
| --- | --- | --- |
| `bot1` | conversational AI, image generation, image analysis, chat moderation helpers | prefix + slash + message listeners |
| `bot2` | game economy, packs, collection, trade, gangs, war, season, battle | mostly slash commands |

## Review Hotspots

If you need to audit this repo later without rereading everything, start here:

| Area | File / directory | Why it matters |
| --- | --- | --- |
| multi-bot startup | `launcher.py` | restart loop, cwd handling, process supervision |
| bot1 secrets/config | `Bot/bot1/config.py` and `.env` | runtime token/model/provider config |
| bot1 chat behavior | `Bot/bot1/commands.py`, `events.py`, `persona.py`, `memory.py` | AI behavior, auto replies, image triggers, memory |
| bot2 startup | `Bot/bot2/main.py` | extension loading, command sync, storage/service bootstrap |
| bot2 data storage | `Bot/bot2/bot/data/` | JSON + SQLite state, migration/bootstrap behavior |
| bot2 gameplay | `Bot/bot2/bot/features/battle.py` and `bot/utils/` | most complex runtime path |
| bot2 admin/owner controls | `Bot/bot2/bot/features/cards_admin.py` and owner command files | high-impact content mutation commands |

## Safe Workflow

```text
Edit one bot at a time
-> run py_compile
-> run focused tests
-> run broader tests if the change touched shared systems
-> review git diff
-> commit
-> push
```

## Deploy Notes

| Problem | Typical cause | Fast fix |
| --- | --- | --- |
| server still runs old code | deploy script skipped pull due to dirty git state | `git fetch origin main && git reset --hard origin/main` |
| battle UI still shows 5 embeds | server never restarted updated `bot2` code | redeploy and restart after commit `b5a6296` or later |
| startup script aborts on dirty repo | tracked `Bot/bot2/logs/bot.log` or generated `.local`, `.cache`, `backup` folders | reset hard and clean generated folders in deploy step |
| deploy logs expose token | token embedded in clone or remote URL | revoke token, replace it, prefer env vars |

## Per-Bot Documentation

- [`Bot/bot1/README.md`](Bot/bot1/README.md)
- [`Bot/bot2/README.md`](Bot/bot2/README.md)
