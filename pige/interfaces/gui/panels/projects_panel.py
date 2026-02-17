"""Projects panel for PIGE GUI.

This panel displays the list of projects in a TreeView with hierarchical support.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pige.core.models import Project
    from pige.core.service import PigeService

logger = logging.getLogger(__name__)


class ProjectsPanel(ttk.Frame):
    """Panel for displaying and managing projects."""
    
    def __init__(
        self,
        parent: tk.Widget,
        service: PigeService,
        **kwargs
    ) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        
        # Setup UI
        self._setup_toolbar()
        self._setup_tree()
        
        # Load initial data
        self.refresh()
    
    def _setup_toolbar(self) -> None:
        """Create the toolbar with actions."""
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar,
            text="New Project",
            command=self._on_new_project
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="Refresh",
            command=self.refresh
        ).pack(side=tk.LEFT, padx=2)
    
    def _setup_tree(self) -> None:
        """Create the projects TreeView."""
        # TreeView with scrollbar
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("name", "status", "tasks"),
            show="tree headings",
            yscrollcommand=scrollbar.set
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)
        
        # Configure columns
        self.tree.heading("name", text="Name")
        self.tree.heading("status", text="Status")
        self.tree.heading("tasks", text="Tasks")
        
        self.tree.column("#0", width=40, stretch=False)
        self.tree.column("name", width=200, stretch=True)
        self.tree.column("status", width=100, stretch=False)
        self.tree.column("tasks", width=80, stretch=False)
        
        # Bind events
        self.tree.bind("<Double-Button-1>", self._on_double_click)
    
    def refresh(self) -> None:
        """Refresh the projects list."""
        logger.debug("Refreshing projects panel")
        
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Load projects
        projects = self.service.list_projects(include_archived=False)
        
        # Build hierarchy
        projects_by_id = {p.id: p for p in projects}
        root_projects = [p for p in projects if p.parent_id is None]
        
        # Sort by display_order
        root_projects.sort(key=lambda p: p.display_order)
        
        # Insert projects recursively
        for project in root_projects:
            self._insert_project_recursive(project, "", projects_by_id)
    
    def _insert_project_recursive(
        self,
        project: Project,
        parent_iid: str,
        projects_by_id: dict[str, Project]
    ) -> None:
        """Insert a project and its children recursively."""
        # Count tasks
        tasks = self.service.list_tasks(project_id=project.id)
        tasks_open = len([t for t in tasks if t.status != "done"])
        tasks_total = len(tasks)
        tasks_str = f"{tasks_open}/{tasks_total}"
        
        # Insert this project
        iid = self.tree.insert(
            parent_iid,
            tk.END,
            iid=project.id,
            text="📁" if project.status == "active" else "📦",
            values=(project.name, project.status, tasks_str)
        )
        
        # Insert children
        children = [
            p for p in projects_by_id.values()
            if p.parent_id == project.id
        ]
        children.sort(key=lambda p: p.display_order)
        
        for child in children:
            self._insert_project_recursive(child, iid, projects_by_id)
    
    def _on_new_project(self) -> None:
        """Handle New Project button."""
        logger.info("New Project requested from panel")
        # TODO: Open new project dialog
    
    def _on_double_click(self, event: tk.Event) -> None:
        """Handle double-click on project."""
        selection = self.tree.selection()
        if not selection:
            return
        
        project_id = selection[0]
        logger.info(f"Project double-clicked: {project_id}")
        # TODO: Open project details or trigger callback
