"""Configuration for Lookism Bot v2."""

import os

BOT_TOKEN = "MTQ2OTM4MzI3MTgyNDQ5MDcxOQ.GJRzn8.dha4uARmFlygx6bG1_YHmkbsumNeLgoBzJ6foQ"
OWNER_IDS = {1152936208742240316, 944972813041803285}
DATA_PATH = "lookism_data.json"
SQLITE_PATH = os.getenv("LOOKISM_SQLITE_PATH", "lookism_data.sqlite3")

# Set to a list of guild IDs for fast development sync, or None for global sync.
GUILD_IDS = None

OWNER_GUILD_ID = 1447875474364829748
