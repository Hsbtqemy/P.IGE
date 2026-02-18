"""Tests for SearchPanel GUI component."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from pige.core.service import PigeService
from pige.core.storage import Storage
from pige.interfaces.gui.panels.search_panel import SearchPanel


@pytest.fixture
def temp_service():
    """Create a temporary service with test data."""
    with TemporaryDirectory() as tmpdir:
        storage = Storage(Path(tmpdir))
        service = PigeService(storage)
        service.init_storage()
        
        # Create test project
        project = service.create_project("Test Project", None, [])
        
        # Create test entries
        entry1, _ = service.add_entry(
            project_id=project.id,
            entry_type="note",
            title="Test Entry Alpha",
            tags=["test", "alpha"],
            body="This is a test entry with alpha keyword."
        )
        
        entry2, _ = service.add_entry(
            project_id=project.id,
            entry_type="meeting",
            title="Meeting Notes Beta",
            tags=["meeting", "beta"],
            body="Meeting notes with beta keyword."
        )
        
        # Rebuild search index
        service.storage.rebuild_search_index()
        
        yield service


def test_search_panel_creation(temp_service):
    """Test SearchPanel can be created."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        assert panel.service == temp_service
        assert panel.search_var is not None
        assert panel.search_type_var is not None
        assert panel.results_tree is not None
        assert panel.status_label is not None
        
    finally:
        root.destroy()


def test_search_panel_initial_state(temp_service):
    """Test SearchPanel initial state."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        assert panel.search_var.get() == ""
        assert panel.search_type_var.get() == "All"
        assert len(panel.current_results) == 0
        assert len(panel.results_tree.get_children()) == 0
        
    finally:
        root.destroy()


def test_search_entries(temp_service):
    """Test searching for entries."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        # Search for "alpha"
        panel.search_var.set("alpha")
        panel.search_type_var.set("Entries")
        panel.perform_search()
        
        # Should find 1 result
        assert len(panel.current_results) > 0
        result_type, result_id, result_title = panel.current_results[0]
        assert result_type == "entry"
        assert "Alpha" in result_title
        
    finally:
        root.destroy()


def test_search_all_types(temp_service):
    """Test searching across all types."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        # Search for "test" (should find project and entry)
        panel.search_var.set("test")
        panel.search_type_var.set("All")
        panel.perform_search()
        
        # Should find multiple results
        assert len(panel.current_results) >= 1
        
    finally:
        root.destroy()


def test_search_no_results(temp_service):
    """Test search with no results."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        # Search for something that doesn't exist
        panel.search_var.set("xyznonexistent")
        panel.perform_search()
        
        # Should find no results
        assert len(panel.current_results) == 0
        assert "No results found" in panel.status_label.cget("text")
        
    finally:
        root.destroy()


def test_search_empty_query(temp_service):
    """Test search with empty query."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        # Try to search with empty query
        panel.search_var.set("")
        panel.perform_search()
        
        # Should show warning
        assert "enter a search query" in panel.status_label.cget("text").lower()
        
    finally:
        root.destroy()


def test_clear_search(temp_service):
    """Test clearing search results."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        # Perform a search first
        panel.search_var.set("test")
        panel.perform_search()
        
        assert len(panel.current_results) > 0
        
        # Clear search
        panel.clear_search()
        
        assert panel.search_var.get() == ""
        assert len(panel.current_results) == 0
        assert len(panel.results_tree.get_children()) == 0
        
    finally:
        root.destroy()


def test_result_selection_callback(temp_service):
    """Test result selection triggers callback."""
    root = tk.Tk()
    try:
        callback_mock = MagicMock()
        panel = SearchPanel(root, temp_service, on_result_selected=callback_mock)
        
        # Perform search
        panel.search_var.set("alpha")
        panel.perform_search()
        
        # Simulate selection
        if panel.current_results:
            # Trigger double-click event
            panel._on_result_double_click()
            
            # Callback should have been called
            callback_mock.assert_called_once()
            
            result_type, result_id = callback_mock.call_args[0]
            assert result_type == "entry"
            assert result_id is not None
        
    finally:
        root.destroy()


def test_focus_search(temp_service):
    """Test focus_search sets focus to input."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        panel.search_var.set("test query")
        
        # Focus should work (note: actual focus requires window to be visible)
        panel.focus_search()
        
        # Input should be selected
        assert panel.search_entry.selection_present()
        
    finally:
        root.destroy()


def test_search_performance(temp_service):
    """Test search completes quickly."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        # Perform search
        panel.search_var.set("test")
        panel.perform_search()
        
        # Check status shows timing
        status_text = panel.status_label.cget("text")
        assert "ms" in status_text
        
        # Extract timing (should be < 100ms)
        import re
        match = re.search(r"(\d+\.?\d*)ms", status_text)
        if match:
            elapsed_ms = float(match.group(1))
            assert elapsed_ms < 100  # Should be very fast
        
    finally:
        root.destroy()


def test_search_types_dropdown(temp_service):
    """Test search type dropdown has correct values."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        assert panel.SEARCH_TYPES == ["All", "Entries", "Projects", "Tasks"]
        assert panel.search_type_var.get() == "All"  # Default
        
    finally:
        root.destroy()


def test_search_error_handling(temp_service):
    """Test search handles errors gracefully."""
    root = tk.Tk()
    try:
        panel = SearchPanel(root, temp_service)
        
        # Mock search_entries to raise an error
        with patch.object(
            panel.service.storage,
            '_get_search_index',
            side_effect=Exception("Test error")
        ):
            panel.search_var.set("test")
            panel.perform_search()
            
            # Should show error message
            status_text = panel.status_label.cget("text")
            assert "error" in status_text.lower()
        
    finally:
        root.destroy()
