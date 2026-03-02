from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from scheduler.config import Settings


def configure_logging(settings: Settings) -> None:
    settings.expanded_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = settings.expanded_log_dir / "app.log"

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = TimedRotatingFileHandler(
        filename=log_path,
        when="D",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(stream_handler)
