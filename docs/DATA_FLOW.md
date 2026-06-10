# 💾 Data Flow & Storage Architecture

> **How data moves through the system, from Discord interaction to persistent storage.**

---

## 1. 📊 Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Discord API                              │
└──────────────────┬──────────────────┬──────────────────────┘
                   │                  │
         ┌─────────▼─────────┐  ┌────▼──────────────────────┐
         │    Bot1: Miss Kim  │  │  Bot2: Lookism HXCC      │
         │  (JSON memory +    │  │  (JSON + SQLite dual)     │
         │   LLM APIs)        │  │                           │
         └─────────┬─────────┘  └────┬───────────────────────┘
                   │                  │
         ┌─────────▼─────────┐  ┌────▼──────────────────────┐
         │  bot_memory.json  │  │  lookism_data.json        │
         │  (conversations)  │  │  (game state)             │
         └───────────────────┘  │  lookism_data.sqlite3     │
                                │  (market/trade/battle)    │
                                └────────┬──────────────────┘
                                         │
                                ┌────────▼──────────────────┐
                                │  Supabase (website read)   │
                                └───────────────────────────┘
```

---

## 2. 🔄 Bot1: Miss Kim Data Flow

### Read Path (Message Processing)
```
Discord on_message event
    │
    ├── 1. Rate limit check (in-memory: _user_message_times)
    │
    ├── 2. Read BOT_MEMORY from JSON file (on first access)
    │       _load_json_file(MEMORY_FILE, default)
    │       → Returns dict, cached in global BOT_MEMORY
    │
    ├── 3. Build prompt context:
    │       add_memory_to_prompt()
    │       → Reads from BOT_MEMORY["users"][scope_key]
    │       → Returns formatted [summary] + [topic] + [memories] + [current]
    │
    ├── 4. Call LLM:
    │       chat_with_fallback(system_prompt, user_prompt)
    │       → Tries Ollama → Qwen → Cerebras → Groq
    │       → Returns reply string
    │
    ├── 5. Store reply in memory:
    │       remember_line(user_id, "B", reply)
    │       → Appends to BOT_MEMORY["users"][scope_key]["lines"]
    │       → _save_json_file_async() with asyncio.Lock()
    │
    └── 6. Send reply to Discord
```

### Write Path
```
remember_line(user_id, prefix, text)
    │
    ├── 1. Compute scope key:
    │       _memory_scope_key(user_id, guild_id, channel_id)
    │       → "user:{id}:guild:{gid}:chan:{cid}" or "user:{id}:dm"
    │
    ├── 2. Get/create scope state:
    │       _scope_state(user_id, guild_id, channel_id)
    │
    ├── 3. Append line (trimmed to 300 chars):
    │       lines.append(f"{prefix}: {cleaned[:300]}")
    │
    ├── 4. Trim to max items (default 80):
    │       lines[-max_user_memory_items:]
    │
    ├── 5. Increment msg_count
    │
    ├── 6. Detect topic from last 10 lines
    │
    └── 7. Save to file (async):
        _save_json_file_async(MEMORY_FILE, BOT_MEMORY)
        → Acquire _memory_lock → write JSON → release
```

### Summarization Flow
```
_should_summarize(user_id) → True every N messages (default 10)
    │
update_conversation_summary(user_id)
    │
    ├── 1. Get all lines from memory
    │
    ├── 2. Take lines except last 4 (these stay in context)
    │
    ├── 3. Call LLM:
    │       "Summarize this conversation in 1 short sentence."
    │
    ├── 4. Store summary (trimmed to 300 chars):
    │       state["summary"] = summary[:300]
    │
    └── 5. Keep only last 4 lines (rest summarized away)
        state["lines"] = lines[-4:]
