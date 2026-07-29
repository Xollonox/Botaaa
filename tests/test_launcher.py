import launcher

# Minimal runnable bot2 env: token + Firebase project + one credentials variant.
BOT2_BASE_ENV = {
    "BOT_TOKEN": "token",
    "FIREBASE_PROJECT_ID": "proj",
    "FIREBASE_CREDENTIALS_PATH": "/tmp/sa.json",
}


def test_bot2_owner_ids_accepts_comma_separated_numbers() -> None:
    env = {**BOT2_BASE_ENV, "LOOKISM_OWNER_IDS": "123, 456"}

    assert launcher._missing_required_env("bot2", env) == []


def test_bot2_owner_ids_accepts_alternate_env_names() -> None:
    env = {**BOT2_BASE_ENV, "BOT_OWNER_IDS": "123"}

    assert launcher._missing_required_env("bot2", env) == []


def test_bot2_does_not_require_owner_env() -> None:
    assert launcher._missing_required_env("bot2", dict(BOT2_BASE_ENV)) == []


def test_bot2_invalid_owner_env_does_not_block_startup() -> None:
    env = {**BOT2_BASE_ENV, "LOOKISM_OWNER_IDS": "abc"}

    assert launcher._missing_required_env("bot2", env) == []


def test_bot2_requires_firebase_project_id() -> None:
    env = {"BOT_TOKEN": "token", "FIREBASE_CREDENTIALS_PATH": "/tmp/sa.json"}

    assert launcher._missing_required_env("bot2", env) == ["FIREBASE_PROJECT_ID"]


def test_bot2_requires_a_firebase_credentials_variant() -> None:
    env = {"BOT_TOKEN": "token", "FIREBASE_PROJECT_ID": "proj"}

    assert launcher._missing_required_env("bot2", env) == [
        "FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS_JSON"
    ]


def test_bot2_accepts_credentials_json_variant() -> None:
    env = {
        "BOT_TOKEN": "token",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_CREDENTIALS_JSON": "{}",
    }

    assert launcher._missing_required_env("bot2", env) == []


def test_bot2_reports_all_missing_firebase_vars() -> None:
    env = {"BOT_TOKEN": "token"}

    assert launcher._missing_required_env("bot2", env) == [
        "FIREBASE_PROJECT_ID",
        "FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS_JSON",
    ]


def test_default_launcher_includes_only_bots_in_this_workspace(monkeypatch) -> None:
    monkeypatch.delenv("BOTAAA_BOTS", raising=False)
    assert launcher._bot_names() == ["bot1", "bot2"]
