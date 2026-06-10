# 🤖 Bot1: Miss Kim — Complete Architecture

> **Role:** Conversational AI chatbot with image generation and vision analysis
> **Persona:** Yeonu Kim — Generation 0 veteran operative from the Lookism universe
> **Files:** `Bot/bot1/` | **Entry:** `main.py`

---

## 1. 📁 File Map

```text
Bot/bot1/
├── main.py              # discord.py Bot bootstrap, extension loading
├── config.py             # .env loader, all token/model constants
├── commands.py           # Slash commands, prefix commands, hybrid commands
├── events.py            # on_message listener, auto-reply, image triggers
├── memory.py            # Per-user/channel memory management
├── persona.py           # Yeonu Kim persona, moods, language detection
├── image.py             # Image generation, vision, Perchance, prompt enhancement
├── llm.py               # Multi-provider LLM client with fallback
├── tests/
│   ├── __init__.py      # Empty
│   └── test_remember_line.py  # Memory filtering tests
└── requirements.txt     # discord.py, aiohttp, python-dotenv
```

---

## 2. 🚀 Startup Sequence

```
main.py
  │
  ├── 1. Load config.py → read .env → validate DISCORD_TOKEN
  │
  ├── 2. Create commands.Bot
  │       prefix = "!"
  │       intents = default + message_content + members
  │
  ├── 3. Load extension "commands" → CommandsCog
  │       /ask, !kim, /imagine, /image, /vision, /pollo,
  │       /perchance, /reset_memory, /language, /mood,
  │       /stats, !purge, !say
  │
  ├── 4. Load extension "events" → EventsCog
  │       on_ready, on_message, on_error,
  │       on_disconnect, on_command_error,
  │       on_app_command_error
  │
  └── 5. bot.start(DISCORD_TOKEN)
```

---

## 3. 🧠 AI Provider Chain (llm.py)

### Client Architecture
```
LLM Layer:
├── OllamaClient (5 rotating keys)
│   ├── base_url = OLLAMA_BASE_URL
│   ├── model = OLLAMA_MODEL ("ministral-3:14b-cloud")
│   └── _next_key() → round-robin rotation on every call
│
├── OpenAICompatClient — Cerebras
│   ├── 2 rotating keys
│   ├── model = "llama3.1-8b"
│   └── rotates on 401/403/429 only
│
└── OpenAICompatClient — Groq
    ├── 2 rotating keys
    ├── model = "llama-3.1-8b-instant"
    └── Search model = "groq/compound"
```

### chat_with_fallback() Flow
```
1. Try Ollama (primary)
   ├── Success? → Return reply
   └── Fail? → Typicially "I could not reach..."
       │
2. Try Qwen Fallback (Ollama, different model)
   ├── Success? → Return reply
   └── Fail? →
       │
3. Try Cerebras
   ├── Success? → Return reply
   └── Fail? →
       │
4. Try Groq Search (only if prefer_search=True AND Lookism query)
   ├── Success? → Return reply
   └── Fail? →
       │
5. Try Groq (universal fallback)
   ├── Success? → Return reply
   └── Fail? → Return Ollama's error message
```

### Key Implementation Details
```python
class OpenAICompatClient:
    def _ordered_keys(self):
        # Returns [current_key, next_key] — tries current first
        # Only rotates on 401/403/429 in the response
        return [self.keys[self._idx], self.keys[(self._idx + 1) % len(self.keys)]]

class OllamaClient:
    def _next_key(self):
        # Rotates on EVERY call, not just failures
        # This means key 0 could be alive but gets skipped
        key = self.keys[self._idx]
        self._idx = (self._idx + 1) % len(self.keys)
        return key
```

**⚠️ Known Issue:** Ollama rotates keys on every call, even successful ones. This wastes working keys.

---

## 4. 💾 Memory System (memory.py)

### Memory Architecture
```
BOT_MEMORY = {
    "users": {
        "user:{user_id}:guild:{guild_id}:chan:{channel_id}": {
            "lines": [        # Max 80 lines per scope
                "U: Hello",
                "B: Hi there!",
                ...
            ],
            "summary": "",    # LLM-generated, truncated to 300 chars
            "topic": "",      # Detected topic keyword
            "msg_count": 0    # Auto-increment counter
        }
    },
    "channels": {
        "{channel_id}": {
            "lang": "auto|en|hinglish",
            "mood": "calm|warm|serious|sarcastic|playful"
        }
    }
}
```

