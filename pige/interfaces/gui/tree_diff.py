"""Tree diff calculator for incremental TreeView updates.

This module provides utilities to compute diffs between TreeView states
and apply incremental updates to avoid flickering and preserve scroll/selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class TreeNode(Generic[T]):
    """Represents a node in the tree structure."""
    
    id: str
    parent_id: str | None
    values: tuple[Any, ...]
    data: T
    tags: tuple[str, ...] = ()
    open: bool = False


@dataclass
class TreeDiff:
    """Represents changes between two tree states."""
    
    added: list[TreeNode]  # Nodes to add
    removed: list[str]  # Node IDs to remove
    modified: list[tuple[str, tuple[Any, ...]]]  # (node_id, new_values)
    reordered: list[tuple[str, int]]  # (node_id, new_index) for position changes
    expand_changed: list[tuple[str, bool]]  # (node_id, new_open_state)


def compute_tree_diff(
    old_nodes: dict[str, TreeNode],
    new_nodes: dict[str, TreeNode],
) -> TreeDiff:
    """Compute diff between two tree states.
    
    Args:
        old_nodes: Dict of {node_id: TreeNode} for current state
        new_nodes: Dict of {node_id: TreeNode} for target state
    
    Returns:
        TreeDiff with all changes needed to transform old to new
    """
    added = []
    removed = []
    modified = []
    reordered = []
    expand_changed = []
    
    old_ids = set(old_nodes.keys())
    new_ids = set(new_nodes.keys())
    
    # Find removed nodes
    removed = list(old_ids - new_ids)
    
    # Find added nodes
    for node_id in (new_ids - old_ids):
        added.append(new_nodes[node_id])
    
    # Find modified nodes (values changed)
    for node_id in (old_ids & new_ids):
        old_node = old_nodes[node_id]
        new_node = new_nodes[node_id]
        
        if old_node.values != new_node.values:
            modified.append((node_id, new_node.values))
        
        if old_node.open != new_node.open:
            expand_changed.append((node_id, new_node.open))
    
    # Find reordered nodes (check siblings order)
    # Group by parent to check order within each level
    old_by_parent: dict[str | None, list[str]] = {}
    new_by_parent: dict[str | None, list[str]] = {}
    
    for node_id, node in old_nodes.items():
        parent = node.parent_id
        if parent not in old_by_parent:
            old_by_parent[parent] = []
        old_by_parent[parent].append(node_id)
    
    for node_id, node in new_nodes.items():
        parent = node.parent_id
        if parent not in new_by_parent:
            new_by_parent[parent] = []
        new_by_parent[parent].append(node_id)
    
    # Check if order changed within each parent group
    for parent_id in new_by_parent:
        old_children = old_by_parent.get(parent_id, [])
        new_children = new_by_parent[parent_id]
        
        # Filter out removed/added nodes for fair comparison
        old_existing = [nid for nid in old_children if nid in new_ids]
        new_existing = [nid for nid in new_children if nid in old_ids]
        
        if old_existing != new_existing:
            # Order changed
            for idx, node_id in enumerate(new_children):
                reordered.append((node_id, idx))
    
    return TreeDiff(
        added=added,
        removed=removed,
        modified=modified,
        reordered=reordered,
        expand_changed=expand_changed
    )


def tree_from_items(items: list[T], id_getter, parent_getter, values_getter, tags_getter=None, open_getter=None) -> dict[str, TreeNode[T]]:
    """Build tree node dict from list of items.
    
    Args:
        items: List of data items
        id_getter: Function to extract ID from item
        parent_getter: Function to extract parent ID from item
        values_getter: Function to extract TreeView values tuple from item
        tags_getter: Optional function to extract tags tuple
        open_getter: Optional function to get open state
    
    Returns:
        Dict of {node_id: TreeNode}
    """
    nodes = {}
    
    for item in items:
        node_id = id_getter(item)
        parent_id = parent_getter(item)
        values = values_getter(item)
        tags = tags_getter(item) if tags_getter else ()
        open_state = open_getter(item) if open_getter else False
        
        nodes[node_id] = TreeNode(
            id=node_id,
            parent_id=parent_id,
            values=values,
            data=item,
            tags=tags,
            open=open_state
        )
    
    return nodes


class IncrementalTreeView:
    """Helper for incremental TreeView updates with diff-based approach."""
    
    def __init__(self, treeview):
        """Initialize with a Tkinter TreeView widget.
        
        Args:
            treeview: tkinter.ttk.Treeview instance
        """
        self.tree = treeview
        self._snapshot: dict[str, TreeNode] | None = None
    
    def snapshot_state(self) -> None:
        """Capture current tree state for future diffs."""
        nodes = {}
        
        def capture_recursive(item_id: str, parent_id: str | None = None):
            values = self.tree.item(item_id, "values")
            tags = self.tree.item(item_id, "tags")
            open_state = self.tree.item(item_id, "open")
            
            nodes[item_id] = TreeNode(
                id=item_id,
                parent_id=parent_id,
                values=tuple(values) if values else (),
                data=None,  # We don't store original data in snapshot
                tags=tuple(tags) if tags else (),
                open=bool(open_state)
            )
            
            # Capture children recursively
            for child_id in self.tree.get_children(item_id):
                capture_recursive(child_id, item_id)
        
        # Capture all root items
        for root_id in self.tree.get_children():
            capture_recursive(root_id)
        
        self._snapshot = nodes
    
    def apply_diff(
        self,
        new_nodes: dict[str, TreeNode],
        preserve_selection: bool = True,
        preserve_scroll: bool = True
    ) -> None:
        """Apply incremental update using diff.
        
        Args:
            new_nodes: Target tree state
            preserve_selection: Whether to restore selection after update
            preserve_scroll: Whether to preserve scroll position
        """
        if self._snapshot is None:
            # First update, no diff needed - full rebuild
            self._rebuild_tree(new_nodes)
            self.snapshot_state()
            return
        
        # Compute diff
        diff = compute_tree_diff(self._snapshot, new_nodes)
        
        # Save state to restore
        selected = self.tree.selection() if preserve_selection else ()
        yview = self.tree.yview() if preserve_scroll else None
        
        # Apply changes in order: remove, modify, add, reorder
        
        # 1. Remove nodes (bottom-up to avoid issues)
        for node_id in diff.removed:
            if self.tree.exists(node_id):
                self.tree.delete(node_id)
        
        # 2. Modify existing nodes (update values)
        for node_id, new_values in diff.modified:
            if self.tree.exists(node_id):
                self.tree.item(node_id, values=new_values)
        
        # 3. Add new nodes (must add parents before children)
        # Sort by depth (root first)
        def get_depth(node: TreeNode) -> int:
            depth = 0
            current = node
            while current.parent_id:
                depth += 1
                current = new_nodes.get(current.parent_id)
                if not current:
                    break
            return depth
        
        added_sorted = sorted(diff.added, key=get_depth)
        
        for node in added_sorted:
            parent_iid = node.parent_id or ""
            # Find insertion index (append to end by default)
            self.tree.insert(
                parent_iid,
                "end",
                iid=node.id,
                values=node.values,
                tags=node.tags,
                open=node.open
            )
        
        # 4. Handle expand/collapse state changes
        for node_id, new_open_state in diff.expand_changed:
            if self.tree.exists(node_id):
                self.tree.item(node_id, open=new_open_state)
        
        # 5. Reorder nodes (if needed)
        # Note: Tkinter TreeView doesn't have direct "move" - must delete+reinsert
        # For now, skip reordering to avoid flickering (can be added later)
        
        # Restore state
        if preserve_selection and selected:
            # Only restore selection for items that still exist
            valid_selection = [item for item in selected if self.tree.exists(item)]
            if valid_selection:
                self.tree.selection_set(valid_selection)
        
        if preserve_scroll and yview:
            self.tree.yview_moveto(yview[0])
        
        # Update snapshot
        self._snapshot = new_nodes
    
    def _rebuild_tree(self, nodes: dict[str, TreeNode]) -> None:
        """Full rebuild (used for first load). Preserves insertion order of nodes at same depth."""
        self.tree.delete(*self.tree.get_children())
        order_list = list(nodes.keys())  # insertion order (Python 3.7+)

        def get_depth(node: TreeNode) -> int:
            depth = 0
            current = node
            while current.parent_id and current.parent_id in nodes:
                depth += 1
                current = nodes[current.parent_id]
            return depth

        def sort_key(node: TreeNode):
            idx = order_list.index(node.id) if node.id in order_list else 9999
            return (get_depth(node), idx)

        sorted_nodes = sorted(nodes.values(), key=sort_key)

        for node in sorted_nodes:
            parent_iid = node.parent_id or ""
            self.tree.insert(
                parent_iid,
                "end",
                iid=node.id,
                values=node.values,
                tags=node.tags,
                open=node.open
            )
