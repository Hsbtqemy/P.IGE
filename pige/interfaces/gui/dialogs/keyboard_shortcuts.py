"""Keyboard shortcuts dialog for PIGE GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable


def show_keyboard_shortcuts(parent: tk.Tk, menu_accel: Callable[[str], str]) -> None:
    """Show a dialog with all keyboard shortcuts.
    
    Args:
        parent: Parent window
        menu_accel: Function to format menu accelerator keys (e.g., Cmd/Ctrl)
    """
    dialog = tk.Toplevel(parent)
    dialog.title("Keyboard Shortcuts - PIGE")
    dialog.geometry("600x500")
    dialog.resizable(True, True)
    
    # Create main frame with scrollbar
    main_frame = ttk.Frame(dialog, padding=10)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Title
    title_label = ttk.Label(
        main_frame,
        text="Keyboard Shortcuts",
        font=("TkDefaultFont", 14, "bold")
    )
    title_label.pack(pady=(0, 10))
    
    # Create canvas and scrollbar
    canvas = tk.Canvas(main_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)
    
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    # Define shortcuts by category
    shortcuts = [
        ("File Operations", [
            (f"{menu_accel('N')}", "New Project"),
            (f"{menu_accel('E')}", "New Entry"),
            (f"{menu_accel('S')}", "Save entry (onglet Work actif)"),
            (f"{menu_accel('Q')}", "Quit"),
            ("Delete / Backspace", "Delete selected item"),
        ]),
        ("View", [
            ("F9", "Toggle Focus Mode"),
        ]),
        ("Editor", [
            ("Ctrl+Shift+X", "Toggle checkbox (Windows/Linux)"),
            ("Cmd+Shift+X", "Toggle checkbox (macOS)"),
            ("Ctrl++", "Zoom in (Windows/Linux)"),
            ("Ctrl+-", "Zoom out (Windows/Linux)"),
            ("Ctrl+0", "Reset zoom (Windows/Linux)"),
            ("Cmd++", "Zoom in (macOS)"),
            ("Cmd+-", "Zoom out (macOS)"),
            ("Cmd+0", "Reset zoom (macOS)"),
        ]),
        ("Navigation", [
            ("Double-click", "Open entry or toggle task"),
            ("Enter", "Apply search filter"),
        ]),
        ("Help", [
            ("F1", "Show this dialog"),
        ]),
    ]
    
    # Add shortcuts to scrollable frame
    for category, items in shortcuts:
        category_frame = ttk.LabelFrame(scrollable_frame, text=category, padding=10)
        category_frame.pack(fill=tk.X, padx=5, pady=5)
        
        for key, description in items:
            row = ttk.Frame(category_frame)
            row.pack(fill=tk.X, pady=2)
            
            key_label = ttk.Label(
                row,
                text=key,
                font=("TkDefaultFont", 9, "bold"),
                width=25,
                anchor="w"
            )
            key_label.pack(side=tk.LEFT)
            
            desc_label = ttk.Label(row, text=description, anchor="w")
            desc_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
    
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    # Close button
    button_frame = ttk.Frame(dialog)
    button_frame.pack(fill=tk.X, padx=10, pady=10)
    
    close_button = ttk.Button(
        button_frame,
        text="Close",
        command=dialog.destroy
    )
    close_button.pack(side=tk.RIGHT)
    
    # Bind Escape and F1 to close
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.bind("<F1>", lambda e: dialog.destroy())
    
    # Center dialog on parent
    dialog.transient(parent)
    dialog.grab_set()
    parent.wait_window(dialog)