### Memory Operations
| Function | What It Does |
|----------|-------------|
| `remember_line(user_id, prefix, text)` | Appends `"U/B: {text}"`, trims to 300 chars, filters backend errors |
| `add_memory_to_prompt(user_id, text)` | Builds context block: `[summary] + [topic] + [recent_memories] + [current_text]` |
| `get_relevant_memories(memories, query)` | Word-overlap scoring, returns top-N relevant lines |
| `update_conversation_summary(user_id)` | Calls LLM to summarize conversation, replaces old summary |
| `clear_user_memory(user_id)` | Removes user scope from BOT_MEMORY |
| `clear_all_memory()` | Wipes all users and channels |
| `_should_summarize(user_id)` | Returns True every N messages (configurable) |

### Topic Detection
```python
common_topics = {
    "lookism": ["lookism", "yeonu", "jinyoung", "red paper", "webtoon"],
    "game": ["game", "play", "gaming", "rpg", "mmo", "valorant"],
    "music": ["song", "music", "playlist", "album", "artist"],
    "movie": ["movie", "film", "show", "netflix", "anime"],
    "food": ["food", "eat", "cook", "recipe", "hungry"],
    "tech": ["code", "coding", "programming", "python", "javascript"],
    "life": ["work", "study", "school", "college", "job"],
    "sports": ["sport", "game", "match", "team", "win", "fight"],
    "relationship": ["love", "crush", "date", "girlfriend", "boyfriend"],
}
# Uses substring matching — "game" matches "gameplay", "gamer", "gameboy"
```

---

## 5. 🎨 Image System (image.py)

### Image Generation Backends
```
Cloudflare Workers AI:
├── Flux 1 Schnell (txt2img) — primary text-to-image
│   POST /accounts/{id}/ai/run/@cf/black-forest-labs/flux-1-schnell
│
├── Flux 2 Dev (img2img) — image-to-image editing
│   POST multipart/form-data with prompt + image
│
└── Stable Diffusion 1.5 (img2img) — fallback img2img
    POST JSON with prompt + image_b64

Pollinations (free tier, no auth needed):
└── GET https://image.pollinations.ai/prompt/{encoded_prompt}
```

### Vision Analysis Pipeline
```
User sends image + optional question
    │
1. Gather image URLs (from message attachments + replied-to messages)
    │
2. Build system prompt: persona + mood + "You can analyze images"
    │
3. Try Ollama Vision (model: ministral-3:14b-cloud with base64 images)
    ├── Success? → Return
    └── Fail? →
4. Try Qwen Vision Fallback
    ├── Success? → Return
    └── Fail? →
5. Try Groq Vision (model: meta-llama/llama-4-scout-17b-16e-instruct)
    ├── Success? → Return
    └── Fail? → "Vision is not available right now."
```

### Image Enhancement Flow
```
User: "a samurai"  (or reply to bot's generated image)
    │
1. enhance_image_prompt():
   ├── If image_url provided → Vision analysis of reference
   │   → "Describe image, rewrite into one detailed prompt"
   └── If text only → LLM prompt expansion
       → "Expand to 120 words: art style, lighting, mood, colors"
    │
2. generate_image_bytes(prompt, source_bytes=None):
   ├── If source_bytes → Try Flux 2 img2img, fallback SD 1.5
   └── If no source → Flux 1 txt2img
```

### Trigger Detection
```python
IMAGE_TRIGGER_PREFIXES = [
    "create image", "generate image", "make image",
    "draw image", "imagine", "make a photo", "create a photo",
]

CHAT_IMAGE_TRIGGERS = {
    "@pollo": "pollinations",    # Free image gen via Pollinations
    "@imagine": "cloudflare",     # Quality image gen via Cloudflare
}
```

---

## 6. 👤 Persona System (persona.py)

### Mood Definitions
```python
VALID_MOODS = {"calm", "warm", "serious", "sarcastic", "playful"}

MOOD_TONES = {
    "calm": "Composed, direct, slightly cryptic. Speak with quiet authority.",
    "warm": "Genuinely caring, mentor-like, softer than usual but still composed.",
    "serious": "Terse, no-nonsense, focused. Minimal small talk.",
    "sarcastic": "Dry wit and side-eye energy. Still poised — never unhinged.",
    "playful": "Light banter and teasing. Confident and fun, still in control.",
}
```

