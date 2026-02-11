import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pige.core.storage import Storage, _fold_entry_events
from pige.utils import io as io_utils


def _minimal_entry_event(eid: str, title: str = "T") -> dict:
    return {
        "kind": "entry",
        "id": eid,
        "ts": "2024-01-01T12:00:00Z",
        "project_id": "p1",
        "type": "note",
        "title": title,
        "tags": [],
        "content_path": f"entries/{eid}.md",
    }


class TestStorage(unittest.TestCase):
    def test_init_storage_creates_files(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()

            self.assertTrue((data_dir / "projects.json").exists())
            self.assertTrue((data_dir / "entries.jsonl").exists())
            self.assertTrue((data_dir / "tasks.json").exists())
            self.assertTrue((data_dir / "timers.json").exists())
            self.assertTrue((data_dir / "timelogs.jsonl").exists())
            self.assertTrue((data_dir / "entries").is_dir())
            self.assertTrue((data_dir / "exports").is_dir())

            with open(data_dir / "timers.json", "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertFalse(payload["running"])

    def test_write_entry_content_atomic_read_back(self) -> None:
        """write_entry_content uses atomic write; read returns same content."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()
            entry_id = "a" * 32
            content = "# Hello\n\nBody with unicode: éàù."
            path = storage.write_entry_content(entry_id, content)
            self.assertEqual(path, storage.entries_dir / f"{entry_id}.md")
            self.assertTrue(path.exists())
            self.assertFalse(Path(str(path) + ".tmp").exists())
            read_back = storage.read_entry_content(path)
            self.assertEqual(read_back, content)

    def test_read_tasks_ignores_unknown_keys(self) -> None:
        """tasks.json with unknown keys is read; only known fields are used."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()
            raw = [
                {
                    "id": "task1",
                    "project_id": "proj1",
                    "title": "A task",
                    "status": "open",
                    "unknown_field": True,
                    "extra": "ignored",
                }
            ]
            io_utils.safe_write_json(storage.tasks_path, raw)
            tasks = storage.read_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].id, "task1")
            self.assertEqual(tasks[0].project_id, "proj1")
            self.assertEqual(tasks[0].title, "A task")
            self.assertEqual(tasks[0].status, "open")
            self.assertFalse(hasattr(tasks[0], "unknown_field"))

    def test_read_projects_ignores_unknown_keys(self) -> None:
        """projects.json with unknown keys is read; only known fields are used."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()
            raw = [
                {
                    "id": "proj1",
                    "name": "Alpha",
                    "description": "Desc",
                    "unknown_key": 42,
                }
            ]
            io_utils.safe_write_json(storage.projects_path, raw)
            projects = storage.read_projects()
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0].id, "proj1")
            self.assertEqual(projects[0].name, "Alpha")
            self.assertEqual(projects[0].description, "Desc")
            self.assertFalse(hasattr(projects[0], "unknown_key"))

    def test_read_timer_state_ignores_unknown_keys(self) -> None:
        """timers.json with unknown keys is read; only known fields are used."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()
            raw = {
                "running": False,
                "project_id": None,
                "start_ts": None,
                "note": None,
                "unknown": "ignored",
            }
            io_utils.safe_write_json(storage.timers_path, raw)
            state = storage.read_timer_state()
            self.assertFalse(state.running)
            self.assertIsNone(state.project_id)
            self.assertFalse(hasattr(state, "unknown"))

    def test_read_entries_meta_folds_entry_update_and_delete(self) -> None:
        """read_entries_meta applies entry_update and entry_delete from JSONL."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()
            # entry1
            io_utils.append_jsonl(
                storage.entries_path,
                {
                    "kind": "entry",
                    "id": "e1",
                    "ts": "2024-01-01T12:00:00Z",
                    "project_id": "p1",
                    "type": "note",
                    "title": "Original",
                    "tags": [],
                    "content_path": "entries/e1.md",
                },
            )
            # update title
            io_utils.append_jsonl(
                storage.entries_path,
                {
                    "kind": "entry_update",
                    "ts": "2024-01-02T12:00:00Z",
                    "entry_id": "e1",
                    "patch": {"title": "Updated"},
                },
            )
            entries = storage.read_entries_meta()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].id, "e1")
            self.assertEqual(entries[0].title, "Updated")
            # entry2 then delete e1
            io_utils.append_jsonl(
                storage.entries_path,
                {
                    "kind": "entry",
                    "id": "e2",
                    "ts": "2024-01-03T12:00:00Z",
                    "project_id": "p1",
                    "type": "note",
                    "title": "Second",
                    "tags": [],
                    "content_path": "entries/e2.md",
                },
            )
            io_utils.append_jsonl(
                storage.entries_path,
                {"kind": "entry_delete", "ts": "2024-01-04T12:00:00Z", "entry_id": "e1"},
            )
            entries = storage.read_entries_meta()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].id, "e2")
            self.assertEqual(entries[0].title, "Second")

    def test_read_entries_meta_corrupt_jsonl_raises_with_line_number(self) -> None:
        """read_entries_meta raises ValueError with line number on corrupt JSONL."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = Storage(data_dir)
            storage.init_storage()
            io_utils.append_jsonl(
                storage.entries_path,
                {
                    "kind": "entry",
                    "id": "e1",
                    "ts": "2024-01-01T12:00:00Z",
                    "project_id": "p1",
                    "type": "note",
                    "title": "T",
                    "tags": [],
                    "content_path": "entries/e1.md",
                },
            )
            with open(storage.entries_path, "a", encoding="utf-8") as f:
                f.write("not valid json\n")
            with self.assertRaises(ValueError) as ctx:
                storage.read_entries_meta()
            self.assertIn("line 2", str(ctx.exception))
            self.assertIn("Corrupt", str(ctx.exception))

    def test_fold_entry_events_unknown_entry_id_update_raises(self) -> None:
        """_fold_entry_events raises when entry_update references unknown entry_id."""
        events = [
            _minimal_entry_event("e1"),
            {"kind": "entry_update", "ts": "2024-01-02T12:00:00Z", "entry_id": "e2", "patch": {"title": "X"}},
        ]
        with self.assertRaises(ValueError) as ctx:
            _fold_entry_events(events)
        self.assertIn("e2", str(ctx.exception))
        self.assertIn("update", str(ctx.exception).lower())

    def test_fold_entry_events_invalid_patch_raises(self) -> None:
        """_fold_entry_events raises when entry_update patch is not a dict."""
        events = [
            _minimal_entry_event("e1"),
            {"kind": "entry_update", "ts": "2024-01-02T12:00:00Z", "entry_id": "e1", "patch": "not a dict"},
        ]
        with self.assertRaises(ValueError) as ctx:
            _fold_entry_events(events)
        self.assertIn("patch", str(ctx.exception).lower())

    def test_fold_entry_events_type_in_patch_raises(self) -> None:
        """_fold_entry_events raises when patch contains 'type' (immutable)."""
        events = [
            _minimal_entry_event("e1"),
            {"kind": "entry_update", "ts": "2024-01-02T12:00:00Z", "entry_id": "e1", "patch": {"type": "meeting"}},
        ]
        with self.assertRaises(ValueError) as ctx:
            _fold_entry_events(events)
        self.assertIn("type", str(ctx.exception).lower())

    def test_fold_entry_events_unknown_patch_keys_raises(self) -> None:
        """_fold_entry_events raises when patch has keys not in ALLOWED_ENTRY_PATCH_KEYS."""
        events = [
            _minimal_entry_event("e1"),
            {"kind": "entry_update", "ts": "2024-01-02T12:00:00Z", "entry_id": "e1", "patch": {"title": "OK", "id": "x"}},
        ]
        with self.assertRaises(ValueError) as ctx:
            _fold_entry_events(events)
        self.assertIn("Invalid entry_update keys", str(ctx.exception))
        self.assertIn("id", str(ctx.exception))

    def test_fold_entry_events_unknown_entry_id_delete_raises(self) -> None:
        """_fold_entry_events raises when entry_delete references unknown entry_id."""
        events = [
            _minimal_entry_event("e1"),
            {"kind": "entry_delete", "ts": "2024-01-02T12:00:00Z", "entry_id": "e2"},
        ]
        with self.assertRaises(ValueError) as ctx:
            _fold_entry_events(events)
        self.assertIn("e2", str(ctx.exception))

    def test_fold_entry_events_invalid_event_raises(self) -> None:
        """_fold_entry_events raises when an event is not a dict."""
        events = [_minimal_entry_event("e1"), "not a dict"]
        with self.assertRaises(ValueError) as ctx:
            _fold_entry_events(events)
        self.assertIn("Invalid entry event", str(ctx.exception))

    def test_fold_entry_events_unknown_kind_raises(self) -> None:
        """_fold_entry_events raises when event kind is unknown."""
        events = [_minimal_entry_event("e1"), {"kind": "foo", "entry_id": "e1"}]
        with self.assertRaises(ValueError) as ctx:
            _fold_entry_events(events)
        self.assertIn("Unknown entry event kind", str(ctx.exception))
        self.assertIn("foo", str(ctx.exception))

    def test_fold_entry_events_preserves_order_and_multiple_updates(self) -> None:
        """_fold_entry_events preserves insertion order and applies multiple updates."""
        events = [
            _minimal_entry_event("e1", "First"),
            _minimal_entry_event("e2", "Second"),
            {"kind": "entry_update", "ts": "2024-01-02T12:00:00Z", "entry_id": "e1", "patch": {"title": "First updated"}},
            {"kind": "entry_update", "ts": "2024-01-03T12:00:00Z", "entry_id": "e1", "patch": {"tags": ["a", "b"]}},
        ]
        result = _fold_entry_events(events)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].id, "e1")
        self.assertEqual(result[0].title, "First updated")
        self.assertEqual(result[0].tags, ["a", "b"])
        self.assertEqual(result[1].id, "e2")
        self.assertEqual(result[1].title, "Second")
