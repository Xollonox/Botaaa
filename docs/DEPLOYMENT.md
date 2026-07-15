# 🚀 Deployment Guide

> **How to deploy Botaaa in various environments: local, VPS, and panel.**

---

## 1. 📋 Prerequisites

### Minimum Requirements
| Component | Requirement |
|-----------|-------------|
| Python | 3.10+ |
| RAM | 512MB (bot1+bot2), 256MB (single bot) |
| Storage | 500MB+ |
| Network | Outbound HTTPS (Discord API + AI providers) |
| Discord Bot Token | [Create in Developer Portal](https://discord.com/developers/applications) |
| Discord Intents | Message Content + Members + Server Members |

### Recommended
- **Pillow fonts:** `apt install fonts-dejavu` (for profile card rendering)
- **SQLite3:** Built into Python (for bot2 state)

---

## 2. 🏠 Local / Termux Deployment

### One-Command Setup
```bash
cd /data/data/com.termux/files/home/Botaaa
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python launcher.py
```

### With Environment Variables
```bash
set -a
source .env
set +a
python launcher.py
```

### Run Single Bot
```bash
# Miss Kim only
cd Bot/bot1
python main.py

# Lookism HXCC only
cd Bot/bot2
python main.py
```

### Termux-Specific Notes
- Run `pkg install python` if Python isn't installed
- Install `pkg install fontconfig` for PIL font support
- Keep the terminal alive: use `tmux` or `nohup`

---

## 3. 🌐 VPS Deployment

### DigitalOcean / Linode / Hetzner

```bash
# 1. System update
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git tmux

# 2. Clone repo
git clone https://github.com/your-org/Botaaa.git
cd Botaaa

# 3. Virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install deps
pip install -r requirements.txt

# 5. Create .env file (no secrets in repo!)
cp .env.example .env
nano .env  # Add your tokens

# 6. Run in tmux
tmux new -s botaaa
python launcher.py
# Ctrl+B, D to detach
# tmux attach -t botaaa to reattach
```

### Using systemd (Recommended for Production)
```ini
# /etc/systemd/system/botaaa.service
[Unit]
Description=Botaaa Discord Bot Suite
After=network.target

[Service]
Type=simple
User=botaaa
WorkingDirectory=/home/botaaa/Botaaa
EnvironmentFile=/home/botaaa/Botaaa/.env
ExecStart=/home/botaaa/Botaaa/.venv/bin/python /home/botaaa/Botaaa/launcher.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable botaaa
sudo systemctl start botaaa
sudo systemctl status botaaa

# View logs
sudo journalctl -u botaaa -f
```

---

## 4. 🎛️ Panel / Dashboard Deployment

### Pterodactyl / Pelican / Hosting Panels

**Startup Command:**
```bash
cd /home/container
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python launcher.py
```

**Important Panel Notes:**
1. **Persist data:** Mount `lookism_data.json` and `.sqlite3` to persistent storage
2. **Avoid dirty repo:** Set `git fetch origin main && git reset --hard origin/main` as deploy command
3. **Watch for:** `Bot/bot2/logs/bot.log` being tracked in git (make it ignored)
4. **Environment:** Set all tokens as panel environment variables
5. **NeetVerse voice:** Ensure `ffmpeg` is installed and install the root requirements so PyNaCl and Edge TTS are available

**Safe Deploy Flow:**
```bash
git fetch origin main
git reset --hard origin/main
pip install -U -r requirements.txt --user
python launcher.py
```

---

## 5. 🔄 Update & Restart Procedures

### Zero-Downtime Updates (Theoretical)
```bash
# Bot2 stores state in JSON + SQLite, not in-memory
# Restarting is safe as long as:
1. No active battles (or they'll be auto-resolved as "abandoned")
2. No pending trades (or cards remain locked until restart cleanup)

# Best practice: announce maintenance, wait 5 min, then restart
```

### Full Restart
```bash
# If using launcher.py:
pkill -f "python.*launcher"  # SIGINT → graceful shutdown
python launcher.py

# If using systemd:
sudo systemctl restart botaaa

# If using tmux:
tmux kill-session -t botaaa
tmux new -s botaaa
python launcher.py
```

### Git-Based Update
```bash
# Safe pull + restart
git fetch origin main
git reset --hard origin/main
pip install -U -r requirements.txt
sudo systemctl restart botaaa
```

---

## 6. ☁️ Bot-Specific Deployment Options

### Running Bot1 Only (Miss Kim)
```bash
cd Bot/bot1
python main.py
# Requires: DISCORD_TOKEN in .env or env
# Works without: Cerebras, Groq, Ollama keys (will use fallback chain)
```

### Running Bot2 Only (Lookism HXCC)
```bash
cd Bot/bot2
python main.py
# Requires: DISCORD_TOKEN in bot/config.py or env
# Supports: SQLITE_PATH env override
```

---

## 7. 📊 Monitoring

### Health Checks
```python
# Every 60 seconds, check:
# 1. Bot is connected to Discord Gateway
# 2. Storage file is readable
# 3. SQLite database is accessible
# 4. Background tasks are running
```

### Log Files
```
Bot/bot2/logs/bot.log  →  Runtime logs (check for errors)
journalctl -u botaaa   →  System-level logs
```

### Key Metrics to Monitor
| Metric | Warning | Critical |
|--------|---------|----------|
| Memory usage | >300MB | >500MB |
| CPU usage | >80% sustained | >95% |
| Response time (battle) | >3s | >8s |
| LLM failure rate | >10% | >30% |
| SQLite file size | >50MB | >100MB |
| JSON file size | >10MB | >20MB |
| Log file size | >100MB | >500MB |

---

## 8. 🐛 Troubleshooting

### Bot Won't Start
| Symptom | Cause | Fix |
|---------|-------|-----|
| `DISCORD_TOKEN not set` | No token in .env or config | Create .env with DISCORD_TOKEN |
| `PyNaCl not installed` | Voice module missing (safe to ignore) | Not needed |
| `ModuleNotFoundError` | Missing dependency | `pip install -r requirements.txt` |
| `Port already in use` | Another instance running | Kill existing: `pkill -f "python.*bot"` |

### Runtime Errors
| Symptom | Cause | Fix |
|---------|-------|-----|
| `could not reach AI backend` | All LLM providers down | Check provider status pages |
| `Battle error` | Bad state from crash | `/o_battle_unstuck` or restart |
| `JSON decode error` | Corrupted file | Restore from backup or delete (auto-rebuilds) |
| `SQLite locked` | Concurrent write conflict | Wait or restart |
| `Card not found` | Missing in catalog | `/o add_card` or add to `cards.json` |

### Performance Issues
| Issue | Likely Cause | Solution |
|-------|-------------|----------|
| Slow battle responses | JSON lock contention | Move more state to SQLite |
| Image generation timeout | Cloudflare API slow | Switch to Pollinations (faster, lower quality) |
| Profile card rendering fails | Missing fonts | `apt install fonts-dejavu` |
| Memory leak | `generated_image_messages` dict | Restart bot periodically |

---

## 9. 🔒 Production Security Checklist

- [ ] All secrets in `.env` (not in source files)
- [ ] `.gitignore` covers all sensitive files
- [ ] Git history cleaned of secrets (if ever exposed)
- [ ] Rate limiting configured on all commands
- [ ] Log rotation configured
- [ ] Backup strategy for JSON + SQLite files
- [ ] Monitoring + alerting set up
- [ ] Graceful shutdown tested
- [ ] Disaster recovery plan documented

---

## 10. 💾 Backup Strategy

### Automatic Backups (cron)
```bash
# /etc/cron.d/botaaa-backup
0 */6 * * * botaaa cp /home/botaaa/Botaaa/lookism_data.json /backups/botaaa/data_$(date +\%Y\%m\%d_\%H\%M\%S).json
0 */6 * * * botaaa cp /home/botaaa/Botaaa/lookism_data.sqlite3 /backups/botaaa/sqlite_$(date +\%Y\%m\%d_\%H\%M\%S).sqlite3

# Keep last 7 days
0 3 * * * botaaa find /backups/botaaa/ -mtime +7 -delete
```

### Manual Backup
```bash
cp lookism_data.json lookism_data.json.bak
cp lookism_data.sqlite3 lookism_data.sqlite3.bak
cp bot_memory.json bot_memory.json.bak  # If running bot1
```

### Restore
```bash
cp lookism_data.json.bak lookism_data.json
cp lookism_data.sqlite3.bak lookism_data.sqlite3
sudo systemctl restart botaaa
```
