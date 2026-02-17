"""Tests for service-level hierarchy operations."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pige.core.service import PigeService
from pige.core.storage import Storage


class TestServiceHierarchy(unittest.TestCase):
    def _build_service(self, data_dir: str) -> PigeService:
        storage = Storage(Path(data_dir))
        storage.init_storage()
        return PigeService(storage)

    def test_create_project_with_parent(self) -> None:
        """create_project can create a child project."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            parent = service.create_project("Parent", "Desc", [])
            child = service.create_project("Child", "Child desc", [], parent_id=parent.id)
            
            self.assertEqual(child.parent_id, parent.id)
            self.assertEqual(child.display_order, 0)  # First child

    def test_create_project_validates_parent_exists(self) -> None:
        """create_project raises if parent doesn't exist."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            with self.assertRaises(ValueError):
                service.create_project("Child", "Desc", [], parent_id="nonexistent")

    def test_create_project_enforces_max_depth(self) -> None:
        """create_project prevents excessive nesting (max 10 levels)."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            # Create a deep hierarchy (10 levels: 0-9)
            current_parent = None
            for i in range(10):
                project = service.create_project(f"Level {i}", f"Desc {i}", [], parent_id=current_parent)
                current_parent = project.id
            
            # Trying to create an 11th level should fail
            with self.assertRaises(ValueError) as ctx:
                service.create_project("Too deep", "Desc", [], parent_id=current_parent)
            self.assertIn("maximum", str(ctx.exception).lower())
            self.assertIn("depth", str(ctx.exception).lower())

    def test_get_project_depth(self) -> None:
        """get_project_depth returns correct depth."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            root = service.create_project("Root", "Desc", [])
            level1 = service.create_project("Level 1", "Desc", [], parent_id=root.id)
            level2 = service.create_project("Level 2", "Desc", [], parent_id=level1.id)
            
            self.assertEqual(service.get_project_depth(root.id), 0)
            self.assertEqual(service.get_project_depth(level1.id), 1)
            self.assertEqual(service.get_project_depth(level2.id), 2)

    def test_move_project_validates_depth(self) -> None:
        """move_project prevents moves that would exceed max depth."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            # Create a deep hierarchy at root (10 levels: 0-9)
            current = None
            projects = []
            for i in range(10):  # Create 10 levels (0-9)
                p = service.create_project(f"Deep {i}", f"Desc {i}", [], parent_id=current)
                projects.append(p)
                current = p.id
            
            # Create a separate root project
            branch = service.create_project("Branch", "Desc", [])
            
            # Trying to move the top of the deep hierarchy under branch would exceed 10 levels
            # (branch is at 0, moving projects[0] puts it at 1, deepest descendant would be at 10)
            with self.assertRaises(ValueError) as ctx:
                service.move_project(projects[0].id, branch.id)
            self.assertIn("depth", str(ctx.exception).lower())

    def test_reorder_projects_in_parent(self) -> None:
        """reorder_projects_in_parent changes display order."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            p1 = service.create_project("First", "Desc", [])
            p2 = service.create_project("Second", "Desc", [])
            p3 = service.create_project("Third", "Desc", [])
            
            # Reverse order
            service.reorder_projects_in_parent([p3.id, p2.id, p1.id], parent_id=None)
            
            projects = service.storage.read_projects()
            p1_loaded = next(p for p in projects if p.id == p1.id)
            p2_loaded = next(p for p in projects if p.id == p2.id)
            p3_loaded = next(p for p in projects if p.id == p3.id)
            
            self.assertEqual(p3_loaded.display_order, 0)
            self.assertEqual(p2_loaded.display_order, 1)
            self.assertEqual(p1_loaded.display_order, 2)

    def test_get_project_tree(self) -> None:
        """get_project_tree returns hierarchical structure."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            root1 = service.create_project("Root 1", "Desc", [])
            root2 = service.create_project("Root 2", "Desc", [])
            child1 = service.create_project("Child 1", "Desc", [], parent_id=root1.id)
            grandchild = service.create_project("Grandchild", "Desc", [], parent_id=child1.id)
            
            tree = service.get_project_tree()
            
            # Should have 2 root nodes
            self.assertEqual(len(tree), 2)
            
            # First root should have 1 child
            root1_node = next(n for n in tree if n["project"].id == root1.id)
            self.assertEqual(len(root1_node["children"]), 1)
            self.assertEqual(root1_node["depth"], 0)
            
            # Child should have 1 grandchild
            child1_node = root1_node["children"][0]
            self.assertEqual(child1_node["project"].id, child1.id)
            self.assertEqual(len(child1_node["children"]), 1)
            self.assertEqual(child1_node["depth"], 1)
            
            # Grandchild should have no children
            grandchild_node = child1_node["children"][0]
            self.assertEqual(grandchild_node["project"].id, grandchild.id)
            self.assertEqual(len(grandchild_node["children"]), 0)
            self.assertEqual(grandchild_node["depth"], 2)

    def test_create_project_sets_correct_display_order(self) -> None:
        """create_project appends new projects at end of siblings."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            parent = service.create_project("Parent", "Desc", [])
            
            child1 = service.create_project("Child 1", "Desc", [], parent_id=parent.id)
            child2 = service.create_project("Child 2", "Desc", [], parent_id=parent.id)
            child3 = service.create_project("Child 3", "Desc", [], parent_id=parent.id)
            
            self.assertEqual(child1.display_order, 0)
            self.assertEqual(child2.display_order, 1)
            self.assertEqual(child3.display_order, 2)

    def test_export_project_hierarchy(self) -> None:
        """export_project_hierarchy generates indented Markdown."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            
            # Create hierarchy
            root1 = service.create_project("Root 1", "First root", ["tag1"])
            root2 = service.create_project("Root 2", "Second root", [])
            child1 = service.create_project("Child 1.1", "First child", [], parent_id=root1.id)
            grandchild = service.create_project("Grandchild 1.1.1", "Grand", [], parent_id=child1.id)
            
            # Add an entry to root1
            service.add_entry(
                root1.id,
                "note",
                "Test Entry",
                tags=[],
                body="Test content",
            )
            
            # Export
            export_path = service.export_project_hierarchy()
            
            self.assertTrue(export_path.exists())
            content = export_path.read_text(encoding="utf-8")
            
            # Check structure
            self.assertIn("# Project Hierarchy", content)
            self.assertIn("Root 1", content)
            self.assertIn("Root 2", content)
            self.assertIn("Child 1.1", content)
            self.assertIn("Grandchild 1.1.1", content)
            
            # Check indentation (child should be indented with "  -")
            self.assertIn("  - **Child 1.1**", content)
            self.assertIn("    - **Grandchild 1.1.1**", content)
            
            # Check metadata
            self.assertIn("1 entries", content)  # root1 has 1 entry
            self.assertIn("Folder", content)  # Projects with children
            self.assertIn("File", content)  # Projects without children
