from __future__ import annotations

import sys


def main() -> int:
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
