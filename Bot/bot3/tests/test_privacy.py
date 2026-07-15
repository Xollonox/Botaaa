from __future__ import annotations

from neetverse.database import Database
from neetverse.goals import GoalService
from neetverse.privacy import PrivacyService
from neetverse.profiles import ProfileService


def test_export_is_user_scoped_and_delete_removes_audits(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    profiles = ProfileService(database)
    for user_id in ("1", "2"):
        profiles.ensure_draft(user_id, user_id, now=1)
        profiles.update(user_id, {"target_year": 2027, "current_status": "Other", "timezone": "UTC"}, now=2)
    GoalService(database).create("1", title="One goal", metric="questions", target_value=10, unit="questions", now=3)
    privacy = PrivacyService(database)

    exported = privacy.export("1")
    assert exported["user_id"] == "1"
    assert exported["data"]["goals"][0]["title"] == "One goal"
    assert all(row.get("user_id") != "2" for rows in exported["data"].values() for row in rows)

    assert privacy.delete("1") is True
    assert profiles.get("1") is None
    assert profiles.get("2") is not None
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM domain_events WHERE user_id='1'").fetchone()[0] == 0
