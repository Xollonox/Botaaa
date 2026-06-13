# 🔐 Security Audit

> **⚠️ CRITICAL: This repository contains multiple hardcoded secrets that must be rotated immediately before any public exposure.**

---

## 1. 🔴 Critical Vulnerabilities

### 1.1 Discord Bot Token (Exposed)
**Location:** `Bot/bot2/bot/config.py:5`
```python
BOT_TOKEN = "REDACTED — rotated, now loaded from env var"
```
**Impact:** Full Discord bot account access:
- Send messages as the bot
- Access all guilds the bot is in
- Read all messages (with intents)
- Modify server settings where bot has permissions
- **Immediate action:** [Revoke this token in Discord Developer Portal](https://discord.com/developers/applications)

### 1.2 Supabase Service Role Key (Exposed)
**Location:** `Bot/bot2/bot/data/supabase_sync.py:8`
```python
SUPABASE_KEY = "REDACTED — rotated, now loaded from env var"
```
**Impact:** Full Supabase database access:
- Read/write/delete all bot data
- User data, game economy state
- **Immediate action:** [Rotate the anon/service role key in Supabase Dashboard](https://app.supabase.com)

### 1.3 Bot1 API Keys (Potentially Exposed)
**Location:** `Bot/bot1/config.py` reads from `.env`, but if `.env` is committed:
- Cerebras API keys (2)
- Groq API keys (2)
- Ollama API keys (5)
- Cloudflare API token
- Tenor API key

**Impact:** Unauthorized API usage, potential billing charges.

---

## 2. 🟠 Security Concerns

### 2.1 No Input Rate Limiting (Bot2)
- All 80+ slash commands have no global rate limiting
- A malicious user could spam API calls
- `with_lock()` operations on JSON file become serialization bottleneck
- **Mitigation:** Add per-user cooldowns or use Discord's built-in cooldown system

### 2.2 No Owner Command Authentication
- Owner commands check `is_owner(interaction)` which checks `OWNER_IDS`
- No secondary authentication (PIN, 2FA)
- If a bot owner's Discord account is compromised, attacker gets full control
- **Mitigation:** Add PIN confirmation for destructive owner commands

### 2.3 JSON File Race Conditions
- `bot1` uses `asyncio.Lock()` for memory saves
- `bot2` uses `threading.Lock()` for storage saves
- Under concurrent load, JSON corruption is possible
- **Mitigation:** Fully migrate to SQLite

### 2.4 No SQL Injection Protection (Minimal)
- SQLite queries use parameterized statements (`?` placeholders) — good
- But user input validation is minimal
- **Mitigation:** Add input sanitization for all user-provided strings

### 2.5 Unbounded Log File
- `Bot/bot2/logs/bot.log` grows without rotation
- Could contain sensitive data (user IDs, error messages with tokens)
- **Mitigation:** Implement log rotation

### 2.6 No HTTPS Certificate Validation Override (Minor)
- `supabase_sync.py` uses `urllib.request` with default SSL context
- `aiohttp` sessions across both bots use default SSL
- Generally safe, but no custom certificate pinning

---

## 3. 🟡 Best Practice Violations

### 3.1 Hardcoded Owner IDs
```python
OWNER_IDS = {1152936208742240316, 944972813041803285}
```
Should be in `.env` or config file.

### 3.2 Hardcoded API URLs
- All provider URLs hardcoded with defaults
- Should be env-configurable for staging/production separation

### 3.3 No Secrets Rotation Guide
- No documentation on how to rotate tokens
- No expiry dates tracked

### 3.4 API Keys in Source Control
- Even if `.env` is in `.gitignore`, the config files reference them
- `.env.example` files should have placeholder values

---

## 4. 🔧 Immediate Action Items

### Step 1: Revoke All Exposed Secrets
```bash
# 1. Discord Token
# Go to: https://discord.com/developers/applications
# Select your app → Bot → Regenerate Token

# 2. Supabase Key
# Go to: https://app.supabase.com
# Project Settings → API → Service Role Key → Regenerate

# 3. API Keys (Cerebras, Groq, Ollama, Cloudflare)
# Visit each provider's dashboard and rotate keys
```

### Step 2: Move Secrets to Environment Variables
```bash
# Create .env file
cat > .env << 'EOF'
# Discord
DISCORD_TOKEN=your_new_token_here

# LLM Providers
CEREBRAS_API_KEY=your_key
CEREBRAS_API_KEY_2=your_key
GROQ_API_KEY=your_key
GROQ_API_KEY_2=your_key
OLLAMA_API_KEY=your_key
# ... (up to 5 Ollama keys)

# Cloudflare
CLOUDFLARE_ACCOUNT_ID=your_id
CLOUDFLARE_API_TOKEN=your_token

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_key

# Bot2
LOOKISM_SQLITE_PATH=lookism_data.sqlite3
EOF

# Update config files to read from env only (no fallbacks)
```

### Step 3: Update `.gitignore`
```gitignore
# Secrets
.env
.env.*
!env.example

# Runtime data
bot_memory.json
bot_settings.json
lookism_data.json
lookism_data.sqlite3
Bot/bot2/lookism_data.json
Bot/bot2/lookism_data.sqlite3

# Logs
logs/
Bot/bot2/logs/

# Cache
__pycache__/
*.pyc
```

### Step 4: Remove Secrets from Git History
```bash
# WARNING: This rewrites history. Coordinate with all collaborators.
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch Bot/bot2/bot/config.py' \
  --prune-empty --tag-name-filter cat -- --all

# Then force push
git push origin --force --all
```

---

## 5. 🛡️ Recommended Security Improvements

### 5.1 Rate Limiting
```python
from discord.ext import commands

@commands.cooldown(1, 5, commands.BucketType.user)
async def some_command(self, interaction):
    pass
```

### 5.2 Secondary Authentication for Owner Commands
```python
class OwnerConfirmView(discord.ui.View):
    def __init__(self, owner_id, action):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.action = action

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        if interaction.user.id != self.owner_id:
            return
        await self.action(interaction)
```

### 5.3 Input Sanitization
```python
import re

def sanitize_input(text, max_length=100):
    # Strip HTML/script tags
    text = re.sub(r'<[^>]*>', '', text)
    # Remove control characters
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)
    # Truncate
    return text[:max_length]
```

### 5.4 SQLite WAL Mode (Already Implemented)
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
```
This is already done — good.

### 5.5 Audit Logging
```python
import logging
audit_logger = logging.getLogger("audit")

# Log all owner commands
def log_owner_action(interaction, action):
    audit_logger.warning(
        "[AUDIT] Owner action by %s (%s): %s",
        interaction.user.name, interaction.user.id, action
    )
```

---

## 6. 📋 Security Checklist

- [ ] Discord bot token rotated
- [ ] Supabase service key rotated
- [ ] All LLM API keys rotated
- [ ] `.env` file created with new secrets
- [ ] `.gitignore` updated to exclude secrets
- [ ] Git history cleaned of secrets (if repo was public)
- [ ] Rate limiting added to all commands
- [ ] Owner confirmation added for destructive actions
- [ ] Input sanitization added
- [ ] Log rotation configured
- [ ] Secrets in `.env.example` are placeholders only
- [ ] Backup plan: if repo is public, assume ALL secrets compromised

---

## 7. 🚨 Incident Response

If this repo has been exposed publicly:

1. **Immediately revoke all tokens** (Discord, Supabase, API providers)
2. **Check for unauthorized access:**
   - Discord: Check audit log for changes made by the bot
   - Supabase: Check access logs for unauthorized queries
3. **Create new tokens** and deploy with updated `.env`
4. **Notify users** if any personal data may have been exposed
5. **Investigate scope** of potential breach
6. **Implement all security improvements** before re-deploying
