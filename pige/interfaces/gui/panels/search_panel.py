"""Search panel for PIGE GUI with FTS5 full-text search.

This panel provides a search interface for entries, projects, and tasks
using the SQLite FTS5 indexing engine.
"""

from __future__ import annotations

import logging
import time
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from pige.core.service import PigeService

logger = logging.getLogger(__name__)


class SearchPanel(ttk.Frame):
    """Panel for full-text search across entries, projects, and tasks."""
    
    SEARCH_TYPES = ["All", "Entries", "Projects", "Tasks"]
    
    def __init__(
        self,
        parent: tk.Widget,
        service: PigeService,
        on_result_selected: Callable[[str, str], None] | None = None,
        **kwargs
    ) -> None:
        """Initialize search panel.
        
        Args:
            parent: Parent widget
            service: PIGE service instance
            on_result_selected: Callback when result is selected (type, id)
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)
        self.service = service
        self.on_result_selected = on_result_selected
        
        # Search state
        self.current_results: list[tuple[str, str, str]] = []  # (type, id, display)
        
        # Setup UI
        self._setup_search_bar()
        self._setup_results_tree()
        self._setup_status_bar()
        
        logger.debug("SearchPanel initialized")
    
    def _setup_search_bar(self) -> None:
        """Create the search bar with input and controls."""
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Search type dropdown
        ttk.Label(search_frame, text="Search in:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.search_type_var = tk.StringVar(value="All")
        search_type_combo = ttk.Combobox(
            search_frame,
            textvariable=self.search_type_var,
            values=self.SEARCH_TYPES,
            state="readonly",
            width=10
        )
        search_type_combo.pack(side=tk.LEFT, padx=(0, 10))
        
        # Search input
        ttk.Label(search_frame, text="Query:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(
            search_frame,
            textvariable=self.search_var,
            width=40
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # Bind Enter key
        self.search_entry.bind("<Return>", lambda e: self.perform_search())
        
        # Search button
        ttk.Button(
            search_frame,
            text="Search",
            command=self.perform_search
        ).pack(side=tk.LEFT, padx=2)
        
        # Clear button
        ttk.Button(
            search_frame,
            text="Clear",
            command=self.clear_search
        ).pack(side=tk.LEFT, padx=2)
    
    def _setup_results_tree(self) -> None:
        """Create the results TreeView."""
        results_frame = ttk.Frame(self)
        results_frame.pack(fill=tk.BOTH, expand=True)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # TreeView
        self.results_tree = ttk.Treeview(
            results_frame,
            columns=("type", "title", "context"),
            show="headings",
            yscrollcommand=scrollbar.set
        )
        self.results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.results_tree.yview)
        
        # Configure columns
        self.results_tree.heading("type", text="Type", command=lambda: self._sort_results_tree("type"))
        self.results_tree.heading("title", text="Title", command=lambda: self._sort_results_tree("title"))
        self.results_tree.heading("context", text="Context", command=lambda: self._sort_results_tree("context"))
        
        self.results_tree.column("type", width=80, stretch=False)
        self.results_tree.column("title", width=250, stretch=True)
        self.results_tree.column("context", width=300, stretch=True)
        
        # Bind events
        self.results_tree.bind("<Double-Button-1>", self._on_result_double_click)
        self.results_tree.bind("<Return>", self._on_result_double_click)

    def _sort_results_tree(self, column_id: str) -> None:
        """Sort results tree by column; keep current_results in sync for double-click."""
        cols = ("type", "title", "context")
        if column_id not in cols:
            return
        if not hasattr(self, "_results_sort_col"):
            self._results_sort_col = None
            self._results_sort_reverse = False
        if self._results_sort_col == column_id:
            self._results_sort_reverse = not self._results_sort_reverse
        else:
            self._results_sort_col = column_id
            self._results_sort_reverse = False
        col_idx = cols.index(column_id)
        children = self.results_tree.get_children("")
        if not children or len(self.current_results) != len(children):
            return
        items = [(i, iid, self.results_tree.item(iid, "values")) for i, iid in enumerate(children)]
        def sort_key(x):
            idx, iid, vals = x
            if col_idx >= len(vals):
                return ""
            return (vals[col_idx] or "").strip().lower()
        items.sort(key=sort_key, reverse=self._results_sort_reverse)
        for iid in children:
            self.results_tree.delete(iid)
        new_results = [self.current_results[idx] for idx, iid, vals in items]
        self.current_results[:] = new_results
        for idx, iid, vals in items:
            self.results_tree.insert("", tk.END, values=vals)
    
    def _setup_status_bar(self) -> None:
        """Create the status bar."""
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.status_label = ttk.Label(
            status_frame,
            text="Enter a search query to find entries, projects, or tasks.",
            foreground="gray"
        )
        self.status_label.pack(side=tk.LEFT)
    
    def perform_search(self) -> None:
        """Perform the search based on current query and type."""
        query = self.search_var.get().strip()
        
        if not query:
            self.status_label.config(
                text="Please enter a search query.",
                foreground="orange"
            )
            return
        
        search_type = self.search_type_var.get()
        
        # Clear previous results
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self.current_results.clear()
        
        # Update status
        self.status_label.config(
            text=f"Searching for '{query}' in {search_type}...",
            foreground="blue"
        )
        self.update_idletasks()
        
        # Perform search
        start_time = time.time()
        
        try:
            with self.service.storage._get_search_index() as idx:
                if search_type in ("All", "Entries"):
                    entry_ids = idx.search_entries(query)
                    self._add_entry_results(entry_ids)
                
                if search_type in ("All", "Projects"):
                    project_ids = idx.search_projects(query)
                    self._add_project_results(project_ids)
                
                if search_type in ("All", "Tasks"):
                    task_ids = idx.search_tasks(query)
                    self._add_task_results(task_ids)
        
        except Exception as e:
            logger.error(f"Search failed: {e}", exc_info=True)
            self.status_label.config(
                text=f"Search error: {str(e)}",
                foreground="red"
            )
            return
        
        # Update status
        elapsed = (time.time() - start_time) * 1000  # Convert to ms
        total_results = len(self.current_results)
        
        if total_results == 0:
            self.status_label.config(
                text=f"No results found for '{query}' ({elapsed:.1f}ms)",
                foreground="orange"
            )
        else:
            self.status_label.config(
                text=f"Found {total_results} result(s) in {elapsed:.1f}ms",
                foreground="green"
            )
        
        logger.info(f"Search '{query}' found {total_results} results in {elapsed:.1f}ms")
    
    def _add_entry_results(self, entry_ids: list[str]) -> None:
        """Add entry results to the TreeView."""
        entries = self.service.storage.read_entries_meta()
        entries_by_id = {e.id: e for e in entries}
        
        for entry_id in entry_ids:
            entry = entries_by_id.get(entry_id)
            if entry is None:
                continue
            
            # Get project name for context
            try:
                project = self.service.get_project(entry.project_id)
                context = f"Project: {project.name}"
            except Exception:
                context = f"Project ID: {entry.project_id}"
            
            # Add tags to context if present
            if entry.tags:
                context += f" | Tags: {', '.join(entry.tags)}"
            
            # Insert into tree
            self.results_tree.insert(
                "",
                tk.END,
                values=("Entry", entry.title, context)
            )
            
            # Store for callback
            self.current_results.append(("entry", entry_id, entry.title))
    
    def _add_project_results(self, project_ids: list[str]) -> None:
        """Add project results to the TreeView."""
        projects = self.service.list_projects(status="all")
        projects_by_id = {p.id: p for p in projects}
        
        for project_id in project_ids:
            project = projects_by_id.get(project_id)
            if project is None:
                continue
            
            # Build context
            context = f"Status: {project.status}"
            
            # Add parent info if present
            if project.parent_id:
                parent = projects_by_id.get(project.parent_id)
                if parent:
                    context += f" | Parent: {parent.name}"
            
            # Insert into tree
            self.results_tree.insert(
                "",
                tk.END,
                values=("Project", project.name, context)
            )
            
            # Store for callback
            self.current_results.append(("project", project_id, project.name))
    
    def _add_task_results(self, task_ids: list[str]) -> None:
        """Add task results to the TreeView."""
        # Get all tasks from all projects
        projects = self.service.list_projects(status="all")
        projects_by_id = {p.id: p for p in projects}
        
        all_tasks = []
        for project in projects:
            tasks = self.service.list_tasks(project_id=project.id, status="all")
            all_tasks.extend(tasks)
        
        tasks_by_id = {t.id: t for t in all_tasks}
        
        for task_id in task_ids:
            task = tasks_by_id.get(task_id)
            if task is None:
                continue
            
            # Build context
            project = projects_by_id.get(task.project_id)
            context = f"Project: {project.name if project else task.project_id}"
            context += f" | Status: {task.status}"
            
            # Insert into tree
            self.results_tree.insert(
                "",
                tk.END,
                values=("Task", task.title, context)
            )
            
            # Store for callback
            self.current_results.append(("task", task_id, task.title))
    
    def clear_search(self) -> None:
        """Clear the search query and results."""
        self.search_var.set("")
        
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        
        self.current_results.clear()
        
        self.status_label.config(
            text="Search cleared. Enter a new query.",
            foreground="gray"
        )
        
        self.search_entry.focus_set()
    
    def _on_result_double_click(self, event: tk.Event | None = None) -> None:
        """Handle double-click or Enter on result."""
        selection = self.results_tree.selection()
        if not selection:
            return
        
        # Get the index of the selected item
        item_id = selection[0]
        item_index = self.results_tree.index(item_id)
        
        if item_index >= len(self.current_results):
            logger.warning(f"Invalid result index: {item_index}")
            return
        
        result_type, result_id, result_title = self.current_results[item_index]
        
        logger.info(f"Result selected: {result_type} - {result_title} ({result_id})")
        
        # Call callback if provided
        if self.on_result_selected:
            self.on_result_selected(result_type, result_id)
        else:
            # Default: show info message
            self.status_label.config(
                text=f"Selected: {result_type} - {result_title}",
                foreground="blue"
            )
    
    def focus_search(self) -> None:
        """Focus the search input field."""
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)
