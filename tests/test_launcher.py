import launcher


def test_bot2_owner_ids_must_be_numeric() -> None:
    env = {"LOOKISM_OWNER_IDS": "abc", "BOT_TOKEN": "token"}

    assert launcher._invalid_env("bot2", env) == [
        "owner IDs must contain at least one numeric Discord user ID"
    ]


def test_bot2_owner_ids_accepts_comma_separated_numbers() -> None:
    env = {"LOOKISM_OWNER_IDS": "123, 456", "BOT_TOKEN": "token"}

    assert launcher._invalid_env("bot2", env) == []


def test_bot2_owner_ids_accepts_alternate_env_names() -> None:
    env = {"BOT_OWNER_IDS": "123", "BOT_TOKEN": "token"}

    assert launcher._missing_required_env("bot2", env) == []
    assert launcher._invalid_env("bot2", env) == []
