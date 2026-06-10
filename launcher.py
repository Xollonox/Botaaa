import os
import sys
import time
import signal
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_ROOT = os.path.join(BASE_DIR, "Bot")
BOT_DIRS = ["bot1", "bot2", "bot3"]


def start_bot(bot_name: str):
    bot_dir = os.path.join(BOT_ROOT, bot_name)
    script_path = os.path.join(bot_dir, "main.py")
    if not os.path.exists(script_path):
        print(f"[SKIP] {bot_name}: missing {script_path}")
        return None

    cmd = [sys.executable, script_path]
    proc = subprocess.Popen(cmd, cwd=bot_dir)
    print(f"[STARTED] {bot_name} (pid={proc.pid})")
    return proc


def main():
    procs = {}

    for name in BOT_DIRS:
        proc = start_bot(name)
        if proc is not None:
            procs[name] = proc

    if not procs:
        print("No bots started. Add main.py inside Bot/bot1..bot4")
        return

    try:
        while True:
            for name, proc in list(procs.items()):
                code = proc.poll()
                if code is not None:
                    print(f"[EXIT] {name} exited with code {code}. Restarting in 3s...")
                    time.sleep(3)
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


if __name__ == "__main__":
    main()
