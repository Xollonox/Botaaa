from bot.utils.checks import effective_owner_ids


def test_effective_owner_ids_from_env(monkeypatch) -> None:
    """Test that effective_owner_ids reads from LOOKISM_OWNER_IDS env."""
    monkeypatch.setenv("LOOKISM_OWNER_IDS", "111, 222")
    # Force a reimport of config to pick up the new env var
    import importlib
    import bot.config
    importlib.reload(bot.config)

    assert effective_owner_ids() == {111, 222}


def test_effective_owner_ids_empty_when_env_missing(monkeypatch) -> None:
    """Test that effective_owner_ids returns empty set when env is unset."""
    monkeypatch.delenv("LOOKISM_OWNER_IDS", raising=False)
    # Force a reimport of config to pick up the missing env var
    import importlib
    import bot.config
    importlib.reload(bot.config)

    assert effective_owner_ids() == set()


def test_effective_owner_ids_empty_when_env_invalid(monkeypatch) -> None:
    """Test that effective_owner_ids returns empty set when env has invalid values."""
    monkeypatch.setenv("LOOKISM_OWNER_IDS", "abc, def")
    # Force a reimport of config to pick up the invalid env var
    import importlib
    import bot.config
    importlib.reload(bot.config)

    assert effective_owner_ids() == set()
