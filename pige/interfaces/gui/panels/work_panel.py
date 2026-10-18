"""Work panel - Focus mode for daily journaling and task management."""

import logging
import tkinter as tk
from dataclasses import replace
from datetime import date, datetime
from tkinter import ttk, messagebox

from pige.core.exceptions import ProjectNotFoundError
from pige.core.service import PigeService
from pige.interfaces.gui.dialogs import (
    show_edit_task_dialog,
    show_export_hierarchy_dialog,
    show_export_meeting_minutes_dialog,
    show_export_project_narrative_dialog,
    show_export_project_raw_dialog,
    show_export_weekly_summary_dialog,
    show_followup_tasks_dialog,
    show_new_entry_dialog,
    show_new_project_dialog,
    show_new_task_dialog,
)
from pige.interfaces.gui_constants import AUTOSAVE_DELAY_MS
from pige.interfaces.gui_helpers import format_date_ui, parse_date_ui

logger = logging.getLogger(__name__)


class WorkPanel(ttk.Frame):
    """Work panel for focused daily work - journaling, tasks, and time tracking."""
    
    def __init__(self, parent: tk.Widget, service: PigeService, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        
        # State
        self.current_project_id: str | None = None
        self._projects_by_id: dict = {}
        self._autosave_after_id: str | None = None
        
        # Setup UI with 3-pane layout
        self._setup_timer_display()
        
        # Main horizontal splitter: Explorer | Editor+Tasks
        self.main_splitter = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_splitter.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Left pane: Project/Entry explorer
        self._setup_explorer()
        
        # Right pane: Editor + Tasks (vertical splitter)
        right_frame = ttk.Frame(self.main_splitter)
        self.main_splitter.add(right_frame, weight=3)
        
        self.right_splitter = ttk.PanedWindow(right_frame, orient=tk.VERTICAL)
        self.right_splitter.pack(fill=tk.BOTH, expand=True)
        
        # Right top: container for Entry editor OR Project details (one visible at a time)
        self._right_top_container = ttk.Frame(self.right_splitter)
        self.right_splitter.add(self._right_top_container, weight=3)
        self._setup_editor()
        self._setup_project_details_panel()
        self._show_editor_panel()  # Editor visible by default
        
        # Right bottom: Tasks
        self._setup_tasks_section()
        
        # Load initial data
        self.refresh()
    
    def _setup_timer_display(self) -> None:
        """Setup timer display and controls."""
        timer_frame = ttk.LabelFrame(self, text="⏱️ Timer", padding=10)
        timer_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Timer display
        self.timer_var = tk.StringVar(value="Aucun timer actif")
        timer_label = ttk.Label(
            timer_frame,
            textvariable=self.timer_var,
            font=("TkDefaultFont", 11)
        )
        timer_label.pack(side=tk.LEFT, padx=(0, 20))
        
        # Timer buttons
        self.btn_start_timer = ttk.Button(
            timer_frame,
            text="▶ Start",
            command=self._on_start_timer,
            width=10
        )
        self.btn_start_timer.pack(side=tk.LEFT, padx=2)
        
        self.btn_stop_timer = ttk.Button(
            timer_frame,
            text="⏹ Stop",
            command=self._on_stop_timer,
            state=tk.DISABLED,
            width=10
        )
        self.btn_stop_timer.pack(side=tk.LEFT, padx=2)
        
        # Temps du jour (time tracked today per project)
        self.time_today_var = tk.StringVar(value="")
        time_today_label = ttk.Label(timer_frame, textvariable=self.time_today_var, font=("TkDefaultFont", 9))
        time_today_label.pack(side=tk.LEFT, padx=(20, 0))
        
        # Journal du jour : entrées dont le champ technique `ts` tombe dans la journée locale
        # (voir PigeService.log_today — ce n’est pas filtré sur la « date de journal » entry_date).
        journal_frame = ttk.LabelFrame(self, text="📋 Journal du jour", padding=5)
        journal_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Label(
            journal_frame,
            text=(
                "Liste des entrées enregistrées aujourd’hui (fuseau local), "
                "selon l’horodatage de création / mise à jour — pas selon la date affichée sur l’entrée. "
                "Double-clic : ouvrir dans l’éditeur."
            ),
            font=("TkDefaultFont", 8),
            foreground="gray",
            wraplength=920,
        ).pack(anchor=tk.W, pady=(0, 4))
        journal_row = ttk.Frame(journal_frame)
        journal_row.pack(fill=tk.BOTH, expand=True)
        self.journal_listbox = tk.Listbox(
            journal_row,
            height=4,
            font=("TkDefaultFont", 9),
            selectmode=tk.SINGLE,
            activestyle="none",
        )
        journal_scroll = ttk.Scrollbar(journal_row, orient=tk.VERTICAL, command=self.journal_listbox.yview)
        self.journal_listbox.configure(yscrollcommand=journal_scroll.set)
        self.journal_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        journal_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.journal_listbox.bind("<Double-1>", self._on_journal_entry_double_click)
        self._journal_items: list[str] = []  # entry_id for each index
    
    def _setup_explorer(self) -> None:
        """Setup project/entry explorer tree."""
        explorer_frame = ttk.LabelFrame(self.main_splitter, text="📂 Projets & Entries", padding=5)
        self.main_splitter.add(explorer_frame, weight=1)
        
        # Toolbar
        toolbar = ttk.Frame(explorer_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar,
            text="🔄",
            width=3,
            command=self.refresh
        ).pack(side=tk.LEFT)
        
        ttk.Button(
            toolbar,
            text="📂 Projet",
            command=self._on_new_project
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(
            toolbar,
            text="➕ Entry",
            command=self._on_new_entry_from_explorer
        ).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Button(
            toolbar,
            text="Expand all",
            command=self._explorer_expand_all
        ).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Button(
            toolbar,
            text="Collapse all",
            command=self._explorer_collapse_all
        ).pack(side=tk.LEFT, padx=(5, 0))

        self._show_archived_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            toolbar,
            text="Afficher les archives",
            variable=self._show_archived_var,
            command=self.refresh,
        ).pack(side=tk.LEFT, padx=(15, 0))

        # Tree
        tree_frame = ttk.Frame(explorer_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.explorer_tree = ttk.Treeview(
            tree_frame,
            yscrollcommand=scrollbar.set,
            selectmode="browse"
        )
        self.explorer_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.explorer_tree.yview)
        
        # Configure tree appearance
        self.explorer_tree.heading("#0", text="Navigation")
        
        # Bind events
        self.explorer_tree.bind("<<TreeviewSelect>>", self._on_explorer_select)
        self.explorer_tree.bind("<Button-3>", self._on_explorer_right_click)  # Right-click
        
        # Drag & drop support (basic)
        self.explorer_tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.explorer_tree.bind("<B1-Motion>", self._on_drag_motion)
        self.explorer_tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self._drag_data = {"item": None, "x": 0, "y": 0}

    def _setup_project_details_panel(self) -> None:
        """Setup project details / notes panel (replaces Entry editor when a project is selected)."""
        self._project_details_frame = ttk.LabelFrame(
            self._right_top_container,
            text="📋 Détails projet / Notes d'intention",
            padding=10,
        )
        self._project_details_project_id: str | None = None
        # Name
        ttk.Label(self._project_details_frame, text="Nom:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=4)
        self._project_details_name_var = tk.StringVar(value="")
        ttk.Entry(self._project_details_frame, textvariable=self._project_details_name_var, width=45).grid(
            row=0, column=1, sticky=tk.EW, padx=5, pady=4
        )
        # Description / Notes d'intention
        ttk.Label(self._project_details_frame, text="Notes d'intention / Description:").grid(
            row=1, column=0, sticky=tk.NW, padx=5, pady=4
        )
        self._project_details_text = tk.Text(self._project_details_frame, height=6, width=50, wrap=tk.WORD)
        self._project_details_text.grid(row=1, column=1, sticky=tk.NSEW, padx=5, pady=4)
        # Tags
        ttk.Label(self._project_details_frame, text="Tags:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=4)
        self._project_details_tags_var = tk.StringVar(value="")
        ttk.Entry(self._project_details_frame, textvariable=self._project_details_tags_var, width=45).grid(
            row=2, column=1, sticky=tk.EW, padx=5, pady=4
        )
        # People
        ttk.Label(self._project_details_frame, text="Personnes (une par ligne):").grid(
            row=3, column=0, sticky=tk.NW, padx=5, pady=4
        )
        self._project_details_people_text = tk.Text(self._project_details_frame, height=3, width=50, wrap=tk.WORD)
        self._project_details_people_text.grid(row=3, column=1, sticky=tk.EW, padx=5, pady=4)
        # Group
        ttk.Label(self._project_details_frame, text="Groupe:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=4)
        self._project_details_group_var = tk.StringVar(value="")
        ttk.Entry(self._project_details_frame, textvariable=self._project_details_group_var, width=45).grid(
            row=4, column=1, sticky=tk.EW, padx=5, pady=4
        )
        # Status & Priority
        ttk.Label(self._project_details_frame, text="Statut:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=4)
        self._project_details_status_var = tk.StringVar(value="active")
        ttk.Combobox(
            self._project_details_frame,
            textvariable=self._project_details_status_var,
            values=["active", "archived"],
            state="readonly",
            width=12,
        ).grid(row=5, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(self._project_details_frame, text="Priorité (1=haute, 5=basse):").grid(
            row=6, column=0, sticky=tk.W, padx=5, pady=4
        )
        self._project_details_priority_var = tk.IntVar(value=3)
        ttk.Spinbox(
            self._project_details_frame,
            from_=1,
            to=5,
            width=5,
            textvariable=self._project_details_priority_var,
        ).grid(row=6, column=1, sticky=tk.W, padx=5, pady=4)
        # Save button
        btn_frame = ttk.Frame(self._project_details_frame)
        btn_frame.grid(row=7, column=0, columnspan=2, pady=10)
        ttk.Button(
            btn_frame,
            text="💾 Enregistrer le projet",
            command=self._on_save_project_from_panel,
        ).pack(side=tk.LEFT)
        self._project_details_frame.columnconfigure(1, weight=1)
        self._project_details_frame.rowconfigure(1, weight=1)

    def _show_editor_panel(self) -> None:
        """Show Entry editor, hide Project details."""
        self._project_details_frame.pack_forget()
        self.editor_frame.pack(fill=tk.BOTH, expand=True)

    def _show_project_details_panel(self) -> None:
        """Show Project details panel, hide Entry editor."""
        self.editor_frame.pack_forget()
        self._project_details_frame.pack(fill=tk.BOTH, expand=True)

    def _explorer_set_open_recursive(self, parent_iid: str, open_state: bool) -> None:
        """Set open state for a node and all its descendants in the explorer tree."""
        for iid in self.explorer_tree.get_children(parent_iid):
            self.explorer_tree.item(iid, open=open_state)
            self._explorer_set_open_recursive(iid, open_state)

    def _explorer_expand_all(self) -> None:
        """Expand all nodes in the explorer tree."""
        self._explorer_set_open_recursive("", True)

    def _explorer_collapse_all(self) -> None:
        """Collapse all nodes in the explorer tree."""
        self._explorer_set_open_recursive("", False)

    def _setup_editor(self) -> None:
        """Setup markdown editor (lives in right-top container, shown when entry selected)."""
        self.editor_frame = ttk.LabelFrame(self._right_top_container, text="✍️ Entry Editor", padding=10)
        
        # Top toolbar: Type, Title, Entry selector
        top_row = ttk.Frame(self.editor_frame)
        top_row.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(top_row, text="Type:").pack(side=tk.LEFT)
        self.entry_type_var = tk.StringVar(value="note")
        type_combo = ttk.Combobox(
            top_row,
            textvariable=self.entry_type_var,
            values=["note", "meeting", "decision", "activity"],
            state="readonly",
            width=12
        )
        type_combo.pack(side=tk.LEFT, padx=(5, 20))
        type_combo.bind("<<ComboboxSelected>>", self._on_entry_type_changed)
        
        ttk.Label(top_row, text="Titre:").pack(side=tk.LEFT)
        self.entry_title_var = tk.StringVar()
        title_entry = ttk.Entry(top_row, textvariable=self.entry_title_var, width=40)
        title_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Current entry indicator
        self.current_entry_var = tk.StringVar(value="Nouvelle entry")
        ttk.Label(
            top_row,
            textvariable=self.current_entry_var,
            font=("TkDefaultFont", 9),
            foreground="gray"
        ).pack(side=tk.LEFT, padx=(10, 0))
        
        # Metadata panel (Date, People, Groups, Tags)
        meta_frame = ttk.LabelFrame(self.editor_frame, text="Métadonnées", padding=5)
        meta_frame.pack(fill=tk.X, pady=(5, 0))
        
        # Row 1: Date and People
        meta_row1 = ttk.Frame(meta_frame)
        meta_row1.pack(fill=tk.X, pady=2)
        
        ttk.Label(meta_row1, text="Date:", width=10).pack(side=tk.LEFT)
        self.entry_date_var = tk.StringVar()
        ttk.Entry(meta_row1, textvariable=self.entry_date_var, width=12).pack(side=tk.LEFT, padx=(0, 20))
        
        ttk.Label(meta_row1, text="People:", width=10).pack(side=tk.LEFT)
        self.entry_people_var = tk.StringVar()
        ttk.Entry(meta_row1, textvariable=self.entry_people_var, width=40).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Row 2: Groups and Tags
        meta_row2 = ttk.Frame(meta_frame)
        meta_row2.pack(fill=tk.X, pady=2)
        
        ttk.Label(meta_row2, text="Groups:", width=10).pack(side=tk.LEFT)
        self.entry_groups_var = tk.StringVar()
        ttk.Entry(meta_row2, textvariable=self.entry_groups_var, width=20).pack(side=tk.LEFT, padx=(0, 20))
        
        ttk.Label(meta_row2, text="Tags:", width=10).pack(side=tk.LEFT)
        self.entry_tags_var = tk.StringVar()
        ttk.Entry(meta_row2, textvariable=self.entry_tags_var, width=40).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Row 3: Status
        meta_row3 = ttk.Frame(meta_frame)
        meta_row3.pack(fill=tk.X, pady=2)
        
        ttk.Label(meta_row3, text="Statut:", width=10).pack(side=tk.LEFT)
        self.entry_status_var = tk.StringVar()
        status_combo = ttk.Combobox(
            meta_row3,
            textvariable=self.entry_status_var,
            values=["", "actual", "pending", "closed", "waiting", "blocked"],
            width=15
        )
        status_combo.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(meta_row3, text="Prio:").pack(side=tk.LEFT)
        self.entry_priority_var = tk.IntVar(value=3)
        priority_spin = ttk.Spinbox(meta_row3, from_=1, to=5, width=4, textvariable=self.entry_priority_var)
        priority_spin.pack(side=tk.LEFT)

        # Réunion : heures (affichées seulement si type = meeting)
        self._meeting_meta_frame = ttk.Frame(meta_frame)
        self.entry_start_var = tk.StringVar()
        self.entry_end_var = tk.StringVar()
        ttk.Label(self._meeting_meta_frame, text="Début (HH:MM):", width=14).pack(
            side=tk.LEFT
        )
        ttk.Entry(self._meeting_meta_frame, textvariable=self.entry_start_var, width=8).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        ttk.Label(self._meeting_meta_frame, text="Fin (HH:MM):", width=12).pack(side=tk.LEFT)
        ttk.Entry(self._meeting_meta_frame, textvariable=self.entry_end_var, width=8).pack(
            side=tk.LEFT
        )

        # Décision : statut appliqué (affiché seulement si type = decision)
        self._decision_meta_frame = ttk.Frame(meta_frame)
        self.entry_decision_done_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self._decision_meta_frame,
            text="Décision appliquée / faite",
            variable=self.entry_decision_done_var,
        ).pack(side=tk.LEFT)
        
        # Markdown editor
        ttk.Label(self.editor_frame, text="Contenu (Markdown):").pack(anchor=tk.W, pady=(5, 2))
        
        text_frame = ttk.Frame(self.editor_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Scrollbar for text editor
        text_scroll = ttk.Scrollbar(text_frame)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.entry_body_text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            yscrollcommand=text_scroll.set,
            undo=True,
            maxundo=-1
        )
        self.entry_body_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        text_scroll.config(command=self.entry_body_text.yview)
        
        # Track if content is modified
        self.entry_body_text.bind("<<Modified>>", self._on_content_modified)
        self._current_entry_id: str | None = None
        self._entry_modified = False
        
        # Buttons
        btn_row = ttk.Frame(self.editor_frame)
        btn_row.pack(fill=tk.X)
        
        self.btn_save = ttk.Button(
            btn_row,
            text="💾 Enregistrer",
            command=self._on_save_entry,
            state=tk.DISABLED
        )
        self.btn_save.pack(side=tk.LEFT)
        
        ttk.Button(
            btn_row,
            text="➕ Nouvelle",
            command=self._on_new_entry_editor
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(
            btn_row,
            text="🗑️ Supprimer",
            command=self._on_delete_current_entry
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(
            btn_row,
            text="📄 Ouvrir MD externe",
            command=self._on_open_external
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        self.btn_followup = ttk.Button(
            btn_row,
            text="✓ Créer tâches de suivi",
            command=self._on_create_followup_tasks,
            state=tk.DISABLED,
        )
        self.btn_followup.pack(side=tk.LEFT, padx=(5, 0))

        self._sync_entry_type_extra_widgets()
    
    def _sync_entry_type_extra_widgets(self) -> None:
        """Affiche les champs réunion / décision selon le type d'entrée."""
        entry_type = self.entry_type_var.get()
        if entry_type == "meeting":
            self._meeting_meta_frame.pack(fill=tk.X, pady=2)
            self._decision_meta_frame.pack_forget()
            self.entry_decision_done_var.set(False)
        elif entry_type == "decision":
            self._meeting_meta_frame.pack_forget()
            self.entry_start_var.set("")
            self.entry_end_var.set("")
            self._decision_meta_frame.pack(fill=tk.X, pady=2)
        else:
            self._meeting_meta_frame.pack_forget()
            self._decision_meta_frame.pack_forget()
            self.entry_start_var.set("")
            self.entry_end_var.set("")
            self.entry_decision_done_var.set(False)
    
    def _on_create_followup_tasks(self) -> None:
        """Open dialog to create tasks from ACTION/TODO lines in current entry."""
        if not self._current_entry_id:
            messagebox.showwarning("Attention", "Aucune entrée chargée.", parent=self.winfo_toplevel())
            return
        show_followup_tasks_dialog(
            self.winfo_toplevel(),
            self.service,
            self._current_entry_id,
            on_created=lambda _: self._refresh_tasks(),
        )
    
    def _setup_tasks_section(self) -> None:
        """Setup tasks list for active project."""
        tasks_frame = ttk.LabelFrame(self.right_splitter, text="✓ Tasks du Projet", padding=10)
        self.right_splitter.add(tasks_frame, weight=1)
        
        # Toolbar
        toolbar = ttk.Frame(tasks_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar,
            text="➕ Nouvelle Task",
            command=self._on_add_task
        ).pack(side=tk.LEFT)
        
        # Tasks tree
        tree_frame = ttk.Frame(tasks_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tasks_tree = ttk.Treeview(
            tree_frame,
            columns=("title", "status", "due"),
            show="tree headings",
            yscrollcommand=scrollbar.set,
            height=6
        )
        
        self.tasks_tree.heading("#0", text="✓")
        self.tasks_tree.heading("title", text="Titre", command=lambda: self._sort_tasks_tree("title"))
        self.tasks_tree.heading("status", text="Statut", command=lambda: self._sort_tasks_tree("status"))
        self.tasks_tree.heading("due", text="Échéance", command=lambda: self._sort_tasks_tree("due"))
        
        self.tasks_tree.column("#0", width=30, stretch=False)
        self.tasks_tree.column("title", width=300)
        self.tasks_tree.column("status", width=100)
        self.tasks_tree.column("due", width=100)
        
        self.tasks_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tasks_tree.yview)
        
        # Bind events
        self.tasks_tree.bind("<Double-Button-1>", self._on_task_double_click)
        self.tasks_tree.bind("<space>", self._on_task_toggle)
    
    
    def refresh(self) -> None:
        """Refresh all data."""
        logger.debug("Refreshing work panel")

        # Load projects; include archived only if checkbox is set
        status_filter = "all" if self._show_archived_var.get() else "active"
        projects = self.service.list_projects(status=status_filter)
        projects = [p for p in projects if "calendar-sync" not in (p.tags or [])]
        self._projects_by_id = {p.id: p for p in projects}
        
        # Refresh explorer tree
        self._refresh_explorer()
        
        # Refresh timer
        self._refresh_timer()
        
        # Refresh current project data
        if self.current_project_id:
            self._refresh_tasks()
    
    def _get_expanded_project_ids(self) -> set[str]:
        """Return set of expanded project node IDs (project:xxx) in the explorer tree."""
        expanded: set[str] = set()
        def walk(parent: str) -> None:
            for iid in self.explorer_tree.get_children(parent):
                if self.explorer_tree.item(iid, "open"):
                    expanded.add(iid)
                walk(iid)
        walk("")
        return expanded

    def _refresh_explorer(self) -> None:
        """Refresh the project/entry explorer tree with hierarchy."""
        # Remember which project nodes were expanded (so we don't expand all on every refresh)
        expanded_before = self._get_expanded_project_ids()
        # Clear tree
        for item in self.explorer_tree.get_children():
            self.explorer_tree.delete(item)
        
        # Get all entries
        all_entries = self.service.storage.read_entries_meta()
        entries_by_project: dict[str, list] = {}
        
        for entry in all_entries:
            if entry.project_id not in entries_by_project:
                entries_by_project[entry.project_id] = []
            entries_by_project[entry.project_id].append(entry)
        
        # Sort entries by date (newest first)
        for entries in entries_by_project.values():
            entries.sort(key=lambda e: e.entry_date or e.ts, reverse=True)
        
        # Build hierarchical tree: root projects first
        root_projects = [p for p in self._projects_by_id.values() if p.parent_id is None]
        root_projects.sort(key=lambda p: p.display_order)
        
        for project in root_projects:
            self._add_project_node_recursive(project, "", entries_by_project, expanded_before)
    
    def _add_project_node_recursive(
        self,
        project,
        parent_node: str,
        entries_by_project: dict,
        expanded_ids: set[str] | None = None,
    ) -> None:
        """Recursively add project and its children to the tree."""
        project_iid = f"project:{project.id}"
        if expanded_ids is not None:
            is_open = project_iid in expanded_ids
        else:
            is_open = parent_node == ""  # Root level expanded by default on first load
        # Add project node (preserve expand state; default collapsed when no prior state)
        project_text = f"📂 {project.name}"
        if project.status == "archived":
            project_text += " [Archivé]"
        
        project_node = self.explorer_tree.insert(
            parent_node,
            tk.END,
            iid=project_iid,
            text=project_text,
            open=is_open,
        )
        
        # Add entries for this project
        project_entries = entries_by_project.get(project.id, [])
        for entry in project_entries[:20]:  # Limit to 20 most recent
            entry_icon = {
                "note": "📝",
                "meeting": "🤝",
                "decision": "✅",
                "activity": "⚡"
            }.get(entry.type, "📄")
            
            entry_text = f"{entry_icon} {entry.title[:50]}"
            if entry.entry_date:
                entry_text += f" ({entry.entry_date})"
            
            self.explorer_tree.insert(
                project_node,
                tk.END,
                iid=f"entry:{entry.id}",
                text=entry_text
            )
        
        # Add child projects recursively
        children = [p for p in self._projects_by_id.values() if p.parent_id == project.id]
        children.sort(key=lambda p: p.display_order)
        
        for child in children:
            self._add_project_node_recursive(child, project_node, entries_by_project, expanded_ids)
    
    def _on_explorer_select(self, event=None) -> None:
        """Handle selection in explorer tree - load entry directly."""
        selection = self.explorer_tree.selection()
        if not selection:
            self._hide_project_details()
            return
        item_id = selection[0]
        
        if item_id.startswith("project:"):
            # Project selected
            project_id = item_id.replace("project:", "")
            self.current_project_id = project_id
            self._refresh_tasks()
            self._show_project_details(project_id)
            
        elif item_id.startswith("entry:"):
            # Entry selected - load immediately (no double-click needed)
            entry_id = item_id.replace("entry:", "")
            self._hide_project_details()
            self._load_entry_in_editor(entry_id)
            
            # Set current project
            entries = self.service.storage.read_entries_meta()
            entry = next((e for e in entries if e.id == entry_id), None)
            if entry:
                self.current_project_id = entry.project_id
                self._refresh_tasks()
    
    def _show_project_details(self, project_id: str) -> None:
        """Show project details panel in place of Entry editor and fill with project data."""
        project = self._projects_by_id.get(project_id)
        if not project:
            self._hide_project_details()
            return
        self._project_details_project_id = project_id
        self._project_details_name_var.set(project.name or "")
        self._project_details_text.delete("1.0", tk.END)
        self._project_details_text.insert("1.0", project.description or "")
        self._project_details_tags_var.set(", ".join(project.tags) if project.tags else "")
        self._project_details_people_text.delete("1.0", tk.END)
        self._project_details_people_text.insert("1.0", project.person or "")
        self._project_details_group_var.set(project.group or "")
        self._project_details_status_var.set(project.status)
        self._project_details_priority_var.set(getattr(project, "priority", 3))
        self._show_project_details_panel()
    
    def _hide_project_details(self) -> None:
        """Hide project details pane and show Entry editor."""
        self._project_details_project_id = None
        self._show_editor_panel()
    
    def _on_save_project_from_panel(self) -> None:
        """Save all project fields from the details panel."""
        if not self._project_details_project_id:
            return
        project = self._projects_by_id.get(self._project_details_project_id)
        if not project:
            return
        from pige.interfaces.gui_helpers import join_people_storage, split_people
        from pige.utils import strings
        name = self._project_details_name_var.get().strip()
        if not name:
            messagebox.showerror("Erreur", "Le nom du projet est requis.")
            return
        description = self._project_details_text.get("1.0", tk.END).strip() or None
        tags = strings.parse_tags(self._project_details_tags_var.get())
        people_raw = self._project_details_people_text.get("1.0", tk.END)
        person = join_people_storage(split_people(people_raw)) or None
        group = self._project_details_group_var.get().strip() or None
        status = self._project_details_status_var.get()
        if status not in ("active", "archived"):
            status = project.status
        try:
            prio = self._project_details_priority_var.get()
            if not (1 <= prio <= 5):
                prio = getattr(project, "priority", 3)
        except tk.TclError:
            prio = getattr(project, "priority", 3)
        try:
            self.service.update_project(
                self._project_details_project_id,
                name=name,
                description=description,
                tags=tags,
                person=person,
                group=group,
                status=status,
                priority=prio,
            )
            updated = replace(
                project,
                name=name,
                description=description,
                tags=tags,
                person=person,
                group=group,
                status=status,
                priority=prio,
            )
            self._projects_by_id[self._project_details_project_id] = updated
            messagebox.showinfo("Succès", "Projet enregistré.")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'enregistrer:\n{e}")
    
    def _on_explorer_right_click(self, event) -> None:
        """Show context menu on right-click."""
        # Select item under cursor
        item = self.explorer_tree.identify_row(event.y)
        
        # Create context menu
        menu = tk.Menu(self, tearoff=0)
        
        if not item:
            # Right-click on empty space
            menu.add_command(label="📂 Nouveau Projet", command=self._on_new_project)
            menu.add_command(label="🔄 Rafraîchir", command=self.refresh)
            menu.post(event.x_root, event.y_root)
            return
        
        self.explorer_tree.selection_set(item)
        
        if item.startswith("project:"):
            # Project context menu
            project_id = item.replace("project:", "")
            project = self._projects_by_id.get(project_id)
            menu.add_command(label="➕ Nouvelle Entry", command=lambda: self._on_new_entry_dialog(project_id))
            menu.add_command(label="➕ Nouvelle Task", command=self._on_add_task)
            menu.add_separator()
            menu.add_command(label="📂 Nouveau Sous-Projet", command=lambda: self._on_new_subproject(item))
            menu.add_separator()
            menu.add_command(label="⏱️ Start Timer", command=lambda: self._start_timer_for_project(item))
            menu.add_command(label="⏱ Ajouter du temps", command=lambda: self._add_manual_time_for_project(project_id))
            menu.add_separator()
            if project and project.status == "active":
                menu.add_command(label="📦 Archiver le projet", command=lambda: self._archive_project(project_id))
            elif project and project.status == "archived":
                menu.add_command(label="📂 Désarchiver le projet", command=lambda: self._unarchive_project(project_id))
            menu.add_separator()
            export_sub = tk.Menu(menu, tearoff=0)
            export_sub.add_command(
                label="Projet (brut)…",
                command=lambda: show_export_project_raw_dialog(self.winfo_toplevel(), self.service, project_id),
            )
            export_sub.add_command(
                label="Projet (narratif)…",
                command=lambda: show_export_project_narrative_dialog(self.winfo_toplevel(), self.service, project_id),
            )
            export_sub.add_command(
                label="Résumé hebdomadaire…",
                command=lambda: show_export_weekly_summary_dialog(self.winfo_toplevel(), self.service, project_id),
            )
            export_sub.add_command(
                label="Hiérarchie des projets…",
                command=lambda: show_export_hierarchy_dialog(self.winfo_toplevel(), self.service),
            )
            menu.add_cascade(label="Exporter…", menu=export_sub)
            menu.add_separator()
            menu.add_command(label="🗑️ Supprimer le projet", command=lambda: self._delete_project_from_explorer(project_id))
            menu.add_separator()
            menu.add_command(label="🔄 Rafraîchir", command=self.refresh)
            
        elif item.startswith("entry:"):
            # Entry context menu
            entry_id = item.replace("entry:", "")
            menu.add_command(label="✏️ Éditer", command=lambda: self._load_entry_in_editor(entry_id))
            menu.add_command(label="📄 Ouvrir MD externe", command=lambda: self._open_entry_external(entry_id))
            menu.add_separator()
            menu.add_command(
                label="Exporter compte-rendu de réunion…",
                command=lambda: show_export_meeting_minutes_dialog(self.winfo_toplevel(), self.service, entry_id),
            )
            menu.add_separator()
            menu.add_command(label="📋 Copier ID", command=lambda: self._copy_to_clipboard(entry_id))
            menu.add_separator()
            menu.add_command(label="🗑️ Supprimer", command=lambda: self._delete_entry_from_explorer(entry_id))
        
        menu.post(event.x_root, event.y_root)
    
    def _on_drag_start(self, event) -> None:
        """Start drag operation."""
        item = self.explorer_tree.identify_row(event.y)
        if item:
            self._drag_data["item"] = item
            self._drag_data["x"] = event.x
            self._drag_data["y"] = event.y
    
    def _on_drag_motion(self, event) -> None:
        """Handle drag motion (visual feedback)."""
        if self._drag_data["item"]:
            # Could add visual feedback here (e.g., change cursor)
            pass
    
    def _on_drag_release(self, event) -> None:
        """Handle drop operation."""
        if not self._drag_data["item"]:
            return
        
        # Get target item
        target = self.explorer_tree.identify_row(event.y)
        source = self._drag_data["item"]
        
        # Reset drag data
        self._drag_data["item"] = None
        
        if not target or source == target:
            return
        
        # Handle different drop scenarios
        if source.startswith("entry:") and target.startswith("project:"):
            # Move entry to different project
            entry_id = source.replace("entry:", "")
            target_project_id = target.replace("project:", "")
            self._move_entry_to_project(entry_id, target_project_id)
        
        elif source.startswith("project:") and target.startswith("project:"):
            source_project_id = source.replace("project:", "")
            target_project_id = target.replace("project:", "")
            source_project = self._projects_by_id.get(source_project_id)
            target_project = self._projects_by_id.get(target_project_id)
            if not source_project or not target_project:
                return
            # Same parent => reorder siblings; else => move under target
            if source_project.parent_id == target_project.parent_id:
                self._reorder_project_with_sibling(source_project_id, target_project_id, source_project.parent_id)
            else:
                self._move_project_under(source_project_id, target_project_id)
    
    def _start_timer_for_project(self, item_id: str) -> None:
        """Start timer for a project."""
        project_id = item_id.replace("project:", "")
        self.current_project_id = project_id
        self._on_start_timer()

    def _add_manual_time_for_project(self, project_id: str) -> None:
        """Open dialog to add manual time to a project."""
        project = self._projects_by_id.get(project_id)
        if not project:
            return
        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title(f"Ajouter du temps — {project.name[:30]}")
        dialog.grab_set()
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(False, False)
        ttk.Label(dialog, text="Durée (minutes):").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        duration_var = tk.StringVar(value="30")
        ttk.Entry(dialog, textvariable=duration_var, width=8).grid(row=0, column=1, padx=6, pady=6)
        ttk.Label(dialog, text="Note (optionnel):").grid(row=1, column=0, sticky="nw", padx=6, pady=6)
        note_text = tk.Text(dialog, height=3, width=35, wrap=tk.WORD)
        note_text.grid(row=1, column=1, padx=6, pady=6)
        ttk.Label(dialog, text="Date (JJ/MM/AAAA, vide=aujourd'hui):").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        date_var = tk.StringVar(value="")
        ttk.Entry(dialog, textvariable=date_var, width=12).grid(row=2, column=1, padx=6, pady=6)

        def submit() -> None:
            try:
                mins = int(duration_var.get().strip())
            except ValueError:
                messagebox.showerror("Erreur", "La durée doit être un nombre de minutes.", parent=dialog)
                return
            if mins <= 0:
                messagebox.showerror("Erreur", "La durée doit être positive.", parent=dialog)
                return
            note = note_text.get("1.0", tk.END).strip() or None
            day_val = date_var.get().strip() or None
            if day_val:
                try:
                    from datetime import datetime as dt
                    # Accept DD/MM/YYYY or YYYY-MM-DD
                    if "/" in day_val:
                        day_parsed = dt.strptime(day_val, "%d/%m/%Y").date()
                    else:
                        day_parsed = dt.strptime(day_val, "%Y-%m-%d").date()
                except ValueError:
                    messagebox.showerror("Erreur", "Date invalide. Utilisez JJ/MM/AAAA.", parent=dialog)
                    return
            else:
                day_parsed = None
            try:
                self.service.add_manual_time(
                    project_id,
                    duration_sec=mins * 60,
                    day=day_parsed,
                    note=note,
                    create_activity=False,
                )
                dialog.destroy()
                self._refresh_timer()
                messagebox.showinfo("Succès", f"{mins} min ajouté(s) au projet.")
            except ValueError as e:
                messagebox.showerror("Erreur", str(e), parent=dialog)
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible d'ajouter le temps:\n{e}", parent=dialog)

        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Ajouter", command=submit).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.LEFT)
        dialog.wait_window()
    
    def _open_entry_external(self, entry_id: str) -> None:
        """Open entry in external editor."""
        entry_path = self.service.storage.data_dir / "entries" / f"{entry_id}.md"
        
        if not entry_path.exists():
            messagebox.showerror("Erreur", f"Fichier non trouvé: {entry_path}")
            return
        
        import subprocess
        import sys
        
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(str(entry_path))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(entry_path)], check=True)
            else:
                subprocess.run(["xdg-open", str(entry_path)], check=True)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier:\n{e}")
    
    def _copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard."""
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copié", f"ID copié: {text[:16]}...")
    
    def _delete_entry_from_explorer(self, entry_id: str) -> None:
        """Delete entry from explorer context menu."""
        entries = self.service.storage.read_entries_meta()
        entry = next((e for e in entries if e.id == entry_id), None)
        
        if not entry:
            return
        
        result = messagebox.askyesno(
            "Confirmer suppression",
            f"Supprimer l'entry \"{entry.title}\"?\n\nCette action est irréversible."
        )
        
        if result:
            try:
                self.service.delete_entry(entry_id)
                
                # Clear editor if this entry is loaded
                if self._current_entry_id == entry_id:
                    self._on_new_entry_editor()
                
                self._refresh_explorer()
                messagebox.showinfo("Succès", "Entry supprimée")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de supprimer:\n{e}")
    
    def _archive_project(self, project_id: str) -> None:
        """Set project status to archived (finished)."""
        project = self._projects_by_id.get(project_id)
        if not project or project.status == "archived":
            return
        try:
            self.service.update_project(
                project_id,
                name=project.name,
                description=project.description,
                tags=project.tags,
                person=project.person,
                group=project.group,
                status="archived",
            )
            self._projects_by_id[project_id] = replace(project, status="archived")
            if not self._show_archived_var.get():
                self.refresh()
            else:
                self._refresh_explorer()
            messagebox.showinfo("Succès", f"Projet « {project.name} » archivé.")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'archiver:\n{e}")

    def _unarchive_project(self, project_id: str) -> None:
        """Set project status back to active."""
        project = self._projects_by_id.get(project_id)
        if not project or project.status != "archived":
            return
        try:
            self.service.update_project(
                project_id,
                name=project.name,
                description=project.description,
                tags=project.tags,
                person=project.person,
                group=project.group,
                status="active",
            )
            self._projects_by_id[project_id] = replace(project, status="active")
            self._refresh_explorer()
            messagebox.showinfo("Succès", f"Projet « {project.name} » désarchivé.")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de désarchiver:\n{e}")

    def _delete_project_from_explorer(self, project_id: str) -> None:
        """Delete project (and its sub-projects) from explorer context menu."""
        project = self._projects_by_id.get(project_id)
        if not project:
            return
        children = [p for p in self._projects_by_id.values() if p.parent_id == project_id]
        msg = f"Supprimer le projet \"{project.name}\"?"
        if children:
            msg += f"\n\nCe projet a {len(children)} sous-projet(s). Eux et toutes leurs entries seront aussi supprimés."
        msg += "\n\nCette action est irréversible."
        result = messagebox.askyesno("Confirmer suppression", msg)
        if not result:
            return
        try:
            self.service.delete_project(project_id)
            self.refresh()
            # Clear current project if it was deleted or is no longer in the list
            if self.current_project_id and self.current_project_id not in self._projects_by_id:
                self.current_project_id = None
            messagebox.showinfo("Succès", "Projet supprimé")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de supprimer le projet:\n{e}")
    
    def _reorder_project_with_sibling(
        self, source_project_id: str, target_project_id: str, parent_id: str | None
    ) -> None:
        """Reorder a project among its siblings (same parent) by dropping on a sibling."""
        siblings = [
            p for p in self._projects_by_id.values()
            if p.parent_id == parent_id
        ]
        siblings.sort(key=lambda p: p.display_order)
        order_ids = [p.id for p in siblings]
        if source_project_id not in order_ids or target_project_id not in order_ids:
            return
        # Move source to target's position
        order_ids.remove(source_project_id)
        idx = order_ids.index(target_project_id)
        order_ids.insert(idx, source_project_id)
        try:
            self.service.reorder_projects_in_parent(order_ids, parent_id)
            self.refresh()
            messagebox.showinfo("Succès", "Ordre des projets mis à jour")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de réordonner:\n{e}")

    def _move_project_under(self, source_project_id: str, target_project_id: str) -> None:
        """Move a project to become a sub-project of another project."""
        source_project = self._projects_by_id.get(source_project_id)
        target_project = self._projects_by_id.get(target_project_id)
        
        if not source_project or not target_project:
            return
        
        # Prevent circular hierarchy
        if target_project_id == source_project_id:
            messagebox.showwarning("Attention", "Un projet ne peut pas être son propre parent!")
            return
        
        # Check if target is a descendant of source (would create cycle)
        current = target_project
        while current and current.parent_id:
            if current.parent_id == source_project_id:
                messagebox.showwarning(
                    "Attention",
                    f"Impossible: '{target_project.name}' est déjà un sous-projet de '{source_project.name}'!"
                )
                return
            current = self._projects_by_id.get(current.parent_id)
        
        # Confirm move
        result = messagebox.askyesno(
            "Déplacer projet",
            f"Déplacer '{source_project.name}'\n\nComme sous-projet de: {target_project.name}"
        )
        
        if result:
            try:
                # Update project parent
                self.service.move_project(source_project_id, target_project_id)
                
                self._refresh_explorer()
                
                # Expand target to show the moved project
                target_item = f"project:{target_project_id}"
                if self.explorer_tree.exists(target_item):
                    self.explorer_tree.item(target_item, open=True)
                
                messagebox.showinfo("Succès", f"Projet déplacé sous '{target_project.name}'")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de déplacer:\n{e}")
    
    def _move_entry_to_project(self, entry_id: str, target_project_id: str) -> None:
        """Move entry to a different project."""
        entries = self.service.storage.read_entries_meta()
        entry = next((e for e in entries if e.id == entry_id), None)
        
        if not entry:
            return
        
        # Get project names for confirmation
        source_project = self._projects_by_id.get(entry.project_id)
        target_project = self._projects_by_id.get(target_project_id)
        
        if not target_project:
            return
        
        source_name = source_project.name if source_project else entry.project_id[:8]
        
        result = messagebox.askyesno(
            "Déplacer entry",
            f"Déplacer \"{entry.title}\"\n\nDe: {source_name}\nVers: {target_project.name}"
        )
        
        if result:
            try:
                self.service.move_entry(
                    entry_id,
                    target_project_id,
                    keep_tags=True,
                    keep_people=True,
                )
                
                self._refresh_explorer()
                self.current_project_id = target_project_id
                self._refresh_tasks()
                
                messagebox.showinfo("Succès", f"Entry déplacée vers {target_project.name}")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de déplacer:\n{e}")
    
    def _on_new_project(self) -> None:
        """Create a new project (single dialog)."""
        project = show_new_project_dialog(
            self.winfo_toplevel(),
            self.service,
            parent_id=None,
        )
        if not project:
            return
        self.current_project_id = project.id
        self.refresh()
        new_item = f"project:{project.id}"
        if self.explorer_tree.exists(new_item):
            self.explorer_tree.item(new_item, open=True)
            self.explorer_tree.selection_set(new_item)
        messagebox.showinfo("Succès", f"Projet '{project.name}' créé!")
    
    def _on_new_subproject(self, parent_item_id: str) -> None:
        """Create a new sub-project (single dialog)."""
        parent_id = parent_item_id.replace("project:", "")
        parent_project = self._projects_by_id.get(parent_id)
        if not parent_project:
            return
        project = show_new_project_dialog(
            self.winfo_toplevel(),
            self.service,
            parent_id=parent_id,
        )
        if not project:
            return
        self.current_project_id = project.id
        self.refresh()
        parent_item = f"project:{parent_id}"
        new_item = f"project:{project.id}"
        if self.explorer_tree.exists(parent_item):
            self.explorer_tree.item(parent_item, open=True)
        if self.explorer_tree.exists(new_item):
            self.explorer_tree.selection_set(new_item)
        messagebox.showinfo("Succès", f"Sous-projet '{project.name}' créé sous '{parent_project.name}'!")
    
    def _on_new_entry_dialog(self, project_id: str) -> None:
        """Open the new-entry dialog for a project (right-click menu)."""
        self.current_project_id = project_id
        top = self.winfo_toplevel()
        result = show_new_entry_dialog(top, self.service, project_id)
        if not result:
            return
        entry, _path = result
        refresh_all = getattr(top, "_refresh_panels_after_entry_mutation", None)
        if callable(refresh_all):
            refresh_all()
        else:
            self._refresh_explorer()
        self._load_entry_in_editor(entry.id)

    def _on_new_entry_from_explorer(self) -> None:
        """Create new entry from explorer."""
        # Get selected project or ask user
        selection = self.explorer_tree.selection()
        
        if selection and selection[0].startswith("project:"):
            project_id = selection[0].replace("project:", "")
            self.current_project_id = project_id
        elif selection and selection[0].startswith("entry:"):
            # Get project from entry
            entry_id = selection[0].replace("entry:", "")
            entries = self.service.storage.read_entries_meta()
            entry = next((e for e in entries if e.id == entry_id), None)
            if entry:
                self.current_project_id = entry.project_id
        
        if not self.current_project_id:
            messagebox.showwarning("Attention", "Sélectionnez d'abord un projet dans l'arborescence")
            return
        
        # Start new entry
        self._on_new_entry_editor()
    
    def _refresh_timer(self) -> None:
        """Refresh timer display."""
        # Check timer state from storage
        state = self.service.storage.read_timer_state()
        
        if state.running and state.project_id:
            # Get project info
            project = self._projects_by_id.get(state.project_id)
            
            if project and state.start_time:
                try:
                    start_time = datetime.fromisoformat(state.start_time.replace('Z', '+00:00'))
                    elapsed = datetime.now(start_time.tzinfo) - start_time
                    hours = int(elapsed.total_seconds() // 3600)
                    minutes = int((elapsed.total_seconds() % 3600) // 60)
                    
                    self.timer_var.set(f"⏱️ {project.name} - {hours:02d}:{minutes:02d}")
                    self.btn_start_timer.config(state=tk.DISABLED)
                    self.btn_stop_timer.config(state=tk.NORMAL)
                    self._update_time_today_and_journal()
                    return
                except Exception as e:
                    logger.error(f"Failed to parse timer: {e}")
        
        # No timer running
        self.timer_var.set("Aucun timer actif")
        self.btn_start_timer.config(state=tk.NORMAL)
        self.btn_stop_timer.config(state=tk.DISABLED)
        
        self._update_time_today_and_journal()
    
    def _update_time_today_and_journal(self) -> None:
        """Update 'Temps du jour' label and journal du jour list."""
        try:
            today_sec = self.service.time_today()
            if today_sec:
                parts = []
                for pid, sec in sorted(today_sec.items(), key=lambda x: -x[1])[:5]:
                    proj = self._projects_by_id.get(pid)
                    name = proj.name if proj else pid
                    parts.append(f"{name}: {sec // 60} min")
                self.time_today_var.set("Aujourd’hui: " + ", ".join(parts))
            else:
                self.time_today_var.set("Aujourd’hui: 0 min")
        except Exception as e:
            logger.debug("time_today: %s", e)
            self.time_today_var.set("")
        self._refresh_journal_today()
    
    def _refresh_journal_today(self) -> None:
        """Populate journal du jour list from log_today()."""
        self.journal_listbox.delete(0, tk.END)
        self._journal_items.clear()
        try:
            for project, entries in self.service.log_today():
                if "calendar-sync" in (project.tags or []):
                    continue
                for entry in entries:
                    title = (entry.title or "Sans titre")[:60]
                    self.journal_listbox.insert(tk.END, f"  {project.name} — {title}")
                    self._journal_items.append(entry.id)
            if not self._journal_items:
                self.journal_listbox.insert(
                    tk.END,
                    "  (Aucune entrée aujourd’hui — horodatage local, hors dossiers calendrier.)",
                )
        except Exception as e:
            logger.debug("log_today: %s", e)
    
    def _on_journal_entry_double_click(self, event: tk.Event) -> None:
        """Load selected today's entry in editor and reveal in explorer."""
        sel = self.journal_listbox.curselection()
        if not sel or sel[0] >= len(self._journal_items):
            return
        entry_id = self._journal_items[sel[0]]
        self.load_entry(entry_id)
        self.reveal_entry_in_explorer(entry_id)
    
    def _get_descendant_project_ids(self, project_id: str) -> list[str]:
        """Return list of all descendant project IDs (children, grandchildren, ...)."""
        result: list[str] = []
        stack = [p.id for p in self._projects_by_id.values() if p.parent_id == project_id]
        while stack:
            pid = stack.pop()
            result.append(pid)
            stack.extend(p.id for p in self._projects_by_id.values() if p.parent_id == pid)
        return result

    def _refresh_tasks(self) -> None:
        """Refresh tasks list for current project and its sub-projects, with separation."""
        for item in self.tasks_tree.get_children():
            self.tasks_tree.delete(item)
        
        if not self.current_project_id:
            return
        
        try:
            project = self._projects_by_id.get(self.current_project_id)
            project_name = project.name if project else self.current_project_id
            descendant_ids = self._get_descendant_project_ids(self.current_project_id)

            def sort_tasks(tasks_list):
                tasks_list.sort(key=lambda t: (t.status == "done", t.due_date or "9999-99-99"))

            # Section 1: Tâches du projet (direct tasks)
            direct_tasks = self.service.list_tasks(self.current_project_id, status="all")
            sort_tasks(direct_tasks)
            section_project_iid = "section:project"
            self.tasks_tree.insert("", tk.END, iid=section_project_iid, text="Projet", values=(f"Tâches de « {project_name} »", "", ""))
            for task in direct_tasks[:30]:
                icon = "✓" if task.status == "done" else "○"
                due_str = task.due_date or "-"
                self.tasks_tree.insert(section_project_iid, tk.END, iid=task.id, text=icon, values=(task.title, task.status, due_str))

            # Section 2: Sous-projets (tasks from child projects)
            if descendant_ids:
                section_children_iid = "section:children"
                self.tasks_tree.insert("", tk.END, iid=section_children_iid, text="Sous-projets", values=("Tâches des sous-projets", "", ""))
                for child_id in descendant_ids:
                    child = self._projects_by_id.get(child_id)
                    child_name = child.name if child else child_id
                    child_tasks = self.service.list_tasks(child_id, status="all")
                    sort_tasks(child_tasks)
                    subsection_iid = f"subsection:{child_id}"
                    self.tasks_tree.insert(section_children_iid, tk.END, iid=subsection_iid, text="📂", values=(child_name, "", ""))
                    for task in child_tasks[:20]:
                        icon = "✓" if task.status == "done" else "○"
                        due_str = task.due_date or "-"
                        self.tasks_tree.insert(subsection_iid, tk.END, iid=f"task:{child_id}:{task.id}", text=icon, values=(task.title, task.status, due_str))
        except ProjectNotFoundError:
            logger.debug("Current project no longer exists, clearing selection")
            self.current_project_id = None
            self.explorer_tree.selection_set(())
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")

    def _sort_tasks_tree(self, column_id: str) -> None:
        """Sort task rows within each section (Projet / Sous-projets) by column."""
        if not hasattr(self, "_tasks_sort_col"):
            self._tasks_sort_col = None
            self._tasks_sort_reverse = False
        if self._tasks_sort_col == column_id:
            self._tasks_sort_reverse = not self._tasks_sort_reverse
        else:
            self._tasks_sort_col = column_id
            self._tasks_sort_reverse = column_id == "due"
        cols = ("title", "status", "due")
        if column_id not in cols:
            return
        col_idx = cols.index(column_id)

        def sort_key(x):
            iid, text, vals = x
            if col_idx >= len(vals):
                return ""
            v = (vals[col_idx] or "").strip().lower()
            if column_id == "due" and v and v != "-":
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass
            return v

        def sort_children_of(parent_iid: str) -> None:
            child_iids = list(self.tasks_tree.get_children(parent_iid))
            if not child_iids:
                return
            items = [(iid, self.tasks_tree.item(iid, "text"), self.tasks_tree.item(iid, "values")) for iid in child_iids]
            items.sort(key=sort_key, reverse=self._tasks_sort_reverse)
            for iid in child_iids:
                self.tasks_tree.detach(iid)
            for iid, text, vals in items:
                self.tasks_tree.move(iid, parent_iid, tk.END)

        for root_child in self.tasks_tree.get_children(""):
            if root_child == "section:project":
                sort_children_of(root_child)
            elif root_child == "section:children":
                for sub in self.tasks_tree.get_children(root_child):
                    sort_children_of(sub)

    def _on_add_entry(self) -> None:
        """Add new entry."""
        if not self.current_project_id:
            messagebox.showwarning("Attention", "Veuillez sélectionner un projet")
            return
        
        title = self.entry_title_var.get().strip()
        if not title:
            messagebox.showwarning("Attention", "Le titre est requis")
            return
        
        body = self.entry_body_text.get("1.0", tk.END).strip()
        entry_type = self.entry_type_var.get()
        
        # Parse metadata
        tags = [t.strip() for t in self.entry_tags_var.get().split(",") if t.strip()]
        person = self.entry_people_var.get().strip() or None
        group = self.entry_groups_var.get().strip() or None
        status = self.entry_status_var.get().strip() or None
        
        date_raw = self.entry_date_var.get().strip()
        entry_date_parsed: date | None
        if not date_raw:
            entry_date_parsed = None
        else:
            try:
                entry_date_parsed = parse_date_ui(date_raw)
            except ValueError:
                messagebox.showwarning(
                    "Attention",
                    "Date invalide. Utilisez JJ/MM/AAAA ou AAAA-MM-JJ.",
                )
                return

        start_t = (self.entry_start_var.get().strip() or None) if entry_type == "meeting" else None
        end_t = (self.entry_end_var.get().strip() or None) if entry_type == "meeting" else None
        decision_done = (
            self.entry_decision_done_var.get() if entry_type == "decision" else None
        )

        try:
            prio = 3
            try:
                prio = self.entry_priority_var.get()
            except tk.TclError:
                pass
            if not (1 <= prio <= 5):
                prio = 3
            self.service.add_entry(
                project_id=self.current_project_id,
                entry_type=entry_type,
                title=title,
                tags=tags,
                body=body,
                entry_date=entry_date_parsed,
                person=person,
                group=group,
                priority=prio,
                start_time=start_t,
                end_time=end_t,
                decision_done=decision_done,
            )
            
            # Apply status if set
            if status:
                # Get the newly created entry (last one for this project)
                entries = self.service.storage.read_entries_meta()
                new_entry = next(
                    (e for e in reversed(entries) if e.project_id == self.current_project_id and e.title == title),
                    None
                )
                if new_entry:
                    self.service.set_entry_context_status(new_entry.id, status)
            
            # Clear form
            self._on_clear_form()
            
            # Refresh explorer
            self._refresh_explorer()
            
            messagebox.showinfo("Succès", f"Entry '{title}' créée!")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de créer l'entry:\n{e}")
    
    def _on_save_entry(self) -> None:
        """Save current entry modifications."""
        if not self._current_entry_id:
            # No entry loaded, create new one
            self._on_add_entry()
            return
        
        title = self.entry_title_var.get().strip()
        if not title:
            messagebox.showwarning("Attention", "Le titre est requis")
            return
        
        body = self.entry_body_text.get("1.0", tk.END).strip()
        
        try:
            # Update entry content (body in MD file)
            self.service.update_entry_content(self._current_entry_id, body)
            
            # Update metadata
            entries = self.service.storage.read_entries_meta()
            entry = next((e for e in entries if e.id == self._current_entry_id), None)
            
            if entry:
                # Prepare metadata patch
                patch = {}
                if entry.title != title:
                    patch["title"] = title
                
                # Update person, group, tags
                person = self.entry_people_var.get().strip()
                if person != (entry.person or ""):
                    patch["person"] = person if person else None
                
                group = self.entry_groups_var.get().strip()
                if group != (entry.group or ""):
                    patch["group"] = group if group else None
                
                tags = [t.strip() for t in self.entry_tags_var.get().split(",") if t.strip()]
                if tags != entry.tags:
                    patch["tags"] = tags
                
                date_str = self.entry_date_var.get().strip()
                if date_str:
                    try:
                        parsed_d = parse_date_ui(date_str)
                    except ValueError:
                        messagebox.showwarning(
                            "Attention",
                            "Date invalide. Utilisez JJ/MM/AAAA ou AAAA-MM-JJ.",
                        )
                        return
                    new_iso = parsed_d.isoformat()
                    if new_iso != (entry.entry_date or ""):
                        patch["entry_date"] = parsed_d

                if entry.type == "meeting":
                    st = self.entry_start_var.get().strip() or None
                    en = self.entry_end_var.get().strip() or None
                    if st != (entry.start_time or None) or en != (entry.end_time or None):
                        patch["start_time"] = st
                        patch["end_time"] = en
                elif entry.type == "decision":
                    new_dd = self.entry_decision_done_var.get()
                    if new_dd != bool(entry.decision_done):
                        patch["decision_done"] = new_dd
                
                status = self.entry_status_var.get().strip()
                if status != (entry.context_status or ""):
                    patch["context_status"] = status if status else None
                
                try:
                    prio = self.entry_priority_var.get()
                except tk.TclError:
                    prio = 3
                if not (1 <= prio <= 5):
                    prio = 3
                if prio != getattr(entry, "priority", 3):
                    patch["priority"] = prio
                
                # Apply patch if there are changes
                if patch:
                    self.service.update_entry_meta(self._current_entry_id, **patch)
            
            # Reset modified flag
            self._entry_modified = False
            self.entry_body_text.edit_modified(False)
            self.btn_save.config(state=tk.DISABLED)
            self.current_entry_var.set(f"✓ Enregistré: {title[:40]}")
            
            # Refresh explorer
            self._refresh_explorer()
            
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'enregistrer:\n{e}")
    
    def _on_new_entry_editor(self) -> None:
        """Start editing a new entry."""
        self._cancel_autosave()
        if self._entry_modified:
            result = messagebox.askyesnocancel(
                "Modifications non enregistrées",
                "Voulez-vous enregistrer les modifications avant de créer une nouvelle entry?"
            )
            if result is None:  # Cancel
                return
            elif result:  # Yes
                self._on_save_entry()
        
        # Clear editor
        self._current_entry_id = None
        self.entry_title_var.set("")
        self.entry_body_text.delete("1.0", tk.END)
        self.entry_type_var.set("note")
        self.entry_date_var.set(format_date_ui(date.today()))
        self.btn_followup.config(state=tk.DISABLED)
        self.entry_people_var.set("")
        self.entry_groups_var.set("")
        self.entry_tags_var.set("")
        self.entry_status_var.set("")
        self.entry_priority_var.set(3)
        self.current_entry_var.set("Nouvelle entry")
        self._entry_modified = False
        self.btn_save.config(state=tk.DISABLED)
        
        # Apply template for new entry
        self._on_entry_type_changed()
    
    def _on_delete_current_entry(self) -> None:
        """Delete currently loaded entry."""
        if not self._current_entry_id:
            messagebox.showwarning("Attention", "Aucune entry chargée")
            return
        
        title = self.entry_title_var.get()
        result = messagebox.askyesno(
            "Confirmer suppression",
            f"Supprimer l'entry \"{title}\"?\n\nCette action est irréversible."
        )
        
        if result:
            try:
                self.service.delete_entry(self._current_entry_id)
                self._on_new_entry_editor()  # Clear editor
                self._refresh_explorer()
                messagebox.showinfo("Succès", "Entry supprimée")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de supprimer:\n{e}")
    
    def _on_open_external(self) -> None:
        """Open current entry in external editor."""
        if not self._current_entry_id:
            messagebox.showwarning("Attention", "Aucune entry chargée")
            return
        
        entry_path = self.service.storage.data_dir / "entries" / f"{self._current_entry_id}.md"
        
        if not entry_path.exists():
            messagebox.showerror("Erreur", f"Fichier non trouvé: {entry_path}")
            return
        
        import subprocess
        import sys
        
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(str(entry_path))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(entry_path)], check=True)
            else:
                subprocess.run(["xdg-open", str(entry_path)], check=True)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier:\n{e}")
    
    def _on_content_modified(self, event=None) -> None:
        """Handle text content modification; schedule autosave after delay."""
        if self.entry_body_text.edit_modified():
            self._entry_modified = True
            self.btn_save.config(state=tk.NORMAL)
            self._schedule_autosave()
    
    def _cancel_autosave(self) -> None:
        """Cancel any pending autosave."""
        if self._autosave_after_id:
            self.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
    
    def _schedule_autosave(self) -> None:
        """Schedule autosave of entry body after AUTOSAVE_DELAY_MS."""
        if not self._current_entry_id:
            return
        self._cancel_autosave()
        self._autosave_after_id = self.after(AUTOSAVE_DELAY_MS, self._do_autosave)
    
    def _do_autosave(self) -> None:
        """Save entry body to disk (autosave)."""
        self._autosave_after_id = None
        if not self._current_entry_id:
            return
        if not self.entry_body_text.edit_modified():
            return
        try:
            body = self.entry_body_text.get("1.0", tk.END)
            self.service.update_entry_content(self._current_entry_id, body)
            self.entry_body_text.edit_modified(False)
            self._entry_modified = False
            self.btn_save.config(state=tk.DISABLED)
            logger.debug("Entry content autosaved: %s", self._current_entry_id[:8])
        except Exception as e:
            logger.warning("Autosave failed: %s", e)
    
    def _on_entry_type_changed(self, event=None) -> None:
        """Handle entry type change - apply template if content is empty."""
        self._sync_entry_type_extra_widgets()
        if self._current_entry_id:
            # Don't apply template if editing existing entry
            return
        
        current_content = self.entry_body_text.get("1.0", tk.END).strip()
        if current_content:
            # Don't overwrite existing content
            return
        
        # Apply template based on type
        entry_type = self.entry_type_var.get()
        template = self._get_entry_template(entry_type)
        
        if template:
            self.entry_body_text.delete("1.0", tk.END)
            self.entry_body_text.insert("1.0", template)
    
    def _get_entry_template(self, entry_type: str) -> str:
        """Get markdown template for entry type with placeholders."""
        # Date affichée dans le modèle : champ Date si valide, sinon aujourd'hui
        today = date.today().strftime("%d/%m/%Y")
        raw_d = self.entry_date_var.get().strip()
        if raw_d:
            try:
                today = parse_date_ui(raw_d).strftime("%d/%m/%Y")
            except ValueError:
                pass
        title = self.entry_title_var.get() or "[Titre]"
        
        # Get project name
        project_name = "[Projet]"
        if self.current_project_id:
            project = self._projects_by_id.get(self.current_project_id)
            if project:
                project_name = project.name
        
        person = self.entry_people_var.get() or ""
        group = self.entry_groups_var.get() or ""
        tags = self.entry_tags_var.get() or ""
        
        # Templates from gui_constants
        templates = {
            "note": (
                f"# {title}\n\n"
                f"**Date:** {today}\n"
                f"**Project:** {project_name}\n"
                f"**Person/Group:** {person} {group}\n"
                f"**Tags:** {tags}\n\n"
                "## Notes\n"
                "- \n\n"
                "## Next steps\n"
                "- \n"
            ),
            "meeting": (
                f"# {title}\n\n"
                f"**Date:** {today}\n"
                f"**Project:** {project_name}\n"
                f"**People:** {person} {group}\n"
                "**Time:** - \n"
                f"**Tags:** {tags}\n\n"
                "## Agenda\n"
                "- \n\n"
                "## Notes\n"
                "- \n\n"
                "## Decisions\n"
                "- \n\n"
                "## Actions\n"
                "- [ ] \n"
            ),
            "decision": (
                f"# {title}\n\n"
                f"**Date:** {today}\n"
                f"**Project:** {project_name}\n"
                f"**Person/Group:** {person} {group}\n"
                f"**Tags:** {tags}\n\n"
                "## Context\n"
                "- \n\n"
                "## Decision\n"
                "- \n\n"
                "## Rationale\n"
                "- \n\n"
                "## Consequences\n"
                "- \n\n"
                "## Follow-up\n"
                "- \n\n"
                "## Status\n"
                "- Applied/Done: \n"
            ),
            "activity": (
                f"# {title}\n\n"
                f"**Date:** {today}\n"
                f"**Project:** {project_name}\n"
                f"**Person/Group:** {person} {group}\n"
                f"**Tags:** {tags}\n\n"
                "## What was done\n"
                "- \n\n"
                "## Outcomes\n"
                "- \n\n"
                "## Blockers\n"
                "- \n\n"
                "## Next steps\n"
                "- \n"
            ),
        }
        return templates.get(entry_type, "")
    
    def reveal_entry_in_explorer(self, entry_id: str) -> None:
        """Bring the given entry to the front in the explorer: expand its project, select and scroll to it."""
        entries = self.service.storage.read_entries_meta()
        entry = next((e for e in entries if e.id == entry_id), None)
        if not entry:
            return
        project_id = entry.project_id
        # Path from root to this project (for expanding ancestors)
        path_ids: list[str] = []
        pid: str | None = project_id
        while pid:
            proj = self._projects_by_id.get(pid)
            if not proj:
                break
            path_ids.append(pid)
            pid = proj.parent_id
        path_ids.reverse()
        for pid in path_ids:
            node = f"project:{pid}"
            if self.explorer_tree.exists(node):
                self.explorer_tree.item(node, open=True)
        entry_iid = f"entry:{entry_id}"
        if self.explorer_tree.exists(entry_iid):
            self.explorer_tree.selection_set(entry_iid)
            self.explorer_tree.see(entry_iid)
            return
        # Entry not in tree (e.g. not in top 20): insert it under project so it appears
        project_node = f"project:{project_id}"
        if not self.explorer_tree.exists(project_node):
            return
        entry_icon = {"note": "📝", "meeting": "🤝", "decision": "✅", "activity": "⚡"}.get(entry.type, "📄")
        entry_text = f"{entry_icon} {entry.title[:50]}"
        if entry.entry_date:
            entry_text += f" ({entry.entry_date})"
        self.explorer_tree.insert(project_node, 0, iid=entry_iid, text=entry_text)
        self.explorer_tree.selection_set(entry_iid)
        self.explorer_tree.see(entry_iid)

    def _load_entry_in_editor(self, entry_id: str) -> None:
        """Load an entry into the editor."""
        self._cancel_autosave()
        # Check for unsaved changes
        if self._entry_modified:
            result = messagebox.askyesnocancel(
                "Modifications non enregistrées",
                "Voulez-vous enregistrer les modifications?"
            )
            if result is None:  # Cancel
                return
            elif result:  # Yes
                self._on_save_entry()
        
        # Load entry
        try:
            entries = self.service.storage.read_entries_meta()
            entry = next((e for e in entries if e.id == entry_id), None)
            
            if not entry:
                messagebox.showerror("Erreur", "Entry non trouvée")
                return
            
            # Load content
            entry_path = self.service.storage.data_dir / "entries" / f"{entry_id}.md"
            if entry_path.exists():
                content = entry_path.read_text(encoding="utf-8")
            else:
                content = ""
            
            # Update editor
            self._current_entry_id = entry_id
            self.entry_title_var.set(entry.title)
            self.entry_type_var.set(entry.type)
            
            # Update metadata
            self.entry_date_var.set(
                format_date_ui(entry.entry_date) if entry.entry_date else ""
            )
            self.entry_people_var.set(entry.person or "")
            self.entry_groups_var.set(entry.group or "")
            self.entry_tags_var.set(", ".join(entry.tags) if entry.tags else "")
            self.entry_status_var.set(entry.context_status or "")
            prio = getattr(entry, "priority", 3)
            if not isinstance(prio, int) or not (1 <= prio <= 5):
                prio = 3
            self.entry_priority_var.set(prio)
            self.entry_start_var.set(entry.start_time or "")
            self.entry_end_var.set(entry.end_time or "")
            self.entry_decision_done_var.set(bool(entry.decision_done))
            self._sync_entry_type_extra_widgets()
            
            self.entry_body_text.delete("1.0", tk.END)
            self.entry_body_text.insert("1.0", content)
            self.current_entry_var.set(f"📝 {entry.title[:40]}{'...' if len(entry.title) > 40 else ''}")
            
            # Reset modified flag
            self._entry_modified = False
            self.entry_body_text.edit_modified(False)
            self.btn_save.config(state=tk.DISABLED)
            self.btn_followup.config(state=tk.NORMAL)
            
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de charger l'entry:\n{e}")

    def _find_task_row_iid(self, task_id: str) -> str | None:
        """Return the tree iid of the row that displays the given task_id, or None."""
        for iid in self.tasks_tree.get_children("section:project") or []:
            if iid == task_id:
                return iid
        for sub_iid in self.tasks_tree.get_children("section:children") or []:
            for iid in self.tasks_tree.get_children(sub_iid) or []:
                if iid.startswith("task:") and iid.endswith(f":{task_id}"):
                    return iid
        return None

    def show_task(self, task_id: str) -> None:
        """Switch to this panel and select the given task (sets project and refreshes tasks)."""
        task = next(
            (t for t in self.service.storage.read_tasks() if t.id == task_id),
            None,
        )
        if not task:
            return
        self.current_project_id = task.project_id
        self._refresh_tasks()
        row_iid = self._find_task_row_iid(task_id)
        if row_iid:
            self.tasks_tree.selection_set(row_iid)
            self.tasks_tree.see(row_iid)
    
    def _on_clear_form(self) -> None:
        """Clear entry form."""
        self.entry_title_var.set("")
        self.entry_body_text.delete("1.0", tk.END)
        self.entry_type_var.set("note")
        self.entry_priority_var.set(3)
        self.entry_date_var.set(format_date_ui(date.today()))
        self.entry_people_var.set("")
        self.entry_groups_var.set("")
        self.entry_tags_var.set("")
        self.entry_status_var.set("")
        self.entry_start_var.set("")
        self.entry_end_var.set("")
        self.entry_decision_done_var.set(False)
        self._sync_entry_type_extra_widgets()
    
    def _on_add_task(self) -> None:
        """Add new task."""
        if not self.current_project_id:
            messagebox.showwarning("Attention", "Veuillez sélectionner un projet")
            return
        initial_title = ""
        initial_tags = None
        linked_entry_id = None
        if self._current_entry_id:
            entries = [
                e for e in self.service.storage.read_entries_meta()
                if e.project_id == self.current_project_id
            ]
            entry = next((e for e in entries if e.id == self._current_entry_id), None)
            if entry:
                initial_title = f"Follow-up: {entry.title}"
                initial_tags = entry.tags
                linked_entry_id = entry.id
        parent = self.winfo_toplevel()
        result = show_new_task_dialog(
            parent,
            self.service,
            self.current_project_id,
            initial_title=initial_title,
            initial_tags=initial_tags,
            linked_entry_id=linked_entry_id,
            show_link_entry_check=bool(linked_entry_id),
        )
        if result:
            self._refresh_tasks()
    
    def _task_iid_to_task_and_project(self, iid: str) -> tuple[str, str] | None:
        """From a tree item iid, return (task_id, project_id) if it's a task row, else None."""
        if not iid or iid.startswith("section:") or iid.startswith("subsection:"):
            return None
        if iid.startswith("task:"):
            parts = iid.split(":", 2)
            if len(parts) >= 3:
                return (parts[2], parts[1])
            return None
        # Direct task (iid is task.id)
        if self.current_project_id:
            return (iid, self.current_project_id)
        return None

    def _on_task_double_click(self, event) -> None:
        """Handle task double-click (edit)."""
        selection = self.tasks_tree.selection()
        if not selection:
            return
        pair = self._task_iid_to_task_and_project(selection[0])
        if not pair:
            return
        task_id, _ = pair
        parent = self.winfo_toplevel()
        result = show_edit_task_dialog(parent, self.service, task_id)
        if result:
            self._refresh_tasks()

    def _on_task_toggle(self, event) -> None:
        """Toggle task done/open."""
        selection = self.tasks_tree.selection()
        if not selection:
            return
        pair = self._task_iid_to_task_and_project(selection[0])
        if not pair:
            return
        task_id, project_id = pair
        try:
            tasks = self.service.list_tasks(project_id, status="all")
            task = next((t for t in tasks if t.id == task_id), None)
            if task:
                new_status = "open" if task.status == "done" else "done"
                self.service.set_task_done(task_id, new_status == "done")
                self._refresh_tasks()
        except Exception as e:
            logger.error(f"Failed to toggle task: {e}")
    
    
    def _on_start_timer(self) -> None:
        """Start timer for current project."""
        if not self.current_project_id:
            messagebox.showwarning("Attention", "Veuillez sélectionner un projet")
            return
        
        try:
            self.service.time_start(self.current_project_id, note=None)
            self._refresh_timer()
            messagebox.showinfo("Timer", "Timer démarré!")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de démarrer le timer:\n{e}")
    
    def _on_stop_timer(self) -> None:
        """Stop active timer."""
        try:
            self.service.time_stop(create_activity=False)
            self._refresh_timer()
            messagebox.showinfo("Timer", "Timer arrêté!")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'arrêter le timer:\n{e}")
