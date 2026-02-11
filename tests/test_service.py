import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from pige.core.models import TimeLog, TimerState
from pige.core.service import PigeService
from pige.core.storage import Storage
from pige.utils import dates


class TestService(unittest.TestCase):
    def _build_service(self, tmp: str) -> PigeService:
        storage = Storage(Path(tmp) / "data")
        service = PigeService(storage)
        service.init_storage()
        return service

    def test_create_project(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, ["tag1"])
            self.assertEqual(project.name, "Alpha")
            self.assertEqual(project.status, "active")
            self.assertEqual(len(project.id), 32)
            self.assertEqual(len(service.storage.read_projects()), 1)

    def test_create_project_with_person_group(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project(
                "Alpha", None, ["tag1"], person="Alice", group="TeamA"
            )
            self.assertEqual(project.person, "Alice")
            self.assertEqual(project.group, "TeamA")
            stored = service.storage.read_projects()[0]
            self.assertEqual(stored.person, "Alice")
            self.assertEqual(stored.group, "TeamA")

    def test_update_project_changes_fields_and_persists(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", "Old", ["tag1"])
            updated = service.update_project(
                project.id,
                name="Beta",
                description="New desc",
                tags=["t1", "t2"],
                person="Alice",
                group="TeamA",
                status="archived",
            )
            self.assertEqual(updated.name, "Beta")
            self.assertEqual(updated.description, "New desc")
            self.assertEqual(updated.tags, ["t1", "t2"])
            self.assertEqual(updated.person, "Alice")
            self.assertEqual(updated.group, "TeamA")
            self.assertEqual(updated.status, "archived")
            stored = service.storage.read_projects()[0]
            self.assertEqual(stored.name, "Beta")
            self.assertEqual(stored.status, "archived")

    def test_update_project_invalid_id_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            service.create_project("Alpha", None, [])
            with self.assertRaises(ValueError):
                service.update_project(
                    "missing",
                    name="Beta",
                    description=None,
                    tags=[],
                    person=None,
                    group=None,
                    status="active",
                )

    def test_add_entry_creates_files(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, md_path = service.add_entry(
                project.id, "note", "Hello", [], "Body text"
            )
            self.assertTrue(md_path.exists())
            self.assertIn(entry.id, md_path.name)
            with open(md_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertEqual(content, "Body text")

    def test_entry_update_event_applied(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _md_path = service.add_entry(
                project.id, "note", "Hello", ["old"], None
            )
            updated = service.update_entry_meta(
                entry.id, title="Updated", tags=["new"], person="Alice"
            )
            self.assertEqual(updated.title, "Updated")
            self.assertEqual(updated.tags, ["new"])
            self.assertEqual(updated.person, "Alice")
            read_back = [item for item in service.storage.read_entries_meta() if item.id == entry.id][0]
            self.assertEqual(read_back.title, "Updated")

    def test_delete_entry_removes_meta_and_content(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, md_path = service.add_entry(
                project.id, "note", "Hello", ["old"], "Body text"
            )
            self.assertTrue(md_path.exists())
            service.delete_entry(entry.id)
            remaining = [item for item in service.storage.read_entries_meta() if item.id == entry.id]
            self.assertEqual(remaining, [])
            self.assertFalse(md_path.exists())

    def test_delete_project_removes_associated_data(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            other = service.create_project("Beta", None, [])
            entry, md_path = service.add_entry(
                project.id, "note", "Hello", ["old"], "Body text"
            )
            other_entry, other_md_path = service.add_entry(
                other.id, "note", "Other", ["new"], "More text"
            )
            task = service.create_task(project.id, "Task A", [], None, None)
            other_task = service.create_task(other.id, "Task B", [], None, None)
            service.storage.append_timelog(
                TimeLog(
                    id="log-1",
                    project_id=project.id,
                    start=dates.utc_now_iso(),
                    end=dates.utc_now_iso(),
                    duration_sec=60,
                    duration_min=1,
                )
            )
            service.storage.append_timelog(
                TimeLog(
                    id="log-2",
                    project_id=other.id,
                    start=dates.utc_now_iso(),
                    end=dates.utc_now_iso(),
                    duration_sec=120,
                    duration_min=2,
                )
            )
            service.storage.write_timer_state(
                TimerState(True, project.id, dates.utc_now_iso(), None)
            )

            service.delete_project(project.id)

            remaining_projects = service.storage.read_projects()
            self.assertNotIn(project.id, [item.id for item in remaining_projects])
            self.assertIn(other.id, [item.id for item in remaining_projects])

            remaining_entries = service.storage.read_entries_meta()
            self.assertNotIn(project.id, [item.project_id for item in remaining_entries])
            self.assertIn(other_entry.id, [item.id for item in remaining_entries])
            self.assertFalse(md_path.exists())
            self.assertTrue(other_md_path.exists())

            remaining_tasks = service.storage.read_tasks()
            self.assertNotIn(task.id, [item.id for item in remaining_tasks])
            self.assertIn(other_task.id, [item.id for item in remaining_tasks])

            remaining_logs = service.storage.read_timelogs()
            self.assertNotIn(project.id, [item.project_id for item in remaining_logs])
            self.assertIn(other.id, [item.project_id for item in remaining_logs])

            timer_state = service.storage.read_timer_state()
            self.assertFalse(timer_state.running)
            self.assertIsNone(timer_state.project_id)

    def test_entry_update_rejects_type_change(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _md_path = service.add_entry(project.id, "note", "Hello", [], None)
            service.storage.append_entry_update(
                entry.id, dates.utc_now_iso(), {"type": "note"}
            )
            with self.assertRaises(ValueError):
                service.storage.read_entries_meta()

    def test_decision_done_toggle_persists(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _md_path = service.add_entry(
                project.id, "decision", "Ship", [], None, decision_done=False
            )
            updated = service.update_entry_meta(entry.id, decision_done=True)
            self.assertTrue(updated.decision_done)

    def test_meeting_time_persists(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _md_path = service.add_entry(
                project.id,
                "meeting",
                "Sync",
                [],
                None,
                start_time="09:00",
                end_time="10:00",
            )
            updated = service.update_entry_meta(entry.id, end_time="10:30")
            self.assertEqual(updated.start_time, "09:00")
            self.assertEqual(updated.end_time, "10:30")

    def test_add_entry_with_entry_date_midday(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry_date = date(2024, 2, 10)
            entry, _md_path = service.add_entry(
                project.id,
                "note",
                "Hello",
                [],
                None,
                entry_date=entry_date,
            )
            expected_ts = dates.local_date_midday_to_utc_z(entry_date)
            self.assertEqual(entry.ts, expected_ts)
            self.assertEqual(entry.entry_date, entry_date.isoformat())

    def test_meeting_entry_with_hours(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _md_path = service.add_entry(
                project.id,
                "meeting",
                "Sync",
                [],
                None,
                start_time="09:00",
                end_time="10:30",
            )
            self.assertEqual(entry.start_time, "09:00")
            self.assertEqual(entry.end_time, "10:30")

    def test_decision_entry_with_done(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _md_path = service.add_entry(
                project.id,
                "decision",
                "Ship",
                [],
                None,
                decision_done=True,
            )
            self.assertTrue(entry.decision_done)

    def test_start_stop_timer(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            start_dt = datetime.now(timezone.utc) - timedelta(minutes=2)
            start_ts = start_dt.strftime(dates.UTC_Z_FORMAT)
            service.storage.write_timer_state(
                TimerState(True, project.id, start_ts, None)
            )
            timelog, _project = service.time_stop()
            self.assertGreaterEqual(timelog.duration_sec or 0, 120)
            self.assertGreaterEqual(timelog.duration_min or 0, 2)

    def test_timer_duration_seconds(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            start_dt = datetime.now(timezone.utc) - timedelta(seconds=125)
            start_ts = start_dt.strftime(dates.UTC_Z_FORMAT)
            service.storage.write_timer_state(
                TimerState(True, project.id, start_ts, None)
            )
            timelog, _project = service.time_stop()
            self.assertGreaterEqual(timelog.duration_sec or 0, 125)
            totals = service.time_today()
            self.assertGreaterEqual(totals.get(project.id, 0), 125)

    def test_timer_stop_creates_activity_when_enabled(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            start_dt = datetime.now(timezone.utc) - timedelta(seconds=61)
            start_ts = start_dt.strftime(dates.UTC_Z_FORMAT)
            service.storage.write_timer_state(
                TimerState(True, project.id, start_ts, "Focus")
            )
            service.time_stop(create_activity=True)
            entries = [e for e in service.storage.read_entries_meta() if e.project_id == project.id]
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry.type, "log")
            self.assertTrue(entry.title.startswith("Activity - "))
            md_path = service.storage.data_dir / entry.content_path
            with open(md_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("Started:", content)
            self.assertIn("Ended:", content)
            self.assertIn("Duration:", content)
            self.assertIn("min", content)
            self.assertIn("sec", content)
            self.assertIn("Note: Focus", content)

    def test_project_list_today_time_column(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            now = datetime.now(timezone.utc).replace(microsecond=0)
            start = now - timedelta(seconds=65)
            timelog = TimeLog(
                id="test",
                project_id=project.id,
                start=start.strftime(dates.UTC_Z_FORMAT),
                end=now.strftime(dates.UTC_Z_FORMAT),
                duration_sec=65,
                duration_min=1,
                note=None,
                tags=[],
            )
            service.storage.append_timelog(timelog)
            totals = service.time_today()
            self.assertEqual(totals.get(project.id), 65)

    def test_timer_already_running(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            service.storage.write_timer_state(
                TimerState(True, project.id, dates.utc_now_iso(), None)
            )
            with self.assertRaises(ValueError) as ctx:
                service.time_start(project.id, None)
            self.assertIn("Timer already running", str(ctx.exception))

    def test_export_project_raw(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, ["tag1"])
            service.add_entry(project.id, "note", "Hello", [], "Body text")
            export_path, warnings = service.export_project_raw(
                project.id, None, None, None
            )
            self.assertEqual(warnings, [])
            self.assertTrue(export_path.exists())
            with open(export_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("# Alpha", content)
            self.assertIn("Body text", content)

    def test_export_missing_md_file(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, md_path = service.add_entry(project.id, "note", "Hello", [], None)
            md_path.unlink()
            export_path, warnings = service.export_project_raw(
                project.id, None, None, None
            )
            self.assertTrue(export_path.exists())
            self.assertEqual(len(warnings), 1)
            self.assertIn(entry.id, warnings[0])
            with open(export_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("Content file missing", content)

    def test_create_task_persists(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            task = service.create_task(project.id, "Follow up", ["tag1"], "Note", None)
            tasks = service.storage.read_tasks()
            self.assertEqual(len(tasks), 1)
            stored = tasks[0]
            self.assertEqual(stored.id, task.id)
            self.assertEqual(stored.title, "Follow up")
            self.assertEqual(stored.tags, ["tag1"])
            self.assertEqual(stored.note, "Note")
            self.assertEqual(len(stored.id), 32)

    def test_toggle_done(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            task = service.create_task(project.id, "Finish", [], None, None)
            done = service.set_task_done(task.id, True)
            self.assertEqual(done.status, "done")
            self.assertIsNotNone(done.done_at)
            reopened = service.set_task_done(task.id, False)
            self.assertEqual(reopened.status, "open")
            self.assertIsNone(reopened.done_at)

    def test_list_tasks_filters(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            open_task = service.create_task(project.id, "Open", [], None, None)
            done_task = service.create_task(project.id, "Done", [], None, None)
            service.set_task_done(done_task.id, True)
            open_tasks = service.list_tasks(project.id, status="open")
            done_tasks = service.list_tasks(project.id, status="done")
            all_tasks = service.list_tasks(project.id, status="all")
            self.assertEqual([t.id for t in open_tasks], [open_task.id])
            self.assertEqual([t.id for t in done_tasks], [done_task.id])
            self.assertEqual(len(all_tasks), 2)

    def test_task_linked_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _md_path = service.add_entry(project.id, "note", "Hello", [], None)
            task = service.create_task(
                project.id, "Follow up", [], None, linked_entry_id=entry.id
            )
            stored = service.storage.read_tasks()[0]
            self.assertEqual(stored.linked_entry_id, entry.id)
            self.assertEqual(task.linked_entry_id, entry.id)

    def test_export_includes_tasks(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            open_task = service.create_task(project.id, "Open task", [], None, None)
            done_task = service.create_task(project.id, "Done task", [], None, None)
            service.set_task_done(done_task.id, True)
            export_path, warnings = service.export_project_raw(
                project.id, None, None, None
            )
            self.assertEqual(warnings, [])
            with open(export_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("## Tasks", content)
            self.assertIn(f"- [ ] {open_task.title}", content)
            self.assertIn(f"- [x] {done_task.title}", content)

    def test_log_today_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            grouped = service.log_today()
            self.assertEqual(grouped, [])

    def test_invalid_project_id(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            with self.assertRaises(ValueError) as ctx:
                service.add_entry("missing", "note", "Hello", [], None)
            self.assertIn("Project missing not found", str(ctx.exception))
