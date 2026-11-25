"""
PRIMERS OS — centralised logging.

Everything goes to a rotating ``primers.log`` in the log directory. The
terminal only shows errors by default so background threads never scribble
over the interactive prompt; set ``PRIMERS_DEBUG=1`` to see everything.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from utils import paths

_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_file_handler = None
_file_handler_failed = False


def _shared_file_handler():
    global _file_handler, _file_handler_failed
    if _file_handler is None and not _file_handler_failed:
        try:
            handler = RotatingFileHandler(
                os.path.join(paths.log_dir(), "primers.log"),
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(_FORMAT))
            handler.setLevel(logging.DEBUG)
            _file_handler = handler
        except OSError:
            # Read-only home, full disk… keep running with console logging.
            _file_handler_failed = True
    return _file_handler


class PrimersLogger:
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        logger = logging.getLogger(f"primers.{name}")
        if not logger.handlers:
            logger.setLevel(logging.DEBUG)
            logger.propagate = False

            console = logging.StreamHandler(sys.stderr)
            console.setFormatter(logging.Formatter(_FORMAT))
            debug = os.environ.get("PRIMERS_DEBUG", "").lower() in ("1", "true", "yes")
            console.setLevel(logging.DEBUG if debug else logging.ERROR)
            logger.addHandler(console)

            fh = _shared_file_handler()
            if fh is not None:
                logger.addHandler(fh)
        return logger

    @staticmethod
    def log_path() -> str:
        return os.path.join(paths.log_dir(), "primers.log")
