"""Tests for full-text search indexing."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pige.core.indexing import SearchIndex
from pige.core.models import EntryMeta, Project, Task


def _make_entry(id: str, title: str, summary: str = "", **kwargs) -> EntryMeta:
    """Helper to create EntryMeta with defaults."""
    return EntryMeta(
        id=id,
        ts=kwargs.get("ts", "2024-01-01T10:00:00Z"),
        project_id=kwargs.get("project_id", "proj1"),
        type=kwargs.get("type", "note"),
        title=title,
        summary=summary,
        tags=kwargs.get("tags", []),
        content_path=f"entries/{id}.md",
        entry_date=kwargs.get("entry_date", "2024-01-01"),
        person=kwargs.get("person"),
        group=kwargs.get("group")
    )


@pytest.fixture
def index_db() -> Path:
    """Create temporary index database."""
    import tempfile
    import os
    
    # Create temp file in system temp directory
    fd, path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)  # Close the file descriptor
    path = Path(path_str)
    
    yield path
    
    # Cleanup
    try:
        if path.exists():
            path.unlink()
    except:
        pass  # Ignore cleanup errors


@pytest.fixture
def search_index(index_db: Path) -> SearchIndex:
    """Create search index instance."""
    return SearchIndex(index_db)


def test_index_initialization(search_index: SearchIndex) -> None:
    """Test that index is initialized correctly."""
    stats = search_index.get_stats()
    assert stats["entries"] == 0
    assert stats["projects"] == 0
    assert stats["tasks"] == 0
    assert stats["version"] == "1"


def test_index_entry(search_index: SearchIndex) -> None:
    """Test indexing a single entry."""
    entry = _make_entry("e1", "Test Entry", "About Python", tags=["python"])
    search_index.index_entry(entry)
    
    stats = search_index.get_stats()
    assert stats["entries"] == 1


def test_search_entries(search_index: SearchIndex) -> None:
    """Test searching entries."""
    entries = [
        _make_entry("e1", "Python Tutorial", "Learn Python programming", tags=["python"]),
        _make_entry("e2", "Team Meeting", "Discuss project status", tags=["meeting"]),
        _make_entry("e3", "JavaScript Notes", "JavaScript guide", tags=["javascript"]),
    ]
    
    search_index.index_entries_bulk(entries)
    
    # Search for "Python"
    results = search_index.search_entries("Python")
    assert len(results) == 1
    assert "e1" in results
    
    # Search for "project"
    results = search_index.search_entries("project")
    assert len(results) == 1
    assert "e2" in results


def test_remove_entry(search_index: SearchIndex) -> None:
    """Test removing an entry from index."""
    entry = _make_entry("e1", "Test Entry")
    
    search_index.index_entry(entry)
    assert search_index.get_stats()["entries"] == 1
    
    search_index.remove_entry("e1")
    assert search_index.get_stats()["entries"] == 0


def test_index_project(search_index: SearchIndex) -> None:
    """Test indexing a project."""
    project = Project(
        id="p1",
        name="Test Project",
        description="A project for testing",
        status="active",
        tags=["important", "testing"],
        created_at="2024-01-01T10:00:00Z",
        person="Bob",
        group="Team B"
    )
    
    search_index.index_project(project)
    
    stats = search_index.get_stats()
    assert stats["projects"] == 1


def test_search_projects(search_index: SearchIndex) -> None:
    """Test searching projects."""
    projects = [
        Project(
            id="p1",
            name="Backend API",
            description="REST API development",
            status="active",
            tags=["backend"],
            created_at="2024-01-01T10:00:00Z"
        ),
        Project(
            id="p2",
            name="Frontend UI",
            description="User interface design",
            status="active",
            tags=["frontend"],
            created_at="2024-01-02T10:00:00Z"
        ),
    ]
    
    search_index.index_projects_bulk(projects)
    
    # Search for "API"
    results = search_index.search_projects("API")
    assert len(results) == 1
    assert "p1" in results
    
    # Search for "design"
    results = search_index.search_projects("design")
    assert len(results) == 1
    assert "p2" in results


def test_index_task(search_index: SearchIndex) -> None:
    """Test indexing a task."""
    task = Task(
        id="t1",
        project_id="p1",
        title="Implement feature",
        status="todo",
        created_at="2024-01-01T10:00:00Z"
    )
    
    search_index.index_task(task, project_name="Test Project", entry_title="Planning")
    
    stats = search_index.get_stats()
    assert stats["tasks"] == 1


def test_search_tasks(search_index: SearchIndex) -> None:
    """Test searching tasks."""
    tasks_data = [
        (
            Task(
                id="t1",
                project_id="p1",
                title="Fix bug in authentication",
                status="todo",
                created_at="2024-01-01T10:00:00Z"
            ),
            "Backend",
            None
        ),
        (
            Task(
                id="t2",
                project_id="p2",
                title="Update UI components",
                status="in_progress",
                created_at="2024-01-02T10:00:00Z"
            ),
            "Frontend",
            "Design Meeting"
        ),
    ]
    
    search_index.index_tasks_bulk(tasks_data)
    
    # Search for "bug"
    results = search_index.search_tasks("bug")
    assert len(results) == 1
    assert "t1" in results
    
    # Search for "UI"
    results = search_index.search_tasks("UI")
    assert len(results) == 1
    assert "t2" in results


def test_bulk_indexing_performance(search_index: SearchIndex) -> None:
    """Test bulk indexing performance (should be < 100ms for 1K entries)."""
    import time
    
    # Create 1000 entries
    entries = [_make_entry(f"e{i}", f"Entry {i}", f"Content {i}") for i in range(1000)]
    
    start = time.perf_counter()
    search_index.index_entries_bulk(entries)
    elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
    
    assert elapsed < 100  # Should be well under 100ms for 1K entries
    assert search_index.get_stats()["entries"] == 1000


def test_rebuild_index(search_index: SearchIndex) -> None:
    """Test rebuilding entire index."""
    entries = [_make_entry("e1", "Entry 1", "Content 1")]
    
    projects = [
        Project(
            id="p1",
            name="Project 1",
            description="Description",
            status="active",
            tags=[],
            created_at="2024-01-01T10:00:00Z"
        ),
    ]
    
    tasks_data = [
        (
            Task(
                id="t1",
                project_id="p1",
                title="Task 1",
                status="todo",
                created_at="2024-01-01T10:00:00Z"
            ),
            "Project 1",
            "Entry 1"
        ),
    ]
    
    stats = search_index.rebuild(entries, projects, tasks_data)
    
    assert stats["entries"] == 1
    assert stats["projects"] == 1
    assert stats["tasks"] == 1
    
    # Verify data is searchable
    assert len(search_index.search_entries("Entry")) == 1
    assert len(search_index.search_projects("Project")) == 1
    assert len(search_index.search_tasks("Task")) == 1


def test_fts_query_syntax(search_index: SearchIndex) -> None:
    """Test FTS5 query syntax features."""
    entries = [
        _make_entry("e1", "Important Meeting Notes", "Discussed project timeline", tags=["important"]),
        _make_entry("e2", "Regular Standup", "Quick team sync", tags=["standup"]),
    ]
    
    search_index.index_entries_bulk(entries)
    
    # Test AND query
    results = search_index.search_entries("Meeting AND Important")
    assert len(results) == 1
    assert "e1" in results
    
    # Test OR query
    results = search_index.search_entries("standup OR timeline")
    assert len(results) == 2


def test_close_connection(search_index: SearchIndex) -> None:
    """Test closing database connection."""
    search_index.close()
    # Should be able to reopen
    stats = search_index.get_stats()
    assert "entries" in stats
