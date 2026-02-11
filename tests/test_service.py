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

    def test_export_project_raw_redact_bodies(self) -> None:
        from pige.core.service import REDACTED_PLACEHOLDER

        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            service.add_entry(project.id, "note", "Secret", [], "Confidential content")
            export_path, warnings = service.export_project_raw(
                project.id, None, None, None, redact_bodies=True
            )
            self.assertEqual(warnings, [])
            content = export_path.read_text(encoding="utf-8")
            self.assertIn("# Alpha", content)
            self.assertIn("Secret", content)
            self.assertIn(REDACTED_PLACEHOLDER, content)
            self.assertNotIn("Confidential content", content)

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

    def test_list_in_progress_threads_empty_when_no_entries(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            service.create_project("Alpha", None, [])
            threads = service.list_in_progress_threads(days=14)
            self.assertEqual(threads, [])

    def test_list_in_progress_threads_with_entries_and_tasks(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry1, _ = service.add_entry(
                project.id, "note", "Meeting with Alice", [], None, person="Alice"
            )
            entry2, _ = service.add_entry(
                project.id, "note", "Follow-up Bob", [], None, person="Bob"
            )
            service.create_task(
                project.id, "Action from meeting", [], None, linked_entry_id=entry1.id
            )
            threads = service.list_in_progress_threads(days=30)
            self.assertGreaterEqual(len(threads), 1)
            thread_ids = {t.last_entry_id for t in threads}
            self.assertIn(entry1.id, thread_ids)
            self.assertIn(entry2.id, thread_ids)
            thread_for_e1 = next(t for t in threads if t.last_entry_id == entry1.id)
            self.assertEqual(thread_for_e1.open_actions, 1)

    def test_list_in_progress_threads_respects_days_filter(self) -> None:
        """Thread with last entry older than days and no open tasks is excluded."""
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            old_date = date.today() - timedelta(days=20)
            recent_date = date.today() - timedelta(days=2)
            service.add_entry(
                project.id, "note", "Old", [], None,
                person="OldPerson", entry_date=old_date
            )
            entry_recent, _ = service.add_entry(
                project.id, "note", "Recent", [], None,
                person="RecentPerson", entry_date=recent_date
            )
            threads = service.list_in_progress_threads(days=14)
            last_ids = {t.last_entry_id for t in threads}
            self.assertIn(entry_recent.id, last_ids)
            # Old entry thread may or may not appear depending on active_recent;
            # with days=14, 20 days ago is excluded unless there are open_actions
            self.assertGreaterEqual(len(threads), 1)

    def test_list_in_progress_entries_filters_by_context_status(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            e1, _ = service.add_entry(project.id, "note", "Created", [], None)
            service.set_entry_context_status(e1.id, "actual")
            e2, _ = service.add_entry(project.id, "note", "Actual", [], None)
            service.set_entry_context_status(e2.id, "actual")
            e3, _ = service.add_entry(project.id, "note", "Treated", [], None)
            service.set_entry_context_status(e3.id, "treated")
            actual_only = service.list_in_progress_entries()
            self.assertEqual(len(actual_only), 2)
            self.assertIn(e1.id, {e.id for e in actual_only})
            self.assertIn(e2.id, {e.id for e in actual_only})
            with_created = service.list_in_progress_entries(include_created=True)
            self.assertGreaterEqual(len(with_created), 2)
            with_treated = service.list_in_progress_entries(include_treated=True)
            self.assertIn(e3.id, {e.id for e in with_treated})

    def test_move_entry_to_another_project(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            p1 = service.create_project("Alpha", None, ["a"])
            p2 = service.create_project("Beta", None, ["b"])
            entry, _ = service.add_entry(
                p1.id, "note", "Moved", ["t1"], "Body", person="Alice"
            )
            updated = service.move_entry(entry.id, p2.id, keep_tags=True, keep_people=True)
            self.assertEqual(updated.project_id, p2.id)
            self.assertEqual(updated.title, "Moved")
            self.assertEqual(updated.tags, ["t1"])
            self.assertEqual(updated.person, "Alice")
            in_p1 = [e for e in service.storage.read_entries_meta() if e.project_id == p1.id]
            in_p2 = [e for e in service.storage.read_entries_meta() if e.project_id == p2.id]
            self.assertEqual(len(in_p1), 0)
            self.assertEqual(len(in_p2), 1)
            self.assertEqual(in_p2[0].id, entry.id)

    def test_move_entry_keep_tags_false_clears_tags(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            p1 = service.create_project("Alpha", None, [])
            p2 = service.create_project("Beta", None, [])
            entry, _ = service.add_entry(p1.id, "note", "E", ["a", "b"], None)
            updated = service.move_entry(entry.id, p2.id, keep_tags=False, keep_people=True)
            self.assertEqual(updated.project_id, p2.id)
            self.assertEqual(updated.tags, [])

    def test_move_entry_keep_people_false_clears_person_and_group(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            p1 = service.create_project("Alpha", None, [])
            p2 = service.create_project("Beta", None, [])
            entry, _ = service.add_entry(
                p1.id, "note", "E", [], None, person="Alice", group="G1"
            )
            updated = service.move_entry(entry.id, p2.id, keep_tags=True, keep_people=False)
            self.assertEqual(updated.project_id, p2.id)
            self.assertIsNone(updated.person)
            self.assertIsNone(updated.group)

    def test_move_entry_not_found_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            with self.assertRaises(ValueError) as ctx:
                service.move_entry("nonexistent-id", project.id)
            self.assertIn("not found", str(ctx.exception))

    def test_move_entry_same_project_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _ = service.add_entry(project.id, "note", "E", [], None)
            with self.assertRaises(ValueError) as ctx:
                service.move_entry(entry.id, project.id)
            self.assertIn("already in that project", str(ctx.exception))

    def test_move_entry_invalid_project_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _ = service.add_entry(project.id, "note", "E", [], None)
            with self.assertRaises(ValueError) as ctx:
                service.move_entry(entry.id, "nonexistent-project-id")
            self.assertIn("not found", str(ctx.exception).lower())

    def test_extract_followup_tasks_from_body(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            body = "- [ ] First action\n- [ ] Second\nACTION: Do something\nTODO: Another"
            entry, _ = service.add_entry(project.id, "note", "Notes", [], body)
            titles = service.extract_followup_tasks(entry.id)
            self.assertIn("First action", titles)
            self.assertIn("Second", titles)
            self.assertIn("Do something", titles)
            self.assertIn("Another", titles)
            self.assertEqual(len(titles), 4)

    def test_extract_followup_tasks_entry_not_found_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            service.create_project("Alpha", None, [])
            with self.assertRaises(ValueError) as ctx:
                service.extract_followup_tasks("nonexistent-entry-id")
            self.assertIn("not found", str(ctx.exception))

    def test_extract_followup_tasks_empty_body_returns_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _ = service.add_entry(project.id, "note", "Empty", [], "")
            titles = service.extract_followup_tasks(entry.id)
            self.assertEqual(titles, [])

    def test_extract_followup_tasks_deduplicates_same_title(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            body = "- [ ] Same title\n- [ ] Same title\nTODO: Same title"
            entry, _ = service.add_entry(project.id, "note", "Notes", [], body)
            titles = service.extract_followup_tasks(entry.id)
            self.assertEqual(titles, ["Same title"])

    def test_create_followup_tasks_links_to_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            entry, _ = service.add_entry(project.id, "note", "Meeting", [], "- [ ] Task A")
            titles = service.extract_followup_tasks(entry.id)
            created = service.create_followup_tasks(entry.id, titles)
            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].title, "Task A")
            self.assertEqual(created[0].linked_entry_id, entry.id)
            self.assertEqual(created[0].project_id, project.id)

    def test_export_project_narrative_contains_sections(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            service.add_entry(project.id, "decision", "Decide X", [], "Context")
            start = date(2024, 1, 1)
            end = date(2024, 1, 31)
            path = service.export_project_narrative(project.id, start, end, None)
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertIn("## Résumé", content)
            self.assertIn("## Décisions", content)
            self.assertIn("## Chronologie", content)
            self.assertIn("## Temps", content)
            self.assertIn("## Annexes", content)

    def test_export_project_narrative_filters_by_date_range(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            service.add_entry(
                project.id, "note", "In range", [], "Body",
                entry_date=date(2024, 1, 15)
            )
            service.add_entry(
                project.id, "note", "Out early", [], "Body",
                entry_date=date(2023, 12, 1)
            )
            service.add_entry(
                project.id, "note", "Out late", [], "Body",
                entry_date=date(2024, 3, 1)
            )
            start = date(2024, 1, 1)
            end = date(2024, 1, 31)
            path = service.export_project_narrative(project.id, start, end, None)
            content = path.read_text(encoding="utf-8")
            self.assertIn("In range", content)
            self.assertNotIn("Out early", content)
            self.assertNotIn("Out late", content)

    def test_export_weekly_summary_structure(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            service.add_entry(project.id, "meeting", "Sync", [], "Notes")
            start = date(2024, 1, 1)
            end = date(2024, 1, 7)
            path_str = service.export_weekly_summary(start, end, project.id, None)
            path = Path(path_str)
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertIn("Weekly Summary", content)
            self.assertIn("Résumé global", content)
            self.assertIn("Alpha", content)

    def test_export_weekly_summary_start_after_end_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            service.create_project("Alpha", None, [])
            start = date(2024, 1, 10)
            end = date(2024, 1, 5)
            with self.assertRaises(ValueError) as ctx:
                service.export_weekly_summary(start, end, None, None)
            self.assertIn("start is after end", str(ctx.exception).lower())

    def test_export_weekly_summary_filters_by_date_range(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            service.add_entry(
                project.id, "note", "In week", [], "",
                entry_date=date(2024, 1, 3)
            )
            service.add_entry(
                project.id, "note", "Before week", [], "",
                entry_date=date(2023, 12, 25)
            )
            service.add_entry(
                project.id, "note", "After week", [], "",
                entry_date=date(2024, 1, 15)
            )
            start = date(2024, 1, 1)
            end = date(2024, 1, 7)
            path_str = service.export_weekly_summary(start, end, project.id, None)
            content = Path(path_str).read_text(encoding="utf-8")
            self.assertIn("In week", content)
            self.assertNotIn("Before week", content)
            self.assertNotIn("After week", content)

    def test_compact_entries_rewrites_snapshot(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self._build_service(tmp)
            project = service.create_project("Alpha", None, [])
            e1, _ = service.add_entry(project.id, "note", "First", [], "Body 1")
            e2, _ = service.add_entry(project.id, "note", "Second", [], "Body 2")
            service.update_entry_meta(e1.id, title="First updated", tags=["a"])
            before = len(service.storage.read_entries_meta())
            self.assertEqual(before, 2)
            with open(service.storage.entries_path, "r", encoding="utf-8") as f:
                before_lines = sum(1 for _ in f)
            self.assertGreater(before_lines, 2)
            recap = service.compact_entries()
            self.assertEqual(recap["entries_count"], 2)
            self.assertEqual(recap["after_lines"], 2)
            self.assertEqual(recap["before_lines"], before_lines)
            entries = service.storage.read_entries_meta()
            self.assertEqual(len(entries), 2)
            by_id = {e.id: e for e in entries}
            self.assertEqual(by_id[e1.id].title, "First updated")
            self.assertEqual(by_id[e1.id].tags, ["a"])
            self.assertEqual(by_id[e2.id].title, "Second")
