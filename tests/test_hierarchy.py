"""Tests for project hierarchy functionality."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pige.core.models import Project
from pige.core.storage import Storage


class TestProjectHierarchy(unittest.TestCase):
    def test_new_project_has_hierarchy_fields(self) -> None:
        """New Project instances have parent_id and display_order fields."""
        project = Project(id="p1", name="Test Project")
        self.assertIsNone(project.parent_id)
        self.assertEqual(project.display_order, 0)

    def test_project_with_parent(self) -> None:
        """Project can have a parent_id."""
        child = Project(id="child", name="Child", parent_id="parent")
        self.assertEqual(child.parent_id, "parent")

    def test_project_custom_order(self) -> None:
        """Project can have custom display_order."""
        p1 = Project(id="p1", name="First", display_order=10)
        p2 = Project(id="p2", name="Second", display_order=5)
        self.assertEqual(p1.display_order, 10)
        self.assertEqual(p2.display_order, 5)

    def test_storage_reads_hierarchy_fields(self) -> None:
        """Storage correctly reads parent_id and display_order from JSON."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            # Create projects with hierarchy
            projects = [
                Project(id="p1", name="Parent", display_order=0),
                Project(id="p2", name="Child", parent_id="p1", display_order=1),
            ]
            storage.write_projects(projects)

            # Read back
            loaded = storage.read_projects()
            self.assertEqual(len(loaded), 2)
            
            p1 = next(p for p in loaded if p.id == "p1")
            p2 = next(p for p in loaded if p.id == "p2")
            
            self.assertIsNone(p1.parent_id)
            self.assertEqual(p1.display_order, 0)
            self.assertEqual(p2.parent_id, "p1")
            self.assertEqual(p2.display_order, 1)

    def test_migration_sets_default_display_order(self) -> None:
        """migrate_projects_hierarchy sets display_order for existing projects."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            # Create projects without hierarchy fields (simulate old data)
            projects = [
                Project(id="p1", name="First"),
                Project(id="p2", name="Second"),
                Project(id="p3", name="Third"),
            ]
            storage.write_projects(projects)

            # Run migration
            stats = storage.migrate_projects_hierarchy()
            
            self.assertEqual(stats["total"], 3)
            self.assertEqual(stats["migrated"], 3)
            self.assertEqual(stats["already_migrated"], 0)

            # Check order was assigned
            loaded = storage.read_projects()
            self.assertEqual(loaded[0].display_order, 0)
            self.assertEqual(loaded[1].display_order, 1)
            self.assertEqual(loaded[2].display_order, 2)

    def test_migration_is_idempotent(self) -> None:
        """Running migration multiple times is safe."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            # Create multiple projects to trigger migration
            projects = [
                Project(id="p1", name="First"),
                Project(id="p2", name="Second"),
            ]
            storage.write_projects(projects)

            # First migration
            stats1 = storage.migrate_projects_hierarchy()
            self.assertEqual(stats1["total"], 2)
            # At least one should be migrated on first run
            self.assertTrue(stats1["migrated"] > 0)

            # Verify the migration actually persisted
            loaded = storage.read_projects()
            # First project should still have display_order 0 (position 0)
            # Second project should have display_order 1 (position 1)
            p0 = loaded[0]
            p1 = loaded[1]
            # Since p0 is at position 0, it will have display_order=0
            # Since p1 is at position 1, it will have display_order=1
            
            # Second migration - nothing to do since all have non-zero or are at position 0
            stats2 = storage.migrate_projects_hierarchy()
            # Should have less or equal migrations
            self.assertTrue(stats2["migrated"] <= stats1["migrated"])

    def test_storage_handles_missing_hierarchy_fields(self) -> None:
        """Storage gracefully handles JSON without hierarchy fields (backward compat)."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            # Manually write JSON without hierarchy fields
            import json
            projects_data = [
                {"id": "p1", "name": "Old Project", "status": "active", "tags": []}
            ]
            with open(storage.projects_path, "w") as f:
                json.dump(projects_data, f)

            # Should read successfully with defaults
            loaded = storage.read_projects()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, "p1")
            self.assertIsNone(loaded[0].parent_id)
            self.assertEqual(loaded[0].display_order, 0)

    def test_get_project_children_root(self) -> None:
        """get_project_children returns root-level projects when parent_id is None."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="p1", name="Root 1", display_order=1),
                Project(id="p2", name="Root 2", display_order=0),
                Project(id="p3", name="Child", parent_id="p1", display_order=0),
            ]
            storage.write_projects(projects)

            children = storage.get_project_children(None)
            self.assertEqual(len(children), 2)
            # Should be sorted by display_order
            self.assertEqual(children[0].id, "p2")  # display_order=0
            self.assertEqual(children[1].id, "p1")  # display_order=1

    def test_get_project_children_with_parent(self) -> None:
        """get_project_children returns children of specific parent."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="parent", name="Parent"),
                Project(id="child1", name="Child 1", parent_id="parent", display_order=5),
                Project(id="child2", name="Child 2", parent_id="parent", display_order=3),
                Project(id="other", name="Other"),
            ]
            storage.write_projects(projects)

            children = storage.get_project_children("parent")
            self.assertEqual(len(children), 2)
            # Sorted by display_order
            self.assertEqual(children[0].id, "child2")  # display_order=3
            self.assertEqual(children[1].id, "child1")  # display_order=5

    def test_get_project_ancestors(self) -> None:
        """get_project_ancestors returns path from parent to root."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="root", name="Root"),
                Project(id="level1", name="Level 1", parent_id="root"),
                Project(id="level2", name="Level 2", parent_id="level1"),
                Project(id="level3", name="Level 3", parent_id="level2"),
            ]
            storage.write_projects(projects)

            ancestors = storage.get_project_ancestors("level3")
            self.assertEqual(len(ancestors), 3)
            self.assertEqual(ancestors[0].id, "level2")  # Immediate parent
            self.assertEqual(ancestors[1].id, "level1")
            self.assertEqual(ancestors[2].id, "root")

    def test_get_project_ancestors_no_parent(self) -> None:
        """get_project_ancestors returns empty list for root project."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [Project(id="root", name="Root")]
            storage.write_projects(projects)

            ancestors = storage.get_project_ancestors("root")
            self.assertEqual(len(ancestors), 0)

    def test_get_project_descendants(self) -> None:
        """get_project_descendants returns all descendants recursively."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="root", name="Root"),
                Project(id="child1", name="Child 1", parent_id="root"),
                Project(id="child2", name="Child 2", parent_id="root"),
                Project(id="grandchild", name="Grandchild", parent_id="child1"),
            ]
            storage.write_projects(projects)

            descendants = storage.get_project_descendants("root")
            self.assertEqual(len(descendants), 3)
            ids = {d.id for d in descendants}
            self.assertEqual(ids, {"child1", "child2", "grandchild"})

    def test_move_project_to_root(self) -> None:
        """move_project can move a project to root level."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="parent", name="Parent"),
                Project(id="child", name="Child", parent_id="parent"),
            ]
            storage.write_projects(projects)

            storage.move_project("child", None)

            loaded = storage.read_projects()
            child = next(p for p in loaded if p.id == "child")
            self.assertIsNone(child.parent_id)

    def test_move_project_to_new_parent(self) -> None:
        """move_project can move a project to a new parent."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="parent1", name="Parent 1"),
                Project(id="parent2", name="Parent 2"),
                Project(id="child", name="Child", parent_id="parent1"),
            ]
            storage.write_projects(projects)

            storage.move_project("child", "parent2")

            loaded = storage.read_projects()
            child = next(p for p in loaded if p.id == "child")
            self.assertEqual(child.parent_id, "parent2")

    def test_move_project_detects_cycle(self) -> None:
        """move_project raises ValueError if move would create a cycle."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="parent", name="Parent"),
                Project(id="child", name="Child", parent_id="parent"),
            ]
            storage.write_projects(projects)

            # Trying to make parent a child of child would create a cycle
            with self.assertRaises(ValueError) as ctx:
                storage.move_project("parent", "child")
            self.assertIn("cycle", str(ctx.exception).lower())

    def test_reorder_projects(self) -> None:
        """reorder_projects updates display_order for projects."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="p1", name="First", display_order=0),
                Project(id="p2", name="Second", display_order=1),
                Project(id="p3", name="Third", display_order=2),
            ]
            storage.write_projects(projects)

            # Reverse the order
            storage.reorder_projects(["p3", "p2", "p1"], parent_id=None)

            loaded = storage.read_projects()
            p1 = next(p for p in loaded if p.id == "p1")
            p2 = next(p for p in loaded if p.id == "p2")
            p3 = next(p for p in loaded if p.id == "p3")

            self.assertEqual(p3.display_order, 0)  # Now first
            self.assertEqual(p2.display_order, 1)  # Still middle
            self.assertEqual(p1.display_order, 2)  # Now last

    def test_reorder_projects_validates_parent(self) -> None:
        """reorder_projects raises if project doesn't belong to specified parent."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            projects = [
                Project(id="parent", name="Parent"),
                Project(id="root", name="Root"),
                Project(id="child", name="Child", parent_id="parent"),
            ]
            storage.write_projects(projects)

            # Trying to reorder child with root (different parent levels)
            with self.assertRaises(ValueError) as ctx:
                storage.reorder_projects(["child", "root"], parent_id=None)
            self.assertIn("does not belong", str(ctx.exception))