### Roast/Friend Detection
```python
_ROAST_PATTERN = r"\b(idiot|stupid|dumb|ugly|trash|garbage|loser|...)\b"
_SORRY_PATTERN = r"\b(sorry|sry|my bad|forgive|apologize|apologies|mb)\b"
```
- If user roasts → "roasting" mode → sharp composed put-down
- If user apologizes → "friend" mode → warm and approachable

### Language Detection
```python
def detect_language(text, channel_id):
    1. Check channel setting (auto/en/hinglish)
    2. If auto:
       - Unicode range स द → hinglish
       - Keywords: kya, kyu, kaise, bhai, yaar → hinglish
       - Default → en
```

### Lookism Knowledge Base
```python
LOOKISM_KEYWORDS = {
    "lookism", "yeonu", "yeonu kim", "kim yeon woo",
    "red paper", "jinyoung", "0th generation"
}

LOOKISM_YEONU_PROFILE = """... 30-line static text ..."""
```

---

## 7. 🎯 Event Flow (events.py)

### on_message Pipeline
```
1. message.author.bot? → IGNORE
2. Increment _messages_processed, add to _active_users_today
3. Rate limit check (max 5 messages/10s per user)
4. Check send permissions
5. Apology/roast detection → update user relation state
6. Chat image trigger check (@pollo, @imagine)
7. Reply-to-generated-image check (user wants to improve)
8. Keyword image trigger check ("create image of...")
9. Bot mention / reply to bot / DM → full chat response
10. Fall through to process_commands
```

### Generated Image Message Tracking
```python
generated_image_messages = {
    discord_message_id: {
        "prompt": "enhanced prompt string",
        "raw_prompt": "original user prompt",
        "backend": "cloudflare | pollinations"
    }
}
# No TTL — memory leak risk over time (stored until bot restart)
```

---

## 8. 🔧 Configuration Surface (config.py)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DISCORD_TOKEN` | **Required** | Bot token |
| `SPECIAL_USER_ID` | `1152936208742240316` | Superuser ID |
| `CEREBRAS_API_KEY` | `""` | Primary LLM key |
| `CEREBRAS_API_KEY_2` | `""` | Failover key |
| `CEREBRAS_BASE_URL` | `https://api.cerebras.ai/v1` | API endpoint |
| `CEREBRAS_MODEL` | `llama3.1-8b` | Model name |
| `GROQ_API_KEY` / `_2` | `""` | Groq keys |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | API endpoint |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Model name |
| `SEARCH_MODEL` | `groq/compound` | Search-optimized model |
| `VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Vision model |
| `OLLAMA_API_KEY` (1-5) | `""` | 5 rotating Ollama keys |
| `OLLAMA_BASE_URL` | `https://ollama.com/api` | API endpoint |
| `OLLAMA_MODEL` | `ministral-3:14b-cloud` | Model name |
| `QWEN_FALLBACK_MODEL` | `gpt-oss:20b-cloud` | Fallback model |
| `CLOUDFLARE_ACCOUNT_ID` | `""` | CF Workers AI account |
| `CLOUDFLARE_API_TOKEN` | `""` | CF Workers AI auth |
| `CLOUDFLARE_FLUX_MODEL` | `@cf/black-forest-labs/flux-1-schnell` | txt2img |
| `MEMORY_FILE` | `bot_memory.json` | Memory storage path |
| `SETTINGS_FILE` | `bot_settings.json` | Settings storage path |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## 9. 🧪 Tests

### Test File: `test_remember_line.py`
Tests 7 scenarios:
1. Backend error message returns early (not stored)
2. Backend error exact match (whitespace-tolerant)
3. User messages appended normally
4. Non-error bot messages appended normally
5. Long lines trimmed to 300 chars
6. msg_count incremented correctly
7. Guild + channel scope key generation correct

---

## 10. ⚠️ Known Issues (Technical Debt)

| Issue | Impact | Location |
|-------|--------|----------|
| No TTL on `generated_image_messages` | Memory leak | `events.py:39` |
| Ollama rotates keys on every call | Wastes working keys | `llm.py:106` |
| Exact-match trigger detection | "hello there" won't match "hello" | `events.py` |
| String-based topic detection | Over-matches ("game" in "gameplay") | `memory.py` |
| Vision responses not stored in memory | Lost context | `events.py:chat handler` |
| No mood persistence across restarts | Defaults to "calm" daily | `memory.py` |
| 300-char summary truncation | Destroys nuance | `memory.py` |
| Synchronous `_save_json_file()` in async context | Blocks event loop | `memory.py:35, 53` |
