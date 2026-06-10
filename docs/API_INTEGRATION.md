# 🔌 API Integration Reference

> **All external APIs that Botaaa connects to, with endpoints, auth methods, and error handling.**

---

## 1. 📡 Discord API

### Connection
- **Library:** discord.py
- **Auth:** Bot Token (header: `Authorization: Bot {token}`)
- **Gateway:** Secure WebSocket (WSS)
- **Intents:** Default + `message_content` + `members`

### Rate Limits
```
Global: 50 requests/second per bot token
Commands: 5 interactions / 5 seconds per user (configurable)
Webhooks: 30/second per webhook
```

### Error Handling
```python
# Handled by LookismCommandTree.on_error()
# - CommandOnCooldown → friendly message with retry time
# - HTTPException → logged, user sees "An error occurred"
# - NotFound → interaction expired (3s window)
```

---

## 2. 🤖 LLM Providers

### 2.1 Ollama (Cloud)
```
Base URL: https://ollama.com/api
Model: ministral-3:14b-cloud
Auth: Bearer token (5 rotating keys)
Endpoint: POST {base_url}/chat
Timeout: 60 seconds
Rate Limit: Per-key, unknown limit
Error Handling: 
  - 429 → rotate key, retry
  - Other → log, return error message

Key rotation: ROUND-ROBIN on EVERY call
  ⚠️ Known issue: even successful calls advance the key index
```

### 2.2 Cerebras
```
Base URL: https://api.cerebras.ai/v1
Model: llama3.1-8b
Auth: Bearer token (2 rotating keys)
Endpoint: POST {base_url}/chat/completions
Timeout: 35 seconds
Rate Limit: ~30 RPM per key (unofficial)
Error Handling:
  - 401/403/429 → rotate key, retry with next key
  - Other → log, return error

Key rotation: ON FAILURE ONLY (current → next on 401/403/429)
```

### 2.3 Groq
```
Base URL: https://api.groq.com/openai/v1
Model: llama-3.1-8b-instant
Auth: Bearer token (2 rotating keys)
Endpoint: POST {base_url}/chat/completions
Timeout: 35 seconds
Rate Limit: ~30 RPM (Groq, free tier)
Search Model: groq/compound (used for Lookism queries only)
Vision Model: meta-llama/llama-4-scout-17b-16e-instruct

Error Handling: Same as Cerebras (OpenAI-compat client)
```

### 2.4 Qwen Fallback
```
Base URL: Uses Ollama base URL
Model: gpt-oss:20b-cloud
Auth: Uses Ollama keys
Timeout: 60 seconds
Role: Fallback when primary Ollama model fails
```

### Fallback Chain Visualization
```
User Message
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│ 1. Ollama (5 keys round-robin)                             │
│    ├── Success → ✅ Reply                                  │
│    └── Fail → ❌ "could not reach..."                      │
│                                                            │
│ 2. Qwen Fallback (via Ollama, different model)             │
│    ├── Success → ✅ Reply                                  │
│    └── Fail →                                              │
│                                                            │
│ 3. Cerebras (2 keys, rotate on 401/403/429)                │
│    ├── Success → ✅ Reply                                  │
│    └── Fail →                                              │
│                                                            │
│ 4. Groq (only if prefer_search=True + Lookism query)       │
│    ├── Success → ✅ Reply                                  │
│    └── Fail →                                              │
│                                                            │
│ 5. Groq (universal fallback)                               │
│    ├── Success → ✅ Reply                                  │
│    └── Fail → ❌ Return Ollama's error message             │
└────────────────────────────────────────────────────────────┘
```

---

## 3. 🖼️ Image Generation APIs

### 3.1 Cloudflare Workers AI
```
Account: {CLOUDFLARE_ACCOUNT_ID}
Auth: Bearer {CLOUDFLARE_API_TOKEN}
Timeout: 80 seconds (POST), 120 seconds (multipart POST)

Endpoints:
  TXT2IMG: POST /accounts/{id}/ai/run/@cf/black-forest-labs/flux-1-schnell
    Body: {"prompt": str, "steps": 4, "seed": int}
    Response: {"result": {"image": base64}}
    
  IMG2IMG (Flux2): POST /accounts/{id}/ai/run/@cf/black-forest-labs/flux-2-dev
    Body: multipart/form-data (prompt + image + steps + dimensions)
    
  IMG2IMG (SD1.5): POST /accounts/{id}/ai/run/@cf/runwayml/stable-diffusion-v1-5-img2img
    Body: {"prompt": str, "image_b64": str, "num_steps": 20, ...}

Image Format: base64-encoded PNG
Error Handling:
  - Non-200 → log status + body[:500], return None
  - Missing "image" field → log, return None
  - Exception → log, return None
```

