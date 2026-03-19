"""Browse panel - Combined projects and entries view with synchronization."""

import logging
import tkinter as tk
from tkinter import ttk

from pige.core.service import PigeService
from pige.interfaces.gui.panels.entries_panel import EntriesPanel
from pige.interfaces.gui.panels.projects_panel import ProjectsPanel

logger = logging.getLogger(__name__)


class BrowsePanel(ttk.Frame):
    """Combined browse panel with projects hierarchy and entries list."""
    
    def __init__(
        self,
        parent: tk.Widget,
        service: PigeService,
        gui_prefs: dict,
        *,
        on_entries_mutated=None,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        self.gui_prefs = gui_prefs
        
        # Create horizontal splitter
        self.splitter = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.splitter.pack(fill=tk.BOTH, expand=True)
        
        # Left: Projects panel
        self.projects_panel = ProjectsPanel(
            self.splitter,
            self.service,
            initial_page_size=gui_prefs.get("pagination", {}).get("projects_page_size", 100)
        )
        self.splitter.add(self.projects_panel, weight=1)
        
        # Right: Entries panel
        self.entries_panel = EntriesPanel(
            self.splitter,
            self.service,
            initial_page_size=gui_prefs.get("pagination", {}).get("entries_page_size", 50),
            on_entries_mutated=on_entries_mutated,
        )
        self.splitter.add(self.entries_panel, weight=2)
        
        # Bind project selection to filter entries
        self.projects_panel.tree.bind("<<TreeviewSelect>>", self._on_project_selected)
    
    def _on_project_selected(self, event=None) -> None:
        """Handle project selection - filter entries."""
        selection = self.projects_panel.tree.selection()
        if not selection:
            return
        
        project_id = selection[0]
        
        # Get project
        project = self.projects_panel._projects_by_id.get(project_id)
        if not project:
            return
        
        # Filter entries panel by project name
        self.entries_panel.project_var.set(project.name)
        self.entries_panel._apply_filters()
    
    def refresh(self) -> None:
        """Refresh both panels."""
        self.projects_panel.refresh()
        self.entries_panel.refresh()
    
    def get_projects_page_size(self) -> int:
        """Get projects page size for preference saving."""
        return self.projects_panel.get_page_size()
    
    def get_entries_page_size(self) -> int:
        """Get entries page size for preference saving."""
        return self.entries_panel.get_page_size()
