"""Logging configuration for Lookism Bot."""

from __future__ import annotations

import logging
from pathlib import Path
import sys


def setup_logging() -> None:
    """Configure root and discord loggers."""
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)

    log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "bot.log", encoding="utf-8")
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    existing_handler_types = {type(handler) for handler in root.handlers}
    if logging.StreamHandler not in existing_handler_types:
        root.addHandler(stream_handler)
    if logging.FileHandler not in existing_handler_types:
        root.addHandler(file_handler)
    root.setLevel(logging.INFO)

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
