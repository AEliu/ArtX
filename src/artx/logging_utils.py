from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "artx"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure_logging(verbose: bool, log_file: str | None) -> None:
    logger = get_logger()
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    else:
        logger.addHandler(logging.NullHandler())