```

---

## 3. 🔄 Bot2: Lookism HXCC Data Flow

### Request Lifecycle
```
User sends slash command
    │
    ├── 1. LookismCommandTree.interaction_check()
    │       ├── Check _terms_cache (in-memory set)
    │       ├── Cache miss? → storage.load() → check data
    │       ├── Not accepted? → Send Terms embed → BLOCK
    │       └── Accepted? → ALLOW
    │
    ├── 2. Cog handler method executes
    │
    ├── 3. storage.with_lock(mutate_function)
    │       ├── Acquire threading.Lock
    │       ├── data = self._cache (or _load_from_disk if None)
    │       ├── fn(data) modifies data in-place
    │       ├── self.save(data):
    │       │   ├── _sanitize_for_json(data)
    │       │   ├── Write to .tmp file
    │       │   ├── fsync(f.fileno())
    │       │   ├── os.replace(.tmp, .json)
    │       │   └── Update self._cache
    │       └── Return result
    │
    ├── 4. (Optional) Async SQLite update via service
    │
    └── 5. Send Discord embed + view response
```

### Startup Bootstrap Flow
```
setup_hook()
    │
    ├── 1. market_service.bootstrap_from_json()
    │       ├── Check migration table: json_bootstrap_completed?
    │       │   YES → skip
    │       ├── Check has_persisted_state() in SQLite?
    │       │   YES → mark completed, skip
    │       ├── Read from storage.load() → market data
    │       ├── Seed SQLite tables from JSON data
    │       └── Mark migration complete
    │
    ├── 2. trade_service.bootstrap_from_json()
    │       (same pattern)
    │
    ├── 3. battle_service.bootstrap_from_json()
    │       (same pattern)
    │
    ├── 4. recover_active_battles()
    │       ├── Read SQLite battle_active_by_user
    │       ├── For each stale entry → end_battle with "abandoned"
    │
    └── 5. _unlock_stale_trades()
        ├── Scan all players' inventory
        ├── Any trade_locked items? → unlock them
        ├── Clear trade pending state
```

### Market Data Flow
```
/market add → User lists card
    │
    1. Check: card not locked/squad_locked/market_locked/trade_locked
    2. Check: price within rarity band
    3. storage.with_lock():
    │   ├── Set card["market_locked"] = True
    │   ├── Add listing to market["listings"]
    │   └── Save JSON
    4. market_service.upsert_listing() → SQLite

/market remove → User cancels listing
    │
    1. storage.with_lock():
    │   ├── Remove listing from market["listings"]
    │   ├── Set card["market_locked"] = False
    │   └── Save JSON
    2. market_service.delete_listing() → SQLite

/market browse → View listings
    ├── SQLite: list_active_listings()
    └── Plus featured/special from JSON storage.load()
```

### Battle Data Flow
```
/battle → Queue for matchmaking
    │
    1. Check: no active battle, not already queued
    2. Check: has squad with at least 1 fighter
    3. Add to SQLite battle_queue:
    │   battle_repo.upsert_queue_entry(user_id, now, now+60)
    4. Start matchmaking timer (60s)
    5. Every 10s: check for match
    │   ├── Found: remove both from queue, create_battle_state()
    │   └── Timeout: CPU fallback
    6. Battle progresses → apply_move() modifies JSON + SQLite
    7. Battle ends → end_battle() updates:
    │   ├── JSON: clear active battle, update player data
    │   ├── SQLite: clear battle_active_by_user
    │   ├── Grant XP/CP/trophies/rewards
    │   └── Supabase: fire-and-forget sync
```

---

## 4. 🗄️ Storage Comparison

| Aspect | JSON (storage.py) | SQLite (sqlite_store.py) |
|--------|--------------------|-------------------------|
| **Locking** | `threading.Lock()` | SQLite WAL handles it |
| **Read Speed** | ~instant (cached) | ~instant (WAL) |
| **Write Speed** | ~50ms (fsync+replace) | ~5ms |
| **Concurrency** | Single writer | Multiple readers + single writer |
| **Atomicity** | File replace (OS-level) | SQL transaction |
| **Corruption** | Backed up as .corrupt | WAL recovery |
| **Data Type** | Full game state | High-churn subsystems |
| **Backup** | Copy file | `.dump` via sqlite3 |

### What Lives Where
```
JSON (lookism_data.json):
├── players/
│   ├── user/ (balance, inventory, trophies, rank, profile, quests...)
│   ├── squad/
│   ├── ranked_stats/
│   ├── achievements/
│   ├── season_pass/
│   ├── packs/
│   └── redeemed_codes/
├── cards/ (card catalog — 26 definitions)
├── gangs/ + alliances/
├── season/ + tournament/
├── config/ (rewards, UI emojis, market settings)
└── server_settings/

