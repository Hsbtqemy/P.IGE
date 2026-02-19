"""Entry point for PyInstaller-bundled PIGE GUI (.exe / .app).

When run, forwards to `python -m pige gui` so the same code path is used.
"""

import sys

if __name__ == "__main__":
    # Simulate: python -m pige gui [args...]
    sys.argv = [sys.argv[0], "gui"] + sys.argv[1:]
    from pige.__main__ import main
    sys.exit(main())
