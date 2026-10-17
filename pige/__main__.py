from __future__ import annotations

import logging
import os
import sys


def _configure_logging() -> None:
    """Console + rotating log file in the per-user log folder (PIGE_LOG_LEVEL, PIGE_LOG_DIR)."""
    from logging.handlers import RotatingFileHandler

    from pige.core import paths

    log_level = os.environ.get("PIGE_LOG_LEVEL", "WARNING").upper()
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.WARNING

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_dir = paths.log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "pige.log"
        handlers.append(RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
        if not sys.platform.startswith("win"):
            os.chmod(log_file, 0o600)  # logs may mention project names
    except OSError:
        pass  # read-only home or similar: console logging still works

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def main() -> int:
    # Configure logging first
    _configure_logging()
    
    # Usage:
    #   python -m pige ...        -> CLI
    #   python -m pige gui        -> GUI
    if len(sys.argv) >= 2 and sys.argv[1] == "gui":
        # L'interface GUI recevra éventuellement ses propres args après "gui"
        from pige.interfaces.gui import main as gui_main

        return gui_main(sys.argv[2:])

    from pige.interfaces.cli import main as cli_main
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
