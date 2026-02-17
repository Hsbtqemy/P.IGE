"""Autocomplete Entry widget for Tkinter with tag suggestions.

Provides a ttk.Entry with dropdown autocomplete suggestions based on existing tags.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class AutocompleteEntry(ttk.Entry):
    """Entry widget with autocomplete dropdown for tags.
    
    Supports comma-separated tags with autocomplete suggestions.
    Press Down arrow or start typing to see suggestions.
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        get_suggestions: Callable[[], list[str]],
        **kwargs
    ):
        """Initialize autocomplete entry.
        
        Args:
            parent: Parent widget
            get_suggestions: Callable that returns list of suggestion strings
            **kwargs: Additional arguments passed to ttk.Entry
        """
        super().__init__(parent, **kwargs)
        self._get_suggestions = get_suggestions
        self._listbox: tk.Listbox | None = None
        self._popup: tk.Toplevel | None = None
        self._suggestion_list: list[str] = []
        
        # Bind events
        self.bind("<KeyRelease>", self._on_key_release)
        self.bind("<Down>", self._on_down_arrow)
        self.bind("<Up>", self._on_up_arrow)
        self.bind("<Return>", self._on_return)
        self.bind("<Escape>", self._on_escape)
        self.bind("<FocusOut>", self._on_focus_out)
    
    def _get_current_token(self) -> tuple[str, int, int]:
        """Get the current token being edited and its position.
        
        Returns:
            Tuple of (current_token, token_start_index, token_end_index)
        """
        text = self.get()
        cursor_pos = self.index(tk.INSERT)
        
        # Find start of current token (after last comma)
        start = text.rfind(",", 0, cursor_pos)
        start = start + 1 if start != -1 else 0
        
        # Find end of current token (before next comma or end)
        end = text.find(",", cursor_pos)
        end = end if end != -1 else len(text)
        
        # Extract and strip token
        token = text[start:end].strip()
        return token, start, end
    
    def _update_suggestions(self) -> None:
        """Update the suggestion list based on current token."""
        token, _, _ = self._get_current_token()
        
        if not token:
            self._hide_popup()
            return
        
        # Get all available suggestions
        all_suggestions = self._get_suggestions()
        
        # Filter suggestions by current token (case-insensitive)
        token_lower = token.lower()
        self._suggestion_list = [
            s for s in all_suggestions
            if token_lower in s.lower() and s.lower() != token_lower
        ]
        
        # Get already entered tags to exclude them
        text = self.get()
        entered_tags = [t.strip().lower() for t in text.split(",") if t.strip()]
        self._suggestion_list = [
            s for s in self._suggestion_list
            if s.lower() not in entered_tags
        ]
        
        if self._suggestion_list:
            self._show_popup()
        else:
            self._hide_popup()
    
    def _show_popup(self) -> None:
        """Show the autocomplete popup with suggestions."""
        if not self._popup:
            self._popup = tk.Toplevel(self)
            self._popup.wm_overrideredirect(True)
            self._listbox = tk.Listbox(
                self._popup,
                height=min(8, len(self._suggestion_list)),
                width=self.winfo_width() // 8  # Approximate character width
            )
            self._listbox.pack(fill=tk.BOTH, expand=True)
            self._listbox.bind("<Button-1>", self._on_listbox_select)
            self._listbox.bind("<Return>", self._on_listbox_select)
        
        # Update listbox contents
        self._listbox.delete(0, tk.END)
        for suggestion in self._suggestion_list[:20]:  # Limit to 20 suggestions
            self._listbox.insert(tk.END, suggestion)
        
        if self._listbox.size() > 0:
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        
        # Position popup below entry
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        width = self.winfo_width()
        self._popup.geometry(f"{width}x{min(150, self._listbox.size() * 20)}+{x}+{y}")
        self._popup.lift()
    
    def _hide_popup(self) -> None:
        """Hide the autocomplete popup."""
        if self._popup:
            self._popup.destroy()
            self._popup = None
            self._listbox = None
    
    def _insert_suggestion(self, suggestion: str) -> None:
        """Insert the selected suggestion into the entry."""
        text = self.get()
        cursor_pos = self.index(tk.INSERT)
        
        # Find current token boundaries
        start = text.rfind(",", 0, cursor_pos)
        start = start + 1 if start != -1 else 0
        end = text.find(",", cursor_pos)
        end = end if end != -1 else len(text)
        
        # Build new text
        before = text[:start]
        after = text[end:]
        
        # Add space after comma if before text exists
        if before and not before.endswith(" "):
            before = before.rstrip() + " "
        
        new_text = before + suggestion
        if after and not after.startswith(","):
            new_text += ", " + after.lstrip()
        else:
            new_text += after
        
        self.delete(0, tk.END)
        self.insert(0, new_text)
        
        # Position cursor after inserted suggestion
        new_cursor = len(before) + len(suggestion)
        self.icursor(new_cursor)
        
        self._hide_popup()
    
    def _on_key_release(self, event: tk.Event) -> None:
        """Handle key release to update suggestions."""
        # Ignore special keys
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Escape", "Tab"):
            return
        self._update_suggestions()
    
    def _on_down_arrow(self, event: tk.Event) -> str:
        """Handle down arrow to navigate suggestions or show popup."""
        if not self._popup:
            self._update_suggestions()
            return "break"
        
        if self._listbox:
            current = self._listbox.curselection()
            if current:
                next_idx = current[0] + 1
                if next_idx < self._listbox.size():
                    self._listbox.selection_clear(0, tk.END)
                    self._listbox.selection_set(next_idx)
                    self._listbox.activate(next_idx)
                    self._listbox.see(next_idx)
        return "break"
    
    def _on_up_arrow(self, event: tk.Event) -> str:
        """Handle up arrow to navigate suggestions."""
        if not self._listbox:
            return "break"
        
        current = self._listbox.curselection()
        if current:
            prev_idx = current[0] - 1
            if prev_idx >= 0:
                self._listbox.selection_clear(0, tk.END)
                self._listbox.selection_set(prev_idx)
                self._listbox.activate(prev_idx)
                self._listbox.see(prev_idx)
        return "break"
    
    def _on_return(self, event: tk.Event) -> str | None:
        """Handle return key to select suggestion."""
        if not self._listbox:
            return None
        
        current = self._listbox.curselection()
        if current:
            suggestion = self._listbox.get(current[0])
            self._insert_suggestion(suggestion)
            return "break"
        return None
    
    def _on_escape(self, event: tk.Event) -> str:
        """Handle escape key to hide popup."""
        self._hide_popup()
        return "break"
    
    def _on_focus_out(self, event: tk.Event) -> None:
        """Hide popup when focus is lost."""
        # Delay hiding to allow listbox click to register
        self.after(200, self._hide_popup)
    
    def _on_listbox_select(self, event: tk.Event) -> str:
        """Handle listbox selection."""
        if self._listbox:
            current = self._listbox.curselection()
            if current:
                suggestion = self._listbox.get(current[0])
                self._insert_suggestion(suggestion)
        return "break"
