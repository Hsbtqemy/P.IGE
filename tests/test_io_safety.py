"""Crash safety, locking between processes and path safety of the data directory."""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pige.core.service import PigeService
from pige.core.storage import LOCK_FILE_NAME, Storage
from pige.utils import io as io_utils


def _service(data_dir: Path) -> PigeService:
    service = PigeService(Storage(data_dir))
    service.init_storage()
    return service


def _create_tasks(data_dir: str, project_id: str, label: str, count: int) -> None:
    service = PigeService(Storage(Path(data_dir)))
    for i in range(count):
        service.create_task(project_id, f"{label}-{i}", [], None, None)


def _add_entries_forever(data_dir: str, project_id: str) -> None:
    service = PigeService(Storage(Path(data_dir)))
    i = 0
    while True:
        service.add_entry(project_id, "note", f"note {i}", [], "corps " * 50)
        i += 1


class AtomicWriteTests(unittest.TestCase):
    def test_failed_write_keeps_old_file_and_leaves_no_temp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "tasks.json"
            io_utils.safe_write_json(target, ["old"])
            with mock.patch("pige.utils.io.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    io_utils.safe_write_json(target, ["new"])
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), ["old"])
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["tasks.json"])

    def test_torn_last_line_survives_later_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "entries.jsonl"
            io_utils.append_jsonl(log, {"n": 1})
            with open(log, "a", encoding="utf-8") as handle:
                handle.write('{"n": 2, "tit')  # crash in the middle of a write
            self.assertEqual(io_utils.read_jsonl(log), [{"n": 1}])
            io_utils.append_jsonl(log, {"n": 3})
            io_utils.append_jsonl(log, {"n": 4})
            self.assertEqual(io_utils.read_jsonl(log), [{"n": 1}, {"n": 3}, {"n": 4}])
            self.assertIn('"tit', (Path(tmp) / "entries.jsonl.torn").read_text(encoding="utf-8"))

    def test_line_cut_inside_a_multibyte_character(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "entries.jsonl"
            io_utils.append_jsonl(log, {"titre": "réunion"})
            full = (json.dumps({"titre": "décision"}, ensure_ascii=False) + "\n").encode("utf-8")
            cut = full[: full.index("é".encode()) + 1]  # half of the "é"
            with open(log, "ab") as handle:
                handle.write(cut)
            self.assertEqual(io_utils.read_jsonl(log), [{"titre": "réunion"}])
            io_utils.append_jsonl(log, {"titre": "après"})
            self.assertEqual(io_utils.read_jsonl(log), [{"titre": "réunion"}, {"titre": "après"}])


class LockSharingTests(unittest.TestCase):
    def test_two_storages_on_one_folder_do_not_deadlock(self) -> None:
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            first = _service(Path(tmp))
            second = PigeService(Storage(Path(tmp)))
            done = threading.Event()

            def nested() -> None:
                with first.storage.lock.hold():
                    second.list_projects()
                done.set()

            worker = threading.Thread(target=nested, daemon=True)
            worker.start()
            worker.join(5)
            self.assertTrue(done.is_set(), "nested locks on the same folder deadlocked")


@unittest.skipIf(sys.platform.startswith("win"), "uses fork and SIGKILL")
class ProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.service = _service(self.data_dir)
        self.project = self.service.create_project("P", None, [])
        self.ctx = multiprocessing.get_context("fork")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_concurrent_writers_lose_no_update(self) -> None:
        workers = [
            self.ctx.Process(target=_create_tasks, args=(str(self.data_dir), self.project.id, name, 40))
            for name in ("a", "b", "c")
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(60)
            self.assertEqual(worker.exitcode, 0)
        titles = {t.title for t in self.service.list_all_tasks("all")}
        self.assertEqual(len(titles), 120)

    def test_process_killed_mid_write_loses_nothing_already_written(self) -> None:
        worker = self.ctx.Process(target=_add_entries_forever, args=(str(self.data_dir), self.project.id))
        worker.start()
        time.sleep(1.5)
        os.kill(worker.pid, signal.SIGKILL)
        worker.join(10)
        fresh = _service(self.data_dir)
        entries = fresh.storage.read_entries_meta()
        self.assertGreater(len(entries), 5)
        # Every entry the log knows about has its full Markdown body on disk.
        for entry in entries:
            body = fresh.storage.read_entry_body(entry)
            self.assertIn("corps", body)
        # The data directory stays usable: the next write works.
        fresh.add_entry(self.project.id, "note", "après le crash", [], "ok")
        self.assertEqual(len(fresh.storage.read_entries_meta()), len(entries) + 1)

    def test_cache_sees_writes_from_another_process(self) -> None:
        reader = Storage(self.data_dir)
        self.assertEqual(reader.read_entries_meta(), [])
        worker = self.ctx.Process(target=_create_entry, args=(str(self.data_dir), self.project.id))
        worker.start()
        worker.join(30)
        self.assertEqual([e.title for e in reader.read_entries_meta()], ["d'ailleurs"])


def _create_entry(data_dir: str, project_id: str) -> None:
    PigeService(Storage(Path(data_dir))).add_entry(project_id, "note", "d'ailleurs", [], "x")


class PathSafetyTests(unittest.TestCase):
    def test_hostile_content_path_is_neither_read_nor_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "secret.txt"
            outside.write_text("ne pas toucher", encoding="utf-8")
            service = _service(root / "data")
            project = service.create_project("P", None, [])
            entry, _ = service.add_entry(project.id, "note", "t", [], "x")
            # Simulate a crafted backup: rewrite the entry to point outside entries/.
            log = service.storage.entries_path
            events = io_utils.read_jsonl(log)
            events[0]["content_path"] = "../secret.txt"
            io_utils.safe_write_jsonl(log, events)
            service.storage.invalidate_entry_cache()
            hostile = service.storage.get_entry(entry.id)
            self.assertIsNone(service.storage.entry_path(hostile))
            self.assertEqual(service.storage.read_entry_body(hostile), "")
            service.delete_entry(entry.id)
            self.assertTrue(outside.exists())

    def test_ids_with_path_separators_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp))
            storage.init_storage()
            with self.assertRaises(ValueError):
                storage.write_entry_content("../evil", "x")
            io_utils.append_jsonl(
                storage.entries_path,
                {"kind": "entry", "id": "../evil", "ts": "2026-01-01T00:00:00Z", "project_id": "p",
                 "type": "note", "title": "t", "tags": [], "content_path": "entries/x.md"},
            )
            with self.assertRaises(ValueError):
                storage.read_entries_meta()


