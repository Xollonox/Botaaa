# Botaaa

Run the launcher from the repo root with `python launcher.py`.

By default, only the real bots are started: `Bot/bot1` and `Bot/bot2`.
`Bot/bot3` and `Bot/bot4` are placeholders and exit immediately if run directly.

Bot v2 stores its runtime state under `Bot/bot2/`:
`lookism_data.json` and `lookism_data.sqlite3` live next to the bot code unless `LOOKISM_SQLITE_PATH` is set.
