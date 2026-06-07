# Bot1 README

> `bot1` is the Miss Kim conversational Discord bot.
>
> It mixes:
> - chat replies
> - slash commands
> - prefix commands
> - image generation
> - image analysis
> - channel-scoped memory and mood behavior

## Entry Point

Run from the `Bot/bot1` directory:

```bash
cd /data/data/com.termux/files/home/Botaaa/Bot/bot1
python main.py
```

`main.py`:

- enables `message_content`
- enables `members`
- uses prefix `!`
- loads `commands` extension
- loads `events` extension
- starts with `DISCORD_TOKEN`

## Setup

```bash
cd /data/data/com.termux/files/home/Botaaa/Bot/bot1
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

If you want shell-exported env vars first:

```bash
set -a
. ./.env
set +a
python main.py
```

## Directory Map

| File | Purpose |
| --- | --- |
| `main.py` | bot bootstrap and extension loading |
| `config.py` | loads `.env`, defines token/provider/model settings |
| `commands.py` | slash, hybrid, and prefix commands |
| `events.py` | message listeners, auto-replies, image triggers, error logging |
| `llm.py` | LLM fallback chain / model call layer |
| `image.py` | image generation, image prompt improvement, vision helpers |
| `memory.py` | persistent memory, summaries, per-user/channel state |
| `persona.py` | mood, tone, lore prompt construction, language detection |
| `tests/test_remember_line.py` | focused regression for memory behavior |

## Bot1 Mindmap

```text
bot1
|
+-- main.py
|   +-- creates commands.Bot(prefix="!")
|   +-- loads commands.py
|   +-- loads events.py
|
+-- commands.py
|   +-- manual command entrypoints
|   +-- image slash commands
|   +-- memory controls
|   +-- admin tools
|
+-- events.py
|   +-- on_message listener
|   +-- auto image trigger handling
|   +-- mention/reply/DM chat handling
|   +-- rate limiting
|
+-- memory.py
|   +-- remembers lines
|   +-- summarizes long chats
|   +-- stores channel settings
|
+-- persona.py
|   +-- mood
|   +-- language detection
|   +-- system prompt shaping
```

## Config Surface

`config.py` loads `.env` from this folder and requires `DISCORD_TOKEN`.

Main config keys currently used:

| Key | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token, required |
| `SPECIAL_USER_ID` | superuser with elevated command access |
| `CEREBRAS_API_KEY` / `_2` | primary/failover LLM provider credentials |
| `CEREBRAS_BASE_URL` | Cerebras API base |
| `CEREBRAS_MODEL` | primary model name |
| `GROQ_API_KEY` / `_2` | fallback provider credentials |
| `GROQ_BASE_URL` | Groq API base |
| `GROQ_MODEL` | Groq model |
| `SEARCH_MODEL` | model used when search-heavy prompting is preferred |
| `VISION_MODEL` | image analysis model |
| `OLLAMA_API_KEY` ... `OLLAMA_API_KEY_5` | additional provider credentials |
| `OLLAMA_BASE_URL` | Ollama/cloud endpoint |
| `OLLAMA_MODEL` | extra fallback model |
| `QWEN_FALLBACK_MODEL` | additional fallback target |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare image API account |
| `CLOUDFLARE_API_TOKEN` | Cloudflare image API auth |
| `CLOUDFLARE_FLUX_MODEL` | text-to-image model |
| `CLOUDFLARE_FLUX2_DEV_IMG2IMG_MODEL` | image-to-image model |
| `CLOUDFLARE_SD15_IMG2IMG_MODEL` | additional image-to-image model |
| `MEMORY_FILE` | memory JSON path |
| `SETTINGS_FILE` | settings JSON path |
| `LOG_LEVEL` | logging level |

## Command Surface

### Chat commands

| Command | Type | What it does |
| --- | --- | --- |
| `/ask <question>` | hybrid | main ask-anything command |
| `!kim <text>` | prefix | direct conversational reply |

### Image commands

| Command | Type | What it does |
| --- | --- | --- |
| `/imagine <prompt> [image]` | slash | generate image, optional img2img input |
| `/image <prompt> [image]` | slash | same generation path as `/imagine` |
| `/vision <image> [question]` | slash | analyze an image |
| `/pollo <prompt>` | slash | generate free image |
| `/perchance <generator> [list_name]` | hybrid | fetch random Perchance output |

### Memory and behavior commands

| Command | Type | What it does |
| --- | --- | --- |
| `/reset_memory` | slash | opens confirmation buttons for self/global reset |
| `/language <auto|en|hinglish>` | hybrid | sets channel language mode |
| `/mood <mood>` | hybrid | changes Miss Kim mood for the channel |
| `/stats` | slash | bot uptime/message/memory stats |

### Admin / power-user commands

| Command | Type | Access |
| --- | --- | --- |
| `!purge [amount]` | prefix | `SPECIAL_USER_ID` or guild admin |
| `!say <text>` | prefix | `SPECIAL_USER_ID` or guild admin |

## Message-Driven Behavior

`events.py` is where a lot of bot1 behavior actually happens.

### Listener flow

`on_message` does this:

1. ignores bot messages
2. increments internal stats
3. applies rate limiting
4. checks send permission
5. handles apology / roast state updates
6. handles image-generation trigger phrases
7. handles reply-to-generated-image improvement flow
8. handles keyword-based image generation
9. handles mention, reply-to-bot, or DM chat
10. passes through to command processor

### Trigger patterns to remember

| Behavior | Where it comes from |
| --- | --- |
| mention replies | `events.py` |
| reply-to-bot chat continuation | `events.py` |
| DM chat | `events.py` |
| auto image triggers | `events.py` + `image.py` |
| image refinement on reply | `events.py` + `image.py` |
| memory summaries | `commands.py` / `events.py` + `memory.py` |

## Permissions Model

Power-user check is implemented in `commands.py:is_power_user(...)`.

User gets elevated access if:

- their ID matches `SPECIAL_USER_ID`
- or they are a guild administrator

## Discord Portal Requirements

Enable:

- Message Content Intent
- Members Intent

Useful bot permissions:

- Send Messages
- Read Message History
- Manage Messages
- Attach Files

## Validation

### Quick syntax check

```bash
cd Bot/bot1
python3 -m py_compile main.py commands.py events.py config.py image.py llm.py memory.py persona.py
```

### Tests

```bash
cd Bot/bot1
pytest -q
```

## Maintenance Hotspots

| Area | Files | Why you revisit it |
| --- | --- | --- |
| AI reply behavior | `commands.py`, `events.py`, `persona.py`, `llm.py` | response style, provider fallback, prompt logic |
| memory behavior | `memory.py`, `commands.py`, `events.py` | context retention, summarization, resets |
| image generation | `image.py`, `commands.py`, `events.py` | backend failures, prompt shaping, reply-based edits |
| access control | `commands.py` | admin-only actions |
| token/model config | `config.py`, `.env` | runtime failures and provider switches |

## Operational Notes

```text
bot1 is not just slash commands
it is heavily listener-driven
so behavior changes often require checking both commands.py and events.py
```

That is the main thing to remember when reviewing this bot.

