"""PIGE GUI package - Modular Tkinter interface."""

from __future__ import annotations

from pige.interfaces.gui.main_window import PigeMainWindow, main

# Re-export for backward compatibility
# The legacy PigeApp is available at pige.interfaces.gui_legacy
__all__ = ["PigeMainWindow", "main"]



