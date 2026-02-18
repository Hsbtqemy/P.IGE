"""Main window for PIGE GUI - Refactored modular version."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from pige.core.service import PigeService
from pige.core.storage import Storage
from pige.interfaces import gui_helpers
from pige.interfaces.gui.dialogs import show_about_dialog, show_keyboard_shortcuts
from pige.interfaces.gui.panels import ProjectsPanel, SearchPanel
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
            io_utils.write_json(self.prefs_path, prefs)
            return prefs
        return {}
    
    def _save_gui_prefs(self) -> None:
        """Save GUI preferences to disk."""
        io_utils.write_json(self.prefs_path, self.gui_prefs)
    
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
        
        # Tab 1: Projects (with pagination & incremental updates)
        self.projects_panel = ProjectsPanel(
            self.notebook,
            self.service,
            initial_page_size=self.gui_prefs.get("pagination", {}).get("projects_page_size", 100)
        )
        self.notebook.add(self.projects_panel, text="Projects")
        
        # Tab 2: Search
        self.search_panel = SearchPanel(
            self.notebook,
            self.service,
            on_result_selected=self._on_search_result_selected
        )
        self.notebook.add(self.search_panel, text="Search")
        
        # Tab 3: Placeholder for other panels
        placeholder_frame = ttk.Frame(self.notebook)
        self.notebook.add(placeholder_frame, text="Entries")
        
        placeholder_label = ttk.Label(
            placeholder_frame,
            text="Entries panel will be added here.",
            font=("TkDefaultFont", 12),
            justify=tk.CENTER
        )
        placeholder_label.pack(expand=True)
    
    def _setup_keybindings(self) -> None:
        """Setup keyboard shortcuts."""
        # File operations (bind for both Control and Command for cross-platform)
        self.bind_all("<Control-n>", lambda e: self._on_new_project())
        self.bind_all("<Command-n>", lambda e: self._on_new_project())
        self.bind_all("<Control-e>", lambda e: self._on_new_entry())
        self.bind_all("<Command-e>", lambda e: self._on_new_entry())
        self.bind_all("<Control-q>", lambda e: self.quit())
        self.bind_all("<Command-q>", lambda e: self.quit())
        
        # Search
        self.bind_all("<Control-f>", lambda e: self._on_search())
        self.bind_all("<Command-f>", lambda e: self._on_search())
        
        # Help
        self.bind_all("<F1>", lambda e: self._show_keyboard_shortcuts())
    
    # ===== Menu actions =====
    
    def _on_new_project(self) -> None:
        """Handle New Project action."""
        logger.info("New Project action triggered")
        # TODO: Open new project dialog
    
    def _on_new_entry(self) -> None:
        """Handle New Entry action."""
        logger.info("New Entry action triggered")
        # TODO: Open new entry dialog
    
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
        # TODO: Navigate to the selected item in appropriate panel
        # For now, just log it
    
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
        
        self.gui_prefs["pagination"]["projects_page_size"] = self.projects_panel.get_page_size()
        
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
