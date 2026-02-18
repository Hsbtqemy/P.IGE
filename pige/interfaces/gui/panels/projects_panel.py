"""Projects panel for PIGE GUI.

This panel displays the list of projects in a TreeView with hierarchical support,
pagination, and incremental updates for smooth UX.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from pige.interfaces.gui.pagination import PaginationControl, PaginationState
from pige.interfaces.gui.tree_diff import IncrementalTreeView, TreeNode, tree_from_items

if TYPE_CHECKING:
    from pige.core.models import Project
    from pige.core.service import PigeService

logger = logging.getLogger(__name__)


class ProjectsPanel(ttk.Frame):
    """Panel for displaying and managing projects with pagination and smooth updates."""
    
    def __init__(
        self,
        parent: tk.Widget,
        service: PigeService,
        initial_page_size: int = 100,
        **kwargs
    ) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        self.initial_page_size = initial_page_size
        
        # All projects cache (for pagination)
        self._all_root_projects: list[Project] = []
        self._projects_by_id: dict[str, Project] = {}
        
        # Sorting state
        self._sort_column: str = "name"
        self._sort_reverse: bool = False
        
        # Setup UI
        self._setup_toolbar()
        self._setup_tree()
        self._setup_pagination()
        
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
            columns=("name", "status", "tasks", "modified"),
            show="tree headings",
            yscrollcommand=scrollbar.set
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)
        
        # Configure columns
        self.tree.heading("name", text="Name", command=lambda: self._sort_by_column("name"))
        self.tree.heading("status", text="Status", command=lambda: self._sort_by_column("status"))
        self.tree.heading("tasks", text="Tasks", command=lambda: self._sort_by_column("tasks"))
        self.tree.heading("modified", text="Last Modified", command=lambda: self._sort_by_column("modified"))
        
        self.tree.column("#0", width=40, stretch=False)
        self.tree.column("name", width=200, stretch=True)
        self.tree.column("status", width=100, stretch=False)
        self.tree.column("tasks", width=80, stretch=False)
        self.tree.column("modified", width=150, stretch=False)
        
        # Bind events
        self.tree.bind("<Double-Button-1>", self._on_double_click)
        
        # Setup incremental tree for smooth updates
        self.incremental_tree = IncrementalTreeView(self.tree)
    
    def _setup_pagination(self) -> None:
        """Create pagination controls."""
        self.pagination = PaginationControl(
            self,
            on_page_change=self._on_page_change,
            initial_page_size=self.initial_page_size,
            show_all_option=True
        )
        self.pagination.pack(fill=tk.X, pady=(5, 0))
    
    def refresh(self) -> None:
        """Refresh the projects list with pagination."""
        logger.debug("Refreshing projects panel")
        
        # Load all projects (active only by default)
        projects = self.service.list_projects(status="active")
        self._projects_by_id = {p.id: p for p in projects}
        
        # Get root projects only for pagination
        self._all_root_projects = [p for p in projects if p.parent_id is None]
        
        # Apply current sort
        self._apply_sort()
        
        # Update pagination total
        self.pagination.set_total_items(len(self._all_root_projects))
        
        # Display current page
        self._refresh_current_page()
    
    def _sort_by_column(self, column: str) -> None:
        """Sort projects by column."""
        if self._sort_column == column:
            # Toggle direction
            self._sort_reverse = not self._sort_reverse
        else:
            # New column, default ascending
            self._sort_column = column
            self._sort_reverse = False
        
        self._apply_sort()
        self._refresh_current_page()
    
    def _apply_sort(self) -> None:
        """Apply current sort to root projects list."""
        if self._sort_column == "name":
            self._all_root_projects.sort(key=lambda p: p.name.lower(), reverse=self._sort_reverse)
        elif self._sort_column == "status":
            self._all_root_projects.sort(key=lambda p: p.status, reverse=self._sort_reverse)
        elif self._sort_column == "tasks":
            # Sort by task count
            def task_count(p):
                tasks = self.service.list_tasks(project_id=p.id, status="all")
                return len([t for t in tasks if t.status != "done"])
            self._all_root_projects.sort(key=task_count, reverse=self._sort_reverse)
        elif self._sort_column == "modified":
            self._all_root_projects.sort(key=lambda p: p.updated_at or p.created_at, reverse=self._sort_reverse)
    
    def _on_page_change(self, state: PaginationState) -> None:
        """Handle pagination page change."""
        logger.debug(f"Page changed to {state.page}/{state.total_pages} (page_size={state.page_size})")
        self._refresh_current_page()
        
        # Notify parent of page size change (for saving prefs)
        self.event_generate("<<PaginationChanged>>")
    
    def get_page_size(self) -> int:
        """Get current pagination page size."""
        return self.pagination.state.page_size
    
    def _refresh_current_page(self) -> None:
        """Refresh only the current page of projects."""
        # Get current page slice
        start_idx = self.pagination.state.start_index
        end_idx = self.pagination.state.end_index
        page_projects = self._all_root_projects[start_idx:end_idx]
        
        # Build tree nodes for this page (including children)
        new_nodes: dict[str, TreeNode] = {}
        for project in page_projects:
            self._build_tree_nodes_recursive(project, None, new_nodes)
        
        # Apply incremental update
        self.incremental_tree.apply_diff(new_nodes, preserve_selection=True, preserve_scroll=True)
    
    def _build_tree_nodes_recursive(
        self,
        project: Project,
        parent_id: str | None,
        nodes: dict[str, TreeNode]
    ) -> None:
        """Build TreeNode representation recursively."""
        # Count tasks
        tasks = self.service.list_tasks(project_id=project.id, status="all")
        tasks_open = len([t for t in tasks if t.status != "done"])
        tasks_total = len(tasks)
        tasks_str = f"{tasks_open}/{tasks_total}"
        
        # Format modified date
        modified_date = project.updated_at or project.created_at
        if modified_date:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(modified_date.replace('Z', '+00:00'))
                modified_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                modified_str = modified_date[:16]
        else:
            modified_str = "?"
        
        # Icon
        icon = "📁" if project.status == "active" else "📦"
        
        # Create node
        node = TreeNode(
            id=project.id,
            parent_id=parent_id,
            values=(project.name, project.status, tasks_str, modified_str),
            data=project,
            tags=(),
            open=False  # Could load from preferences later
        )
        nodes[project.id] = node
        
        # Add children recursively (children keep their display_order)
        children = [
            p for p in self._projects_by_id.values()
            if p.parent_id == project.id
        ]
        children.sort(key=lambda p: p.display_order)
        
        for child in children:
            self._build_tree_nodes_recursive(child, project.id, nodes)
    
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
