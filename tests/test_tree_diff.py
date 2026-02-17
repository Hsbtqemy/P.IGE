"""Tests for tree diff calculator."""

from __future__ import annotations

import pytest

from pige.interfaces.gui.tree_diff import (
    TreeNode,
    compute_tree_diff,
    tree_from_items,
)


def test_compute_diff_no_changes():
    """Test diff when trees are identical."""
    nodes = {
        "a": TreeNode("a", None, ("A",), None),
        "b": TreeNode("b", "a", ("B",), None),
    }
    
    diff = compute_tree_diff(nodes, nodes)
    
    assert len(diff.added) == 0
    assert len(diff.removed) == 0
    assert len(diff.modified) == 0


def test_compute_diff_added_nodes():
    """Test diff with added nodes."""
    old_nodes = {
        "a": TreeNode("a", None, ("A",), None),
    }
    
    new_nodes = {
        "a": TreeNode("a", None, ("A",), None),
        "b": TreeNode("b", "a", ("B",), None),
        "c": TreeNode("c", None, ("C",), None),
    }
    
    diff = compute_tree_diff(old_nodes, new_nodes)
    
    assert len(diff.added) == 2
    assert len(diff.removed) == 0
    added_ids = {node.id for node in diff.added}
    assert added_ids == {"b", "c"}


def test_compute_diff_removed_nodes():
    """Test diff with removed nodes."""
    old_nodes = {
        "a": TreeNode("a", None, ("A",), None),
        "b": TreeNode("b", "a", ("B",), None),
        "c": TreeNode("c", None, ("C",), None),
    }
    
    new_nodes = {
        "a": TreeNode("a", None, ("A",), None),
    }
    
    diff = compute_tree_diff(old_nodes, new_nodes)
    
    assert len(diff.added) == 0
    assert len(diff.removed) == 2
    assert set(diff.removed) == {"b", "c"}


def test_compute_diff_modified_values():
    """Test diff with modified node values."""
    old_nodes = {
        "a": TreeNode("a", None, ("A", "old"),  None),
        "b": TreeNode("b", "a", ("B", "100"), None),
    }
    
    new_nodes = {
        "a": TreeNode("a", None, ("A", "new"), None),
        "b": TreeNode("b", "a", ("B", "200"), None),
    }
    
    diff = compute_tree_diff(old_nodes, new_nodes)
    
    assert len(diff.added) == 0
    assert len(diff.removed) == 0
    assert len(diff.modified) == 2
    
    modified_dict = dict(diff.modified)
    assert modified_dict["a"] == ("A", "new")
    assert modified_dict["b"] == ("B", "200")


def test_compute_diff_expand_state_changed():
    """Test diff with expand/collapse state changes."""
    old_nodes = {
        "a": TreeNode("a", None, ("A",), None, open=False),
        "b": TreeNode("b", None, ("B",), None, open=True),
    }
    
    new_nodes = {
        "a": TreeNode("a", None, ("A",), None, open=True),
        "b": TreeNode("b", None, ("B",), None, open=False),
    }
    
    diff = compute_tree_diff(old_nodes, new_nodes)
    
    assert len(diff.expand_changed) == 2
    expand_dict = dict(diff.expand_changed)
    assert expand_dict["a"] is True
    assert expand_dict["b"] is False


def test_compute_diff_mixed_changes():
    """Test diff with multiple types of changes."""
    old_nodes = {
        "a": TreeNode("a", None, ("A", "1"), None),
        "b": TreeNode("b", "a", ("B", "2"), None),
        "c": TreeNode("c", None, ("C", "3"), None),
    }
    
    new_nodes = {
        "a": TreeNode("a", None, ("A", "1-modified"), None),  # Modified
        "b": TreeNode("b", "a", ("B", "2"), None),  # Unchanged
        "d": TreeNode("d", "a", ("D", "4"), None),  # Added
        # "c" removed
    }
    
    diff = compute_tree_diff(old_nodes, new_nodes)
    
    assert len(diff.added) == 1
    assert diff.added[0].id == "d"
    
    assert len(diff.removed) == 1
    assert "c" in diff.removed
    
    assert len(diff.modified) == 1
    assert diff.modified[0] == ("a", ("A", "1-modified"))


def test_tree_from_items():
    """Test building tree nodes from data items."""
    
    class Item:
        def __init__(self, id, parent, name, count):
            self.id = id
            self.parent = parent
            self.name = name
            self.count = count
    
    items = [
        Item("a", None, "Item A", 10),
        Item("b", "a", "Item B", 20),
        Item("c", None, "Item C", 30),
    ]
    
    nodes = tree_from_items(
        items,
        id_getter=lambda item: item.id,
        parent_getter=lambda item: item.parent,
        values_getter=lambda item: (item.name, str(item.count)),
    )
    
    assert len(nodes) == 3
    assert nodes["a"].id == "a"
    assert nodes["a"].parent_id is None
    assert nodes["a"].values == ("Item A", "10")
    
    assert nodes["b"].parent_id == "a"
    assert nodes["c"].parent_id is None


def test_tree_from_items_with_tags():
    """Test building tree nodes with tags."""
    
    class Item:
        def __init__(self, id, name, active):
            self.id = id
            self.name = name
            self.active = active
    
    items = [
        Item("a", "Active Item", True),
        Item("b", "Inactive Item", False),
    ]
    
    nodes = tree_from_items(
        items,
        id_getter=lambda i: i.id,
        parent_getter=lambda i: None,
        values_getter=lambda i: (i.name,),
        tags_getter=lambda i: ("active",) if i.active else ("inactive",),
    )
    
    assert nodes["a"].tags == ("active",)
    assert nodes["b"].tags == ("inactive",)


def test_compute_diff_reorder_detection():
    """Test detection of node reordering within parent."""
    old_nodes = {
        "a": TreeNode("a", None, ("A",), None),
        "b": TreeNode("b", None, ("B",), None),
        "c": TreeNode("c", None, ("C",), None),
    }
    
    # Same nodes, different order
    new_nodes = {
        "c": TreeNode("c", None, ("C",), None),
        "a": TreeNode("a", None, ("A",), None),
        "b": TreeNode("b", None, ("B",), None),
    }
    
    diff = compute_tree_diff(old_nodes, new_nodes)
    
    # Reorder should be detected
    assert len(diff.reordered) > 0
    assert len(diff.added) == 0
    assert len(diff.removed) == 0


def test_diff_with_hierarchy():
    """Test diff with parent-child relationships."""
    old_nodes = {
        "root": TreeNode("root", None, ("Root",), None),
        "child1": TreeNode("child1", "root", ("Child 1",), None),
        "child2": TreeNode("child2", "root", ("Child 2",), None),
    }
    
    new_nodes = {
        "root": TreeNode("root", None, ("Root",), None),
        "child1": TreeNode("child1", "root", ("Child 1 Updated",), None),
        "child3": TreeNode("child3", "root", ("Child 3",), None),
        # child2 removed, child3 added, child1 modified
    }
    
    diff = compute_tree_diff(old_nodes, new_nodes)
    
    assert len(diff.removed) == 1
    assert "child2" in diff.removed
    
    assert len(diff.added) == 1
    assert diff.added[0].id == "child3"
    
    assert len(diff.modified) == 1
    assert diff.modified[0] == ("child1", ("Child 1 Updated",))
