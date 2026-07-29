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
         │    Bot1: Miss Kim  │  │  Bot2: Lookism CG      │
         │  (JSON memory +    │  │  (Firestore-backed)       │
         │   LLM APIs)        │  │                           │
         └─────────┬─────────┘  └────┬───────────────────────┘
                   │                  │
         ┌─────────▼─────────┐  ┌────▼──────────────────────┐
         │  bot_memory.json  │  │  Firestore (remote)        │
         │  (conversations)  │  │  players, market, trades,  │
         └───────────────────┘  │  battles, gangs, etc.      │
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

## 3. 🔄 Bot2: Lookism CG Data Flow

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
    │       ├── data = self._cache (or hydrate from Firestore if None)
    │       ├── fn(data) modifies data in-place
    │       ├── self.save(data):
    │       │   ├── Persist to Firestore via Firebase Admin SDK
    │       │   └── Update self._cache
    │       └── Return result
    │
    ├── 4. (Optional) Firestore repo update via service (market/trade/battle)
    │
    └── 5. Send Discord embed + view response
```

### Startup Bootstrap Flow
```
setup_hook()
    │
    ├── 1. Firestore client initialized (firestore_client.py)
    │       Reads FIREBASE_PROJECT_ID + credentials
    │
    ├── 2. Storage hydrates from Firestore on first load()
    │
    ├── 3. recover_active_battles()
    │       ├── Read Firestore battle repo (active-by-user)
    │       ├── For each stale entry → end_battle with "abandoned"
    │
    └── 4. _unlock_stale_trades()
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
    │   └── Save to Firestore
    4. market_service.upsert_listing() → Firestore repo

/market remove → User cancels listing
    │
    1. storage.with_lock():
    │   ├── Remove listing from market["listings"]
    │   ├── Set card["market_locked"] = False
    │   └── Save to Firestore
    2. market_service.delete_listing() → Firestore repo

/market browse → View listings
    ├── Firestore repo: list_active_listings()
    └── Plus featured/special from storage.load()
```

### Battle Data Flow
```
/battle → Queue for matchmaking
    │
    1. Check: no active battle, not already queued
    2. Check: has squad with at least 1 fighter
    3. Add to Firestore battle queue:
    │   battle_repo.upsert_queue_entry(user_id, now, now+60)
    4. Start matchmaking timer (60s)
    5. Every 10s: check for match
    │   ├── Found: remove both from queue, create_battle_state()
    │   └── Timeout: CPU fallback
    6. Battle progresses → apply_move() modifies state + Firestore
    7. Battle ends → end_battle() updates:
    │   ├── State: clear active battle, update player data
    │   ├── Firestore: clear active-by-user
    │   └── Grant XP/CP/trophies/rewards
```

---

## 4. 🗄️ Storage Layer (Firestore)

| Aspect | Firestore Storage |
|--------|-------------------|
| **Locking** | `threading.Lock()` around the storage cache |
| **Read Speed** | ~instant (cached in memory after first load) |
| **Write Speed** | Depends on Firestore round-trip; `async_save` for non-blocking |
| **Concurrency** | Single in-process writer, Firestore server handles replication |
| **Atomicity** | Firestore document set / transaction |
| **Backup** | Firestore export |

> **History:** Pre-migration bot2 used a dual JSON + SQLite layer where JSON held the full game state and SQLite held high-churn market/trade/battle subsystems. Both were replaced by Firestore; the `Storage` public API stayed the same and the repo signatures were preserved so callers didn't have to change.

### What Lives in Firestore
```
players/
├── user/ (balance, inventory, trophies, rank, profile, quests...)
├── squad/
├── ranked_stats/
├── achievements/
├── season_pass/
├── packs/
└── redeemed_codes/
cards/ (card catalog)
gangs/ + alliances/
season/ + tournament/
config/ (rewards, UI emojis, market settings)
server_settings/
market/ (settings, store items, listings)
trades/ (pending, history, offer board)
battle/ (queue, pending_friendly, active_by_user)
```

---

## 5. 📦 Data Synchronization

Firestore is now the single source of truth — there is no secondary store to sync into. Mutations through `storage.with_lock` update the in-memory cache and persist to Firestore; the market/trade/battle repos write their subsystem-specific collections directly.

### Boot-time Seeding & Recovery
```
Every startup (setup_hook, before cogs serve commands):
1. market/trade/battle_service.bootstrap_from_json():
   Idempotent one-shot seed of the Firestore repos from the mirrored
   in-storage state; guarded by app_migrations markers so it never re-seeds.
2. trade_repo.recover_stale_processing_offers():
   Re-opens offers left in 'processing' by a crashed accept flow.
3. _unlock_stale_trades(): unlocks cards flagged trade_locked with no live offer.
4. BattleCog.recover_active_battles_after_restart(): ends stale active battles.

Feature cogs pull fresh repo state through hydrate helpers on demand:
   market_service.hydrate_json_market_listings(data)
   trade_service.hydrate_json_trade_state(data)
   battle_service.hydrate_json_state(data)
```

---

## 6. ⚡ Performance Characteristics

| Operation | Latency | Frequency |
|-----------|---------|-----------|
| storage.load() | ~0.5ms (cached) / ~depends on Firestore round-trip (cold) | Every command |
| storage.with_lock() | ~1 deepcopy of dataset + diff vs cache; 1 Firestore batch on the common path | Every mutation |
| Firestore repo write | Network-bound (~tens of ms typical) | Every battle/market/trade action |
| LLM call (bot1) | ~1-8s | Every AI reply |
| Image generation | ~3-15s | Every /imagine |
| Profile embed render | ~instant (text only) | Every /profile |

### Bottleneck Analysis
```
1️⃣ threading.Lock — serializes ALL mutations
   │ All commands queue up behind one lock
   │ Mitigation: Split hot subsystems into their own Firestore repos (partly done)

2️⃣ Firestore round-trip — every save() hits network
   │ Mitigation: async_save for non-critical writes; batch related updates

3️⃣ LLM calls — slowest operation by far
   │ Blocks command completion for 1-8s
   │ Mitigation: Implement response streaming
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
