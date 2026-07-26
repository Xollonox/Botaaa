from bot.utils.checks import effective_owner_ids


def test_effective_owner_ids_from_env(monkeypatch) -> None:
    """Reads LOOKISM_OWNER_IDS from the process environment on each call."""
    monkeypatch.setenv("LOOKISM_OWNER_IDS", "111, 222")
    assert effective_owner_ids() == {111, 222}


def test_effective_owner_ids_empty_when_env_missing(monkeypatch) -> None:
    """Returns empty set when env is unset (dotenv is not re-consulted)."""
    monkeypatch.delenv("LOOKISM_OWNER_IDS", raising=False)
    assert effective_owner_ids() == set()


def test_effective_owner_ids_empty_when_env_invalid(monkeypatch) -> None:
    """Returns empty set when env has no parseable integer values."""
    monkeypatch.setenv("LOOKISM_OWNER_IDS", "abc, def")
    assert effective_owner_ids() == set()
