"""Main window for PIGE GUI - Refactored modular version."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from pige.core.service import PigeService
from pige.core.storage import Storage
from pige.interfaces import gui_helpers
from pige.interfaces.gui.dialogs import (
    show_about_dialog,
    show_keyboard_shortcuts,
    show_new_entry_dialog,
    show_new_project_dialog,
)
from pige.interfaces.gui.panels import BrowsePanel, CalendarPanel, DashboardPanel, SearchPanel, WorkPanel
from pige.utils import io as io_utils

logger = logging.getLogger(__name__)


class PigeMainWindow(tk.Tk):
    """Main window for PIGE application.
    
    This is a refactored version that uses modular panels and dialogs
    instead of a monolithic class.
    """
    
    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self.title("PIGE")
        self.geometry("1200x700")
        
        # Initialize core services
        self.storage = Storage(data_dir)
        self.service = PigeService(self.storage)
        self.service.init_storage()
        
        # Load preferences
        self.prefs_path = self.storage.data_dir / ".pige_prefs.json"
        self.legacy_prefs_path = self.storage.data_dir / "gui_prefs.json"
        self.gui_prefs = self._load_gui_prefs()
        
        # Setup UI
        self._setup_menu()
        self._setup_main_layout()
        self._setup_keybindings()
        
        # Bind window close event to save preferences
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        logger.info(f"PIGE GUI initialized with data_dir={data_dir}")
    
    def _load_gui_prefs(self) -> dict:
        """Load GUI preferences from disk."""
        # Try new location first
        if self.prefs_path.exists():
            return io_utils.read_json(self.prefs_path, default={})
        # Fall back to legacy location
        if self.legacy_prefs_path.exists():
            prefs = io_utils.read_json(self.legacy_prefs_path, default={})
            # Migrate to new location
            io_utils.safe_write_json(self.prefs_path, prefs)
            return prefs
        return {}
    
    def _save_gui_prefs(self) -> None:
        """Save GUI preferences to disk."""
        io_utils.safe_write_json(self.prefs_path, self.gui_prefs)
    
    def _setup_menu(self) -> None:
        """Create the menu bar."""
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(
            label="New Project",
            accelerator=gui_helpers._menu_accel("N"),
            command=self._on_new_project
        )
        file_menu.add_command(
            label="New Entry",
            accelerator=gui_helpers._menu_accel("E"),
            command=self._on_new_entry
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Quit",
            accelerator=gui_helpers._menu_accel("Q"),
            command=self.quit
        )
        
        # Search menu
        search_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Search", menu=search_menu)
        search_menu.add_command(
            label="Find...",
            accelerator=gui_helpers._menu_accel("F"),
            command=self._on_search
        )
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(
            label="Keyboard Shortcuts",
            accelerator="F1",
            command=self._show_keyboard_shortcuts
        )
        help_menu.add_separator()
        help_menu.add_command(
            label="About PIGE",
            command=self._show_about
        )
    
    def _setup_main_layout(self) -> None:
        """Create the main window layout."""
        # Create notebook (tabbed interface)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab 1: Work - Mode Focus/Journaling (DEFAULT)
        self.work_panel = WorkPanel(
            self.notebook,
            self.service
        )
        self.notebook.add(self.work_panel, text="🎯 Work")
        
        # Tab 2: Dashboard (vue d'ensemble)
        self.dashboard_panel = DashboardPanel(
            self.notebook,
            self.service,
            initial_days=7
        )
        self.notebook.add(self.dashboard_panel, text="📊 Dashboard")
        
        # Tab 3: Browse (Projects + Entries combinés)
        self.browse_panel = BrowsePanel(
            self.notebook,
            self.service,
            self.gui_prefs
        )
        self.notebook.add(self.browse_panel, text="🗂️ Browse")
        
        # Tab 4: Calendar (vue mensuelle)
        self.calendar_panel = CalendarPanel(
            self.notebook,
            self.service,
            on_entry_open=self._on_open_entry_from_calendar
        )
        self.notebook.add(self.calendar_panel, text="📅 Calendrier")
        
        # Tab 5: Search
        self.search_panel = SearchPanel(
            self.notebook,
            self.service,
            on_result_selected=self._on_search_result_selected
        )
        self.notebook.add(self.search_panel, text="🔍 Search")
    
    def _setup_keybindings(self) -> None:
        """Setup keyboard shortcuts."""
        # File operations - only when focus is NOT in a text widget (avoid triggering while typing)
        self.bind("<Control-n>", self._on_key_new_project)
        self.bind("<Command-n>", self._on_key_new_project)
        self.bind("<Control-e>", self._on_key_new_entry)
        self.bind("<Command-e>", self._on_key_new_entry)
        self.bind("<Control-q>", lambda e: self.quit())
        self.bind("<Command-q>", lambda e: self.quit())

        # Search - only when focus is NOT in a text widget
        self.bind("<Control-f>", self._on_key_search)
        self.bind("<Command-f>", self._on_key_search)

        # Help
        self.bind("<F1>", lambda e: self._show_keyboard_shortcuts())

    def _focus_in_text_widget(self) -> bool:
        """Return True if focus is in an Entry, Text, or Combobox (don't trigger shortcuts while typing)."""
        w = self.focus_get()
        if w is None:
            return False
        try:
            cls = w.winfo_class()
            return cls in ("Entry", "Text", "TEntry", "TCombobox")
        except tk.TclError:
            return False

    def _on_key_new_project(self, e: tk.Event) -> str | None:
        if self._focus_in_text_widget():
            return None
        self._on_new_project()
        return "break"

    def _on_key_new_entry(self, e: tk.Event) -> str | None:
        if self._focus_in_text_widget():
            return None
        self._on_new_entry()
        return "break"

    def _on_key_search(self, e: tk.Event) -> str | None:
        if self._focus_in_text_widget():
            return None
        self._on_search()
        return "break"
    
    # ===== Menu actions =====
    
    def _on_new_project(self) -> None:
        """Handle New Project action."""
        logger.info("New Project action triggered")
        project = show_new_project_dialog(self, self.service)
        if project:
            self._after_new_project(project)

    def _after_new_project(self, project) -> None:
        """After a project is created: refresh browse panel and select the new project."""
        self.browse_panel.projects_panel.refresh()
        self.browse_panel.projects_panel.tree.selection_set(project.id)
        self.browse_panel.projects_panel.tree.see(project.id)
    
    def _on_new_entry(self) -> None:
        """Handle New Entry action."""
        logger.info("New Entry action triggered")
        selection = self.browse_panel.projects_panel.tree.selection()
        if not selection:
            messagebox.showerror("No project", "Select a project first.")
            return
        project_id = selection[0]
        result = show_new_entry_dialog(self, self.service, project_id)
        if result:
            entry, _path = result
            self.browse_panel.entries_panel.refresh()
            self.browse_panel.entries_panel.tree.selection_set(entry.id)
            self.browse_panel.entries_panel.tree.see(entry.id)
    
    def _on_search(self) -> None:
        """Handle Search action (Ctrl+F)."""
        logger.info("Search action triggered")
        # Switch to search tab and focus search input
        self.notebook.select(self.search_panel)
        self.search_panel.focus_search()
    
    def _on_search_result_selected(self, result_type: str, result_id: str) -> None:
        """Handle when a search result is selected.

        Args:
            result_type: Type of result (entry, project, task)
            result_id: ID of the selected item
        """
        logger.info(f"Search result selected: {result_type} - {result_id}")
        if result_type == "project":
            self.notebook.select(self.browse_panel)
            self.browse_panel.projects_panel.refresh()
            self.browse_panel.projects_panel.tree.selection_set(result_id)
            self.browse_panel.projects_panel.tree.see(result_id)
        elif result_type == "entry":
            self.notebook.select(self.work_panel)
            self.work_panel._load_entry_in_editor(result_id)
        elif result_type == "task":
            self.notebook.select(self.work_panel)
            self.work_panel.show_task(result_id)
    
    def _on_open_entry_from_calendar(self, entry_id: str) -> None:
        """Open an entry in the WorkPanel from the calendar.
        
        Args:
            entry_id: ID of the entry to open
        """
        logger.info(f"Opening entry {entry_id} from calendar")
        
        # Switch to Work tab
        self.notebook.select(self.work_panel)
        
        # Load entry in WorkPanel editor
        self.work_panel._load_entry_in_editor(entry_id)
        # Bring entry to front in explorer (expand project, select and scroll to it)
        self.work_panel.reveal_entry_in_explorer(entry_id)
    
    def _show_keyboard_shortcuts(self) -> None:
        """Show keyboard shortcuts dialog."""
        show_keyboard_shortcuts(self, gui_helpers._menu_accel)
    
    def _show_about(self) -> None:
        """Show about dialog."""
        show_about_dialog(self)
    
    def _on_closing(self) -> None:
        """Handle window closing - save preferences."""
        logger.info("Saving preferences before closing")
        
        # Save pagination preferences
        if not self.gui_prefs.get("pagination"):
            self.gui_prefs["pagination"] = {}
        
        self.gui_prefs["pagination"]["projects_page_size"] = self.browse_panel.get_projects_page_size()
        self.gui_prefs["pagination"]["entries_page_size"] = self.browse_panel.get_entries_page_size()
        
        # Save to disk
        self._save_gui_prefs()
        
        # Close window
        self.destroy()


def main(argv: list[str] | None = None) -> int:
    """Entry point for PIGE GUI."""
    _ = argv
    
    # Resolve data directory
    data_dir = gui_helpers._resolve_data_dir()
    
    # Create and run application
    app = PigeMainWindow(data_dir)
    app.mainloop()
    
    return 0
