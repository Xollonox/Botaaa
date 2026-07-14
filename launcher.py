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
    "bot2": ("BOT_TOKEN",),
}


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
    return [key for key in REQUIRED_ENV.get(bot_name, ()) if not env.get(key)]


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
        print("No bots started. Add main.py inside Bot/bot1 or Bot/bot2")
        return

    try:
        while True:
            for name, proc in list(procs.items()):
                code = proc.poll()
                if code is not None:
                    print(f"[EXIT] {name} exited with code {code}. Restarting in 10s...")
                    time.sleep(10)
                    new_proc = start_bot(name)
                    if new_proc is not None:
                        procs[name] = new_proc
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
