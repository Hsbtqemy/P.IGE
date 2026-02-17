from __future__ import annotations

import logging
import os
from pathlib import Path
import sys


def _configure_logging() -> None:
    """Configure logging system with environment variable support."""
    log_level = os.environ.get("PIGE_LOG_LEVEL", "WARNING").upper()
    log_dir = Path.home() / ".pige"
    log_dir.mkdir(exist_ok=True)
    
    # Validate log level
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.WARNING
    
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "pige.log", encoding="utf-8")
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.debug(f"Logging configured with level: {log_level}")


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