class BackupTests(unittest.TestCase):
    def test_restore_keeps_passwords_and_rebuilds_index(self) -> None:
        from pige.core.indexing import SearchIndex

        with tempfile.TemporaryDirectory() as tmp:
            service = _service(Path(tmp) / "data")
            project = service.create_project("P", None, [])
            service.add_entry(project.id, "note", "t", [], "texte retrouvable")
            subs = service.storage.data_dir / "calendar_subscriptions.json"
            subs.write_text(json.dumps([{"id": "s", "name": "n", "source_url": "https://x", "password": "pw"}]), encoding="utf-8")
            backup = service.storage.create_backup(Path(tmp) / "b.zip")
            service.storage.restore_backup(backup)
            restored = json.loads(subs.read_text(encoding="utf-8"))
            self.assertEqual(restored[0]["password"], "pw")
            # The index was not in the backup; it is rebuilt on next use.
            service.create_task(project.id, "écriture", [], None, None)
            with SearchIndex(service.storage.index_path) as idx:
                self.assertEqual(len(idx.search_entries("retrouvable")), 1)


    def test_backup_excludes_lock_and_calendar_passwords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _service(Path(tmp) / "data")
            service.create_project("P", None, [])
            subs = service.storage.data_dir / "calendar_subscriptions.json"
            subs.write_text(
                json.dumps([{"id": "s", "name": "n", "source_url": "https://x", "username": "u", "password": "secret"}]),
                encoding="utf-8",
            )
            out = service.storage.create_backup(Path(tmp) / "backup.zip")
            with zipfile.ZipFile(out) as archive:
                names = archive.namelist()
                saved = json.loads(archive.read("calendar_subscriptions.json"))
            self.assertNotIn(LOCK_FILE_NAME, names)
            self.assertEqual(saved, [{"id": "s", "name": "n", "source_url": "https://x"}])
            self.assertIn("secret", subs.read_text(encoding="utf-8"))  # local file untouched


if __name__ == "__main__":
    unittest.main()
