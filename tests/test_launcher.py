import launcher


def test_bot2_owner_ids_accepts_comma_separated_numbers() -> None:
    env = {"LOOKISM_OWNER_IDS": "123, 456", "BOT_TOKEN": "token"}

    assert launcher._missing_required_env("bot2", env) == []


def test_bot2_owner_ids_accepts_alternate_env_names() -> None:
    env = {"BOT_OWNER_IDS": "123", "BOT_TOKEN": "token"}

    assert launcher._missing_required_env("bot2", env) == []


def test_bot2_does_not_require_owner_env() -> None:
    env = {"BOT_TOKEN": "token"}

    assert launcher._missing_required_env("bot2", env) == []


def test_bot2_invalid_owner_env_does_not_block_startup() -> None:
    env = {"LOOKISM_OWNER_IDS": "abc", "BOT_TOKEN": "token"}

    assert launcher._missing_required_env("bot2", env) == []