### 3.2 Pollinations (Free Tier)
```
Base: https://image.pollinations.ai
Timeout: 90 seconds
No auth required

Endpoint: GET /prompt/{encoded_prompt}
Params: width, height, seed, safe=false, model=flux, nologo=true, enhance=true
Response: Raw image bytes (PNG/JPEG)

Prompt Enhancement:
  - Prepends quality tags: "Accurately depict exactly this request..."
  - Adds: "Photorealistic, sharp focus, natural lighting, high detail"
  - Adds anti-distortion: "No unrelated people, objects, text, watermark, logo..."
```

---

## 4. 🎲 Perchance API

```
Endpoint: GET https://perchance.org/api/downloadGenerator
Params: generatorName, listsOnly=true, __cacheBust=random
Timeout: 15 seconds
No auth required

Response: Raw text format:
  output
  Item 1
  Item 2

Extraction: Regex `{list_name}\n([\s\S]*?)(?=\n\w+\n|$)`
Error: Returns descriptive error message string
```

---

## 5. 🗄️ Supabase (Bot2)

```
URL: https://vbvvllaprptilxufsaxv.supabase.co
Auth: Service Role Key (full access)
Endpoint: POST /rest/v1/bot_data
Timeout: 5 seconds
Strategy: Fire-and-forget background thread (dedup: skip if sync pending)

Request:
  POST with headers:
    Content-Type: application/json
    apikey: {SERVICE_ROLE_KEY}
    Authorization: Bearer {SERVICE_ROLE_KEY}
    Prefer: resolution=merge-duplicates
  Body: {"id": "main", "data": {full_state}}

Error Handling:
  - Silently logs warning "Supabase sync failed: {error}"
  - Does NOT retry on failure
  - Does NOT block the main thread
```

---

## 6. 🔗 Discord CDN

```
Used for:
  - Fetching user avatars (profile rendering)
  - Fetching custom emoji images (guild emoji panels)
  - Attachment downloads (vision analysis, img2img)

Endpoints:
  Avatar: GET https://cdn.discordapp.com/avatars/{user_id}/{hash}.png
  Emoji:  GET https://cdn.discordapp.com/emojis/{emoji_id}.png
  Attachment: Uses attachment URL from message

Headers: User-Agent: Mozilla/5.0
Timeout: 12 seconds
```

---

## 7. 📊 API Usage Statistics

| API | Calls/Day (est.) | Cost | Failure Rate |
|-----|------------------|------|--------------|
| Discord Gateway | Always connected | Free | <0.1% |
| Discord REST | 1,000-10,000 | Free | <0.1% |
| Ollama | 500-5,000 | Per-token | ~5% |
| Cerebras | 100-1,000 | Per-token | ~2% |
| Groq | 50-500 | Free tier | ~3% |
| Cloudflare AI | 50-500 | Per-image | ~10% |
| Pollinations | 20-200 | Free | ~5% |
| Supabase | 1,000-10,000 | Free tier | ~1% |

---

## 8. 🛡️ Security Considerations

| API | Risk | Mitigation |
|-----|------|------------|
| Discord | Token theft = full bot access | Rotate token, use env vars |
| LLM Providers | Key abuse, billing | Rate limit, monitor usage |
| Cloudflare | Key abuse, billing | Restrict to specific models |
| Supabase | Full DB access with service key | Rotate key, restrict IP |
| Pollinations | No auth (public) | Rate limit requests |

---

## 9. 🧪 Testing APIs (Offline)

All API calls are wrapped in try/except blocks. For testing without live APIs:
```python
# Mock the HTTP response
from unittest.mock import AsyncMock, patch

async def test_vision_fallback():
    with patch('bot1.image.fetch_url_bytes', return_value=None):
        result = await vision_chat_from_urls(...)
        assert "Vision is not available" in result
```
