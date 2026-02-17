"""Pagination control for TreeView widgets.

This module provides a reusable pagination widget for displaying large datasets
in chunks, with navigation controls and page size selection.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class PaginationState:
    """Current pagination state."""
    
    page: int = 1  # Current page (1-indexed)
    page_size: int = 100  # Items per page
    total_items: int = 0  # Total number of items
    
    @property
    def total_pages(self) -> int:
        """Calculate total number of pages."""
        if self.page_size <= 0 or self.total_items <= 0:
            return 1
        return (self.total_items + self.page_size - 1) // self.page_size
    
    @property
    def start_index(self) -> int:
        """Get start index for current page (0-indexed)."""
        return (self.page - 1) * self.page_size
    
    @property
    def end_index(self) -> int:
        """Get end index for current page (0-indexed, exclusive)."""
        return min(self.start_index + self.page_size, self.total_items)
    
    @property
    def is_first_page(self) -> bool:
        """Check if on first page."""
        return self.page == 1
    
    @property
    def is_last_page(self) -> bool:
        """Check if on last page."""
        return self.page >= self.total_pages
    
    def get_page_slice(self, items: list[T]) -> list[T]:
        """Get slice of items for current page."""
        return items[self.start_index:self.end_index]
    
    def go_to_page(self, page: int) -> None:
        """Navigate to specific page (1-indexed)."""
        self.page = max(1, min(page, self.total_pages))
    
    def next_page(self) -> bool:
        """Go to next page. Returns True if moved."""
        if not self.is_last_page:
            self.page += 1
            return True
        return False
    
    def previous_page(self) -> bool:
        """Go to previous page. Returns True if moved."""
        if not self.is_first_page:
            self.page -= 1
            return True
        return False
    
    def set_page_size(self, size: int) -> None:
        """Change page size and adjust current page if needed."""
        old_start = self.start_index
        self.page_size = max(1, size)
        # Try to keep same starting item visible
        self.page = (old_start // self.page_size) + 1
        self.page = max(1, min(self.page, self.total_pages))


class PaginationControl(ttk.Frame):
    """Pagination control widget with navigation and page size selection.
    
    Displays: [<< Previous] Page X of Y [Next >>] | Show: [50▼] items per page
    """
    
    PAGE_SIZES = [50, 100, 200, 500, 1000]  # Available page sizes
    
    def __init__(
        self,
        parent: tk.Widget,
        on_page_change: Callable[[PaginationState], None],
        initial_page_size: int = 100,
        show_all_option: bool = True,
        **kwargs
    ):
        """Initialize pagination control.
        
        Args:
            parent: Parent widget
            on_page_change: Callback when page changes, receives PaginationState
            initial_page_size: Initial page size (default: 100)
            show_all_option: Whether to show "All" option in page size dropdown
            **kwargs: Additional arguments for Frame
        """
        super().__init__(parent, **kwargs)
        
        self.on_page_change = on_page_change
        self.show_all_option = show_all_option
        
        self.state = PaginationState(page=1, page_size=initial_page_size)
        
        self._setup_ui()
        self._update_ui()
    
    def _setup_ui(self) -> None:
        """Create pagination UI elements."""
        # Left side: Navigation buttons and page info
        nav_frame = ttk.Frame(self)
        nav_frame.pack(side=tk.LEFT, padx=5)
        
        self.prev_button = ttk.Button(
            nav_frame,
            text="<< Previous",
            command=self._on_previous,
            width=12
        )
        self.prev_button.pack(side=tk.LEFT, padx=2)
        
        self.page_label = ttk.Label(
            nav_frame,
            text="Page 1 of 1",
            width=15,
            anchor=tk.CENTER
        )
        self.page_label.pack(side=tk.LEFT, padx=5)
        
        self.next_button = ttk.Button(
            nav_frame,
            text="Next >>",
            command=self._on_next,
            width=12
        )
        self.next_button.pack(side=tk.LEFT, padx=2)
        
        # Separator
        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        # Right side: Page size selector
        size_frame = ttk.Frame(self)
        size_frame.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(size_frame, text="Show:").pack(side=tk.LEFT, padx=2)
        
        self.size_var = tk.StringVar(value=str(self.state.page_size))
        
        # Build page size options
        size_options = [str(size) for size in self.PAGE_SIZES]
        if self.show_all_option:
            size_options.append("All")
        
        self.size_combo = ttk.Combobox(
            size_frame,
            textvariable=self.size_var,
            values=size_options,
            width=8,
            state="readonly"
        )
        self.size_combo.pack(side=tk.LEFT, padx=2)
        self.size_combo.bind("<<ComboboxSelected>>", self._on_page_size_change)
        
        ttk.Label(size_frame, text="items per page").pack(side=tk.LEFT, padx=2)
        
        # Far right: Total count
        self.total_label = ttk.Label(
            self,
            text="(0 total)",
            anchor=tk.E
        )
        self.total_label.pack(side=tk.RIGHT, padx=10)
        
        # Jump to page (hidden by default, can be shown with Ctrl+G)
        self.jump_frame = ttk.Frame(self)
        ttk.Label(self.jump_frame, text="Go to page:").pack(side=tk.LEFT, padx=2)
        
        self.jump_entry = ttk.Entry(self.jump_frame, width=6)
        self.jump_entry.pack(side=tk.LEFT, padx=2)
        self.jump_entry.bind("<Return>", self._on_jump)
        
        ttk.Button(
            self.jump_frame,
            text="Go",
            command=self._on_jump,
            width=5
        ).pack(side=tk.LEFT, padx=2)
    
    def set_total_items(self, total: int) -> None:
        """Update total item count and refresh UI."""
        self.state.total_items = total
        # Ensure current page is valid
        if self.state.page > self.state.total_pages:
            self.state.page = max(1, self.state.total_pages)
        self._update_ui()
    
    def reset(self, total_items: int | None = None) -> None:
        """Reset to first page, optionally updating total."""
        self.state.page = 1
        if total_items is not None:
            self.state.total_items = total_items
        self._update_ui()
    
    def get_page_size(self) -> int | None:
        """Get current page size. Returns None if 'All' is selected."""
        if self.size_var.get() == "All":
            return None
        return self.state.page_size
    
    def _update_ui(self) -> None:
        """Update UI to reflect current state."""
        # Update page label
        self.page_label.config(
            text=f"Page {self.state.page} of {self.state.total_pages}"
        )
        
        # Update total label
        start = self.state.start_index + 1 if self.state.total_items > 0 else 0
        end = self.state.end_index
        self.total_label.config(
            text=f"({start}-{end} of {self.state.total_items} total)"
        )
        
        # Enable/disable navigation buttons
        self.prev_button.config(
            state=tk.NORMAL if not self.state.is_first_page else tk.DISABLED
        )
        self.next_button.config(
            state=tk.NORMAL if not self.state.is_last_page else tk.DISABLED
        )
    
    def _on_previous(self) -> None:
        """Handle Previous button click."""
        if self.state.previous_page():
            self._update_ui()
            self.on_page_change(self.state)
    
    def _on_next(self) -> None:
        """Handle Next button click."""
        if self.state.next_page():
            self._update_ui()
            self.on_page_change(self.state)
    
    def _on_page_size_change(self, event=None) -> None:
        """Handle page size change."""
        size_str = self.size_var.get()
        
        if size_str == "All":
            # Special case: show all items
            self.state.page_size = self.state.total_items if self.state.total_items > 0 else 9999999
            self.state.page = 1
        else:
            try:
                new_size = int(size_str)
                self.state.set_page_size(new_size)
            except ValueError:
                return
        
        self._update_ui()
        self.on_page_change(self.state)
    
    def _on_jump(self, event=None) -> None:
        """Handle jump to page."""
        try:
            page = int(self.jump_entry.get())
            self.state.go_to_page(page)
            self._update_ui()
            self.on_page_change(self.state)
            self.jump_entry.delete(0, tk.END)
        except ValueError:
            pass
    
    def show_jump_controls(self) -> None:
        """Show jump to page controls."""
        self.jump_frame.pack(side=tk.LEFT, padx=10)
        self.jump_entry.focus_set()
    
    def hide_jump_controls(self) -> None:
        """Hide jump to page controls."""
        self.jump_frame.pack_forget()


def paginate_items(items: list[T], page: int, page_size: int) -> tuple[list[T], PaginationState]:
    """Helper function to paginate a list of items.
    
    Args:
        items: Full list of items
        page: Page number (1-indexed)
        page_size: Items per page
    
    Returns:
        Tuple of (paginated_items, pagination_state)
    """
    state = PaginationState(
        page=page,
        page_size=page_size,
        total_items=len(items)
    )
    
    paginated = state.get_page_slice(items)
    return paginated, state