SQLite (lookism_data.sqlite3):
├── market_settings (1 row)
├── market_store_items (card_name → price, stock, enabled)
├── market_listings (listing_id → JSON payload)
├── trade_pending (user_id → status)
├── trade_history (A, B, resolved_at, JSON)
├── trade_offer_board (offers with status)
├── battle_queue (user_id, time window)
├── battle_pending_friendly (target_id, payload)
├── battle_active_by_user (user_id → battle_id)
└── app_migrations (bootstrap tracking)
```

---

## 5. 📦 Data Synchronization

### JSON → SQLite Bootstrap (One-time)
```
On first startup:
1. Read JSON state
2. Seed SQLite tables
3. Mark migration complete in app_migrations
4. All future updates go to BOTH:
   - storage.with_lock() → JSON
   - service.async_call() → SQLite
```

### Runtime Sync
```
STORAGE            SQLITE
   │                   │
   │  ┌───────────┐    │
   │  │  Mutate    │    │
   │  │  JSON      │    │
   │  └─────┬─────┘    │
   │        │ async    │
   │  ┌─────▼─────┐    │
   │  │  Mutate    │    │
   │  │  SQLite    │    │
   │  └───────────┘    │
```

### Boot-time Hydration
```
Every startup:
1. battle_service.hydrate_json_state(data):
   data["battle"]["queue"] = SQLite.list_queue()
   data["battle"]["pending_friendly"] = SQLite.list_pending_friendly()
   data["battle"]["active_by_user"] = SQLite.list_active_by_user()

2. market_service.hydrate_json_market_listings(data):
   data["market"]["listings"] = SQLite.list_active_listings()

3. trade_service.hydrate_json_trade_state(data):
   data["trades"]["pending"] = SQLite.list_pending()
```

---

## 6. ⚡ Performance Characteristics

| Operation | Latency | Frequency |
|-----------|---------|-----------|
| storage.load() | ~0.5ms (cached) / ~50ms (cold) | Every command |
| storage.with_lock() | ~5-100ms (depends on data size) | Every mutation |
| SQLite insert | ~2-10ms | Every battle/market/trade action |
| JSON atomic write | ~10-50ms | Every mutation |
| LLM call (bot1) | ~1-8s | Every AI reply |
| Image generation | ~3-15s | Every /imagine |
| Profile render (PIL) | ~2-5s | Every /profile |
| Supabase sync | ~500ms (fire-and-forget) | Every JSON save |

### Bottleneck Analysis
```
1️⃣ threading.Lock — serializes ALL mutations
   │ All commands queue up behind one lock
   │ Mitigation: Move more data to SQLite

2️⃣ JSON file rewrite — rewrites ENTIRE file on every save
   │ lookism_data.json is ~15KB+ with players
   │ Mitigation: Split into per-player files

3️⃣ LLM calls — slowest operation by far
   │ Blocks command completion for 1-8s
   │ Mitigation: Implement response streaming

4️⃣ Profile render — CPU-intensive PIL operations
   │ 3200x1800 canvas rendering
   │ Mitigation: Cache rendered images with TTL
```

---

## 7. 🔄 Bot1 vs Bot2 State Flow Comparison

```python
# BOT1: Simple Read-Process-Write
BOT_MEMORY = _load_json_file(MEMORY_FILE, {"users":{}, "channels":{}})

async def command_handler():
    state = _scope_state(user_id, guild_id, channel_id)  # Read from global
    # Process...
    remember_line(user_id, "B", reply)                    # Write to global
    await _save_json_file_async(MEMORY_FILE, BOT_MEMORY) # Save to disk

# BOT2: Lock-Read-Mutate-Save
def command_handler():
    def mutate(data):
        player = data["players"][user_id]
        # Process...
        player["user"]["balance"] += amount
        return result

    return storage.with_lock(mutate)  # Lock, read, mutate, save, unlock
```
