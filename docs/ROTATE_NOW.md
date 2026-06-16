# 🔒 CRITICAL: Exposed Credentials - Rotate Immediately

**THIS REPOSITORY CONTAINS HARDCODED SECRETS COMMITTED TO GIT HISTORY.**

All credentials listed below have been exposed in the repository and must be rotated immediately, even if you've since removed them from the codebase. Attackers can access them from git history.

---

## Credentials Found & Status

### Bot/bot1/.env (LIVE SECRETS - KEEP FILE, ROTATE ALL KEYS)
⚠️ **File Status:** Still committed to git, now in .gitignore
⚠️ **Action:** Keep the file to run bot1, but rotate all keys immediately

| Credential | Service | Exposure | Status |
|------------|---------|----------|--------|
| `DISCORD_TOKEN` | Discord (bot1) | Committed to git | ❌ MUST ROTATE |
| `CEREBRAS_API_KEY` | Cerebras AI | Committed to git | ❌ MUST ROTATE |
| `CEREBRAS_API_KEY_2` | Cerebras AI | Committed to git | ❌ MUST ROTATE |
| `GROQ_API_KEY` | Groq API | Committed to git | ❌ MUST ROTATE |
| `GROQ_API_KEY_2` | Groq API | Committed to git | ❌ MUST ROTATE |
| `OLLAMA_API_KEY` through `OLLAMA_API_KEY_5` | Ollama Cloud | Committed to git (5 keys) | ❌ MUST ROTATE |
| `CLOUDFLARE_API_TOKEN` | Cloudflare | Committed to git | ❌ MUST ROTATE |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare | Committed to git | ⚠️ SHOULD ROTATE |

### Bot/bot2/bot/config.py (NOW FIXED)
✅ **Status:** Hardcoded token removed, now loads from environment
✅ **Action:** Already fixed — loads `BOT_TOKEN` from env vars

### Bot/bot2/bot/data/supabase_sync.py (NOW FIXED)
✅ **Status:** No longer has hardcoded defaults, uses env vars only
✅ **Action:** Already fixed — gracefully handles missing `SUPABASE_SERVICE_ROLE_KEY`

---

## Step-by-Step Rotation Instructions

### 1. Discord (Bot/bot1 - Primary)
**Impact:** Bot1 token is compromised
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your bot application
3. Go to **Bot** section → click **Regenerate** under TOKEN
4. Copy the new token
5. Update `Bot/bot1/.env`:
   ```
   DISCORD_TOKEN=<new_token_here>
   ```

### 2. Cerebras AI (Bot/bot1)
**Impact:** Both CEREBRAS_API_KEY and CEREBRAS_API_KEY_2 compromised
1. Go to [Cerebras Console](https://console.cerebras.ai)
2. Navigate to **API Keys** section
3. Delete old keys (both KEY and KEY_2)
4. Create 2 new keys
5. Update `Bot/bot1/.env`:
   ```
   CEREBRAS_API_KEY=<new_key_here>
   CEREBRAS_API_KEY_2=<new_key_2_here>
   ```

### 3. Groq API (Bot/bot1)
**Impact:** Both GROQ_API_KEY and GROQ_API_KEY_2 compromised
1. Go to [Groq Console](https://console.groq.com)
2. Navigate to **API Keys**
3. Delete old keys (both KEY and KEY_2)
4. Create 2 new keys
5. Update `Bot/bot1/.env`:
   ```
   GROQ_API_KEY=<new_key_here>
   GROQ_API_KEY_2=<new_key_2_here>
   ```

### 4. Ollama Cloud (Bot/bot1)
**Impact:** All 5 API keys (OLLAMA_API_KEY through OLLAMA_API_KEY_5) compromised
1. Go to [Ollama Cloud Dashboard](https://ollama.com/dashboard)
2. Navigate to **API Keys** section
3. Delete all 5 old keys
4. Create 5 new keys
5. Update `Bot/bot1/.env`:
   ```
   OLLAMA_API_KEY=<new_key_here>
   OLLAMA_API_KEY_2=<new_key_2_here>
   OLLAMA_API_KEY_3=<new_key_3_here>
   OLLAMA_API_KEY_4=<new_key_4_here>
   OLLAMA_API_KEY_5=<new_key_5_here>
   ```

### 5. Cloudflare (Bot/bot1)
**Impact:** API token AND account ID exposed (account ID is less sensitive but should still be rotated)
1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Navigate to **Profile → API Tokens** (or **Account → API Tokens**)
3. Delete the old token
4. Create a new token with appropriate permissions for image generation
5. Update `Bot/bot1/.env`:
   ```
   CLOUDFLARE_API_TOKEN=<new_token_here>
   ```

⚠️ **Note on CLOUDFLARE_ACCOUNT_ID:** This is less critical than the API token, but consider it exposed. No formal "rotation" needed—it's tied to your account. Focus on rotating the API token.

### 6. Supabase (Bot/bot2 - If Used)
**Status:** Currently optional and not exposed in code, but store securely if enabled
1. If you plan to enable Supabase sync in bot2:
   - Go to [Supabase Dashboard](https://supabase.com/dashboard)
   - Create or retrieve a service role key
   - Store it ONLY in `.env` (never commit to git)
   - Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `Bot/bot2/.env`

---

## Verification Checklist

After rotating all credentials:

- [ ] All Discord bot tokens have been regenerated
- [ ] All Cerebras API keys have been deleted and recreated
- [ ] All Groq API keys have been deleted and recreated
- [ ] All 5 Ollama API keys have been deleted and recreated
- [ ] Cloudflare API token has been rotated
- [ ] All new credentials are stored in respective `.env` files (never committed)
- [ ] Bot1 and Bot2 are tested and working with new credentials
- [ ] Old credentials are confirmed deleted from each service
- [ ] Git history cannot expose active credentials (they're all rotated)

---

## Environment File Examples

### Bot/bot1/.env (Update with new credentials)
```env
DISCORD_TOKEN=<new_token>
CEREBRAS_API_KEY=<new_key>
CEREBRAS_API_KEY_2=<new_key>
GROQ_API_KEY=<new_key>
GROQ_API_KEY_2=<new_key>
OLLAMA_API_KEY=<new_key>
OLLAMA_API_KEY_2=<new_key>
OLLAMA_API_KEY_3=<new_key>
OLLAMA_API_KEY_4=<new_key>
OLLAMA_API_KEY_5=<new_key>
CLOUDFLARE_API_TOKEN=<new_token>
CLOUDFLARE_ACCOUNT_ID=<existing_id>
# ... other config values unchanged
```

### Bot/bot2/.env (Create if not exists)
```env
BOT_TOKEN=<your_discord_bot_token>
LOOKISM_SQLITE_PATH=  # optional
SUPABASE_URL=         # optional
SUPABASE_SERVICE_ROLE_KEY=  # optional
GANG_WAR_PREP_SECONDS=86400
GANG_WAR_BATTLE_SECONDS=86400
```

---

## Prevention Going Forward

✅ All `.env` files are now in `.gitignore`
✅ Bot2 loads credentials from environment variables with proper error handling
✅ Supabase sync gracefully handles missing keys

**Always:**
- Never commit `.env` files to git
- Use `.env.example` with placeholder values as documentation
- Load secrets from environment variables at runtime
- Rotate keys immediately if they're ever exposed
