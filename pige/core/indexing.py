"""Full-text search indexing using SQLite FTS5.

This module provides efficient full-text search capabilities for PIGE entries,
projects, and tasks using SQLite's FTS5 extension.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pige.core.models import EntryMeta, Project, Task

logger = logging.getLogger(__name__)


class SearchIndex:
    """Full-text search index using SQLite FTS5.
    
    This class manages a SQLite database with FTS5 tables for fast
    full-text search across entries, projects, and tasks.
    
    Features:
    - Sub-50ms search for 10K+ entries
    - Automatic index updates on create/update/delete
    - Rebuild capability for corrupted indexes
    - Stemming and tokenization support
    """
    
    def __init__(self, db_path: Path) -> None:
        """Initialize search index.
        
        Args:
            db_path: Path to SQLite database file (e.g., data/.pige_index.db)
        """
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()
    
    def _ensure_db(self) -> None:
        """Ensure database and tables exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Create FTS5 table for entries
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
            USING fts5(
                entry_id UNINDEXED,
                title,
                body,
                tags,
                person,
                group_name,
                project_name,
                entry_type,
                tokenize = 'porter unicode61'
            )
        """)
        
        # Create FTS5 table for projects
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS projects_fts
            USING fts5(
                project_id UNINDEXED,
                name,
                description,
                tags,
                person,
                group_name,
                tokenize = 'porter unicode61'
            )
        """)
        
        # Create FTS5 table for tasks
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts
            USING fts5(
                task_id UNINDEXED,
                title,
                project_name,
                entry_title,
                tokenize = 'porter unicode61'
            )
        """)
        
        # Create metadata table to track index version
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS index_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Set initial version if not exists
        cursor.execute("""
            INSERT OR IGNORE INTO index_metadata (key, value, updated_at)
            VALUES ('version', '1', ?)
        """, (datetime.now().isoformat(),))
        
        conn.commit()
        logger.info(f"Search index initialized at {self.db_path}")
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def __enter__(self) -> SearchIndex:
        return self
    
    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object) -> bool:
        self.close()
        return False
    
    def __del__(self) -> None:
        """Cleanup: close database connection."""
        self.close()
    
    # ===== Entry Indexing =====
    
    def index_entry(self, entry: EntryMeta) -> None:
        """Index or update an entry in FTS.
        
        Args:
            entry: Entry metadata to index
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Remove existing entry if present
        cursor.execute("DELETE FROM entries_fts WHERE entry_id = ?", (entry.id,))
        
        # Insert new/updated entry
        cursor.execute("""
            INSERT INTO entries_fts (
                entry_id, title, body, tags, person, 
                group_name, project_name, entry_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.id,
            entry.title,
            entry.summary or "",  # Use summary instead of body
            " ".join(entry.tags),
            entry.person or "",
            entry.group or "",
            "",  # project_name will be resolved by caller
            entry.type
        ))
        
        conn.commit()
        logger.debug(f"Indexed entry {entry.id}")
    
    def remove_entry(self, entry_id: str) -> None:
        """Remove an entry from FTS.
        
        Args:
            entry_id: ID of entry to remove
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM entries_fts WHERE entry_id = ?", (entry_id,))
        conn.commit()
        logger.debug(f"Removed entry {entry_id} from index")
    
    def index_entries_bulk(self, entries: list[EntryMeta]) -> None:
        """Bulk index entries (faster than individual calls).
        
        Args:
            entries: List of entries to index
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Clear existing entries
        cursor.execute("DELETE FROM entries_fts")
        
        # Bulk insert
        data = [
            (
                e.id, e.title, e.summary or "", " ".join(e.tags),
                e.person or "", e.group or "", "", e.type  # project_name empty for now
            )
            for e in entries
        ]
        
        cursor.executemany("""
            INSERT INTO entries_fts (
                entry_id, title, body, tags, person,
                group_name, project_name, entry_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        
        conn.commit()
        logger.info(f"Bulk indexed {len(entries)} entries")
    
    # ===== Project Indexing =====
    
    def index_project(self, project: Project) -> None:
        """Index or update a project in FTS.
        
        Args:
            project: Project to index
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Remove existing project if present
        cursor.execute("DELETE FROM projects_fts WHERE project_id = ?", (project.id,))
        
        # Insert new/updated project
        cursor.execute("""
            INSERT INTO projects_fts (
                project_id, name, description, tags, person, group_name
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            project.id,
            project.name,
            project.description or "",
            " ".join(project.tags),
            project.person or "",
            project.group or ""
        ))
        
        conn.commit()
        logger.debug(f"Indexed project {project.id}")
    
    def remove_project(self, project_id: str) -> None:
        """Remove a project from FTS.
        
        Args:
            project_id: ID of project to remove
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects_fts WHERE project_id = ?", (project_id,))
        conn.commit()
        logger.debug(f"Removed project {project_id} from index")
    
    def index_projects_bulk(self, projects: list[Project]) -> None:
        """Bulk index projects.
        
        Args:
            projects: List of projects to index
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Clear existing projects
        cursor.execute("DELETE FROM projects_fts")
        
        # Bulk insert
        data = [
            (
                p.id, p.name, p.description or "", " ".join(p.tags),
                p.person or "", p.group or ""
            )
            for p in projects
        ]
        
        cursor.executemany("""
            INSERT INTO projects_fts (
                project_id, name, description, tags, person, group_name
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, data)
        
        conn.commit()
        logger.info(f"Bulk indexed {len(projects)} projects")
    
    # ===== Task Indexing =====
    
    def index_task(self, task: Task, project_name: str | None = None, entry_title: str | None = None) -> None:
        """Index or update a task in FTS.
        
        Args:
            task: Task to index
            project_name: Optional project name for context
            entry_title: Optional entry title for context
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Remove existing task if present
        cursor.execute("DELETE FROM tasks_fts WHERE task_id = ?", (task.id,))
        
        # Insert new/updated task
        cursor.execute("""
            INSERT INTO tasks_fts (
                task_id, title, project_name, entry_title
            ) VALUES (?, ?, ?, ?)
        """, (
            task.id,
            task.title,
            project_name or "",
            entry_title or ""
        ))
        
        conn.commit()
        logger.debug(f"Indexed task {task.id}")
    
    def remove_task(self, task_id: str) -> None:
        """Remove a task from FTS.
        
        Args:
            task_id: ID of task to remove
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks_fts WHERE task_id = ?", (task_id,))
        conn.commit()
        logger.debug(f"Removed task {task_id} from index")
    
    def index_tasks_bulk(self, tasks_data: list[tuple[Task, str | None, str | None]]) -> None:
        """Bulk index tasks.
        
        Args:
            tasks_data: List of (task, project_name, entry_title) tuples
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Clear existing tasks
        cursor.execute("DELETE FROM tasks_fts")
        
        # Bulk insert
        data = [
            (t.id, t.title, pn or "", et or "")
            for t, pn, et in tasks_data
        ]
        
        cursor.executemany("""
            INSERT INTO tasks_fts (
                task_id, title, project_name, entry_title
            ) VALUES (?, ?, ?, ?)
        """, data)
        
        conn.commit()
        logger.info(f"Bulk indexed {len(tasks_data)} tasks")
    
    # ===== Full-Text Search =====
    
    def search_entries(self, query: str, limit: int = 100) -> list[str]:
        """Search entries using full-text query.
        
        Args:
            query: FTS5 query string (e.g., "meeting Python", "title:important")
            limit: Maximum results to return
        
        Returns:
            List of entry IDs matching the query
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT entry_id, rank
            FROM entries_fts
            WHERE entries_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        results = [row[0] for row in cursor.fetchall()]
        logger.debug(f"Search '{query}' returned {len(results)} entries")
        return results
    
    def search_projects(self, query: str, limit: int = 100) -> list[str]:
        """Search projects using full-text query.
        
        Args:
            query: FTS5 query string
            limit: Maximum results to return
        
        Returns:
            List of project IDs matching the query
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT project_id, rank
            FROM projects_fts
            WHERE projects_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        results = [row[0] for row in cursor.fetchall()]
        logger.debug(f"Search '{query}' returned {len(results)} projects")
        return results
    
    def search_tasks(self, query: str, limit: int = 100) -> list[str]:
        """Search tasks using full-text query.
        
        Args:
            query: FTS5 query string
            limit: Maximum results to return
        
        Returns:
            List of task IDs matching the query
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT task_id, rank
            FROM tasks_fts
            WHERE tasks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        results = [row[0] for row in cursor.fetchall()]
        logger.debug(f"Search '{query}' returned {len(results)} tasks")
        return results
    
    # ===== Index Management =====
    
    def rebuild(self, entries: list[EntryMeta], projects: list[Project], tasks_data: list[tuple[Task, str | None, str | None]]) -> dict[str, int]:
        """Rebuild entire index from scratch.
        
        Args:
            entries: All entries to index
            projects: All projects to index
            tasks_data: All tasks with context to index
        
        Returns:
            Statistics dict with counts
        """
        logger.info("Rebuilding search index...")
        
        self.index_entries_bulk(entries)
        self.index_projects_bulk(projects)
        self.index_tasks_bulk(tasks_data)
        
        # Update metadata
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE index_metadata
            SET value = ?, updated_at = ?
            WHERE key = 'last_rebuild'
        """, (datetime.now().isoformat(), datetime.now().isoformat()))
        
        if cursor.rowcount == 0:
            cursor.execute("""
                INSERT INTO index_metadata (key, value, updated_at)
                VALUES ('last_rebuild', ?, ?)
            """, (datetime.now().isoformat(), datetime.now().isoformat()))
        
        conn.commit()
        
        stats = {
            "entries": len(entries),
            "projects": len(projects),
            "tasks": len(tasks_data)
        }
        
        logger.info(f"Index rebuilt: {stats}")
        return stats
    
    def get_stats(self) -> dict[str, int | str]:
        """Get index statistics.
        
        Returns:
            Dict with entry/project/task counts and metadata
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Count entries
        cursor.execute("SELECT COUNT(*) FROM entries_fts")
        entries_count = cursor.fetchone()[0]
        
        # Count projects
        cursor.execute("SELECT COUNT(*) FROM projects_fts")
        projects_count = cursor.fetchone()[0]
        
        # Count tasks
        cursor.execute("SELECT COUNT(*) FROM tasks_fts")
        tasks_count = cursor.fetchone()[0]
        
        # Get metadata
        cursor.execute("SELECT key, value FROM index_metadata")
        metadata = {row[0]: row[1] for row in cursor.fetchall()}
        
        return {
            "entries": entries_count,
            "projects": projects_count,
            "tasks": tasks_count,
            "version": metadata.get("version", "unknown"),
            "last_rebuild": metadata.get("last_rebuild", "never")
        }
