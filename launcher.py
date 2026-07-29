import os
import sys
import time
import signal
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_ROOT = os.path.join(BASE_DIR, "Bot")
DEFAULT_BOT_DIRS = ["bot1", "bot2"]
REQUIRED_ENV = {
    "bot1": ("DISCORD_TOKEN",),
    # LOOKISM_OWNER_IDS is intentionally NOT required: config.py only warns
    # and owner commands get disabled (see tests/test_launcher.py).
    "bot2": ("BOT_TOKEN", "FIREBASE_PROJECT_ID"),
}
# bot2 additionally needs ONE of these credentials variants.
BOT2_FIREBASE_CRED_VARS = ("FIREBASE_CREDENTIALS_PATH", "FIREBASE_CREDENTIALS_JSON")

# Restart backoff: starts at BACKOFF_START, doubles per rapid crash, resets
# once a process stays up longer than STABLE_SECONDS.
BACKOFF_START = 10
BACKOFF_MAX = 300
STABLE_SECONDS = 60


def _load_env_file(path: str) -> dict[str, str]:
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    return values


def _bot_names() -> list[str]:
    raw = os.getenv("BOTAAA_BOTS", "")
    if not raw.strip():
        return DEFAULT_BOT_DIRS
    return [name.strip() for name in raw.split(",") if name.strip()]


def _env_for_bot(bot_name: str) -> dict[str, str]:
    dotenv = _load_env_file(os.path.join(BOT_ROOT, bot_name, ".env"))
    env = {**dotenv, **os.environ}
    return env


def _missing_required_env(bot_name: str, env: dict[str, str]) -> list[str]:
    missing = [key for key in REQUIRED_ENV.get(bot_name, ()) if not env.get(key)]
    if bot_name == "bot2" and not any(env.get(k) for k in BOT2_FIREBASE_CRED_VARS):
        missing.append("FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS_JSON")
    return missing


def start_bot(bot_name: str):
    bot_dir = os.path.join(BOT_ROOT, bot_name)
    script_path = os.path.join(bot_dir, "main.py")
    if not os.path.exists(script_path):
        print(f"[SKIP] {bot_name}: missing {script_path}")
        return None

    env = _env_for_bot(bot_name)
    missing = _missing_required_env(bot_name, env)
    if missing:
        print(f"[SKIP] {bot_name}: missing required env {', '.join(missing)}")
        return None
    cmd = [sys.executable, script_path]
    proc = subprocess.Popen(cmd, cwd=bot_dir, env=env)
    print(f"[STARTED] {bot_name} (pid={proc.pid})")
    return proc


def main():
    procs = {}

    def request_shutdown(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    for name in _bot_names():
        proc = start_bot(name)
        if proc is not None:
            procs[name] = proc

    if not procs:
        print("No bots started. Add main.py inside a configured Bot/ directory")
        return

    backoff = {name: BACKOFF_START for name in procs}
    started_at = {name: time.monotonic() for name in procs}
    try:
        while True:
            for name, proc in list(procs.items()):
                code = proc.poll()
                if code is not None:
                    # A long-lived process earns a reset of its backoff.
                    if time.monotonic() - started_at.get(name, 0) > STABLE_SECONDS:
                        backoff[name] = BACKOFF_START
                    delay = backoff.get(name, BACKOFF_START)
                    print(f"[EXIT] {name} exited with code {code}. Restarting in {delay}s...")
                    time.sleep(delay)
                    new_proc = start_bot(name)
                    if new_proc is not None:
                        procs[name] = new_proc
                        started_at[name] = time.monotonic()
                        backoff[name] = min(delay * 2, BACKOFF_MAX)
                    else:
                        del procs[name]
            if not procs:
                print("All bots stopped.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping all bots...")
        for proc in procs.values():
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
        time.sleep(1)
        for proc in procs.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in procs.values():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
