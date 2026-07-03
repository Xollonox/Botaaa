from bot.config import OWNER_IDS
from bot.utils.checks import effective_owner_ids


def test_effective_owner_ids_prefers_valid_env(monkeypatch) -> None:
    monkeypatch.setenv("LOOKISM_OWNER_IDS", "111, 222")
    monkeypatch.delenv("BOT_OWNER_IDS", raising=False)
    monkeypatch.delenv("OWNER_IDS", raising=False)

    assert effective_owner_ids() == {111, 222}


def test_effective_owner_ids_falls_back_to_config_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("LOOKISM_OWNER_IDS", raising=False)
    monkeypatch.delenv("BOT_OWNER_IDS", raising=False)
    monkeypatch.delenv("OWNER_IDS", raising=False)

    assert effective_owner_ids() == {int(owner_id) for owner_id in OWNER_IDS}


def test_effective_owner_ids_falls_back_to_config_when_env_invalid(monkeypatch) -> None:
    monkeypatch.setenv("LOOKISM_OWNER_IDS", "abc")
    monkeypatch.delenv("BOT_OWNER_IDS", raising=False)
    monkeypatch.delenv("OWNER_IDS", raising=False)

    assert effective_owner_ids() == {int(owner_id) for owner_id in OWNER_IDS}
