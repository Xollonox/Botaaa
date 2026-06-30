from datetime import datetime, timezone

bot_start_time = datetime.now(timezone.utc)
messages_processed = 0
active_users_today: set[int] = set()

