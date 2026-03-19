"""About dialog for PIGE GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from pige.utils.updates import get_installed_version


def show_about_dialog(parent: tk.Tk) -> None:
    """Show About PIGE dialog."""
    dialog = tk.Toplevel(parent)
    dialog.title("About PIGE")
    dialog.geometry("400x300")
    dialog.resizable(False, False)
    
    frame = ttk.Frame(dialog, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)
    
    # Title
    title_label = ttk.Label(
        frame,
        text="PIGE",
        font=("TkDefaultFont", 20, "bold")
    )
    title_label.pack(pady=(0, 5))
    
    # Subtitle
    subtitle_label = ttk.Label(
        frame,
        text="Project Integrated Journaling Engine",
        font=("TkDefaultFont", 10)
    )
    subtitle_label.pack(pady=(0, 20))
    
    # Version (métadonnées du paquet installé)
    version_label = ttk.Label(
        frame,
        text=f"Version {get_installed_version()}",
        font=("TkDefaultFont", 9)
    )
    version_label.pack(pady=(0, 20))
    
    # Description
    desc_text = (
        "PIGE is a local-first project journaling tool\n"
        "that helps you organize and track your work.\n\n"
        "Features:\n"
        "• Project-based organization\n"
        "• Multiple entry types (notes, meetings, decisions)\n"
        "• Task management with time tracking\n"
        "• Export capabilities\n"
        "• All data stored locally in JSON/Markdown"
    )
    desc_label = ttk.Label(
        frame,
        text=desc_text,
        justify=tk.LEFT
    )
    desc_label.pack(pady=(0, 20))
    
    # Close button
    close_button = ttk.Button(
        frame,
        text="Close",
        command=dialog.destroy
    )
    close_button.pack()
    
    # Center dialog on parent
    dialog.transient(parent)
    dialog.grab_set()
