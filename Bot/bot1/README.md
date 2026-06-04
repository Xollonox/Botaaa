# Miss Kim Discord Bot (Cerebras)

## Features
- Multi-server support
- Auto trigger replies: hi, hello, good night, thanks, etc.
- Auto revive dead chat after silence window
- `/ask` and `!kim` AI replies
- Owner/admin-only command controls (`!say`, `!purge`)
- Cerebras API key failover (`CEREBRAS_API_KEY` -> `CEREBRAS_API_KEY_2` on 429/unauthorized)

## Setup (Termux / Linux / VPS)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set your env vars:
```bash
set -a
. ./.env
set +a
python main.py
```

## Discord Dev Portal requirements
- Enable **Message Content Intent**
- Invite bot with permissions: Send Messages, Read Message History, Manage Messages

## Commands
- `/ask <question>`
- `!kim <question>`
- `!say <message>` owner/admin only
- `!purge <count>` owner/admin only

## Notes
- `SPECIAL_USER_ID` always has full bot command access.
- Any guild Administrator also has admin-level bot command access.
