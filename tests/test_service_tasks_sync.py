"""Service features used by the web server: client-chosen ids, mail links, inbox."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pige.core.exceptions import TaskNotFoundError
from pige.core.service import INBOX_TAG, PigeService
from pige.core.storage import Storage


class TaskSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.service = PigeService(Storage(Path(self._tmp.name)))
        self.service.init_storage()
        self.project = self.service.create_project("Projet", None, [])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_client_id_makes_creation_idempotent(self) -> None:
        task_id = "0123456789abcdef0123456789abcdef"
        first = self.service.create_task(self.project.id, "Appeler", [], None, None, task_id=task_id)
        second = self.service.create_task(self.project.id, "Appeler", [], None, None, task_id=task_id)
        self.assertEqual(first.id, task_id)
        self.assertEqual(second, first)
        self.assertEqual(len(self.service.list_all_tasks("all")), 1)

    def test_invalid_client_id_is_rejected(self) -> None:
        for bad in ("../etc/passwd", "ABCDEF", "0123456789abcdef0123456789abcdeG", ""):
            with self.assertRaises(ValueError):
                self.service.create_task(self.project.id, "x", [], None, None, task_id=bad)

    def test_mail_message_id_survives_updates_and_reload(self) -> None:
        task = self.service.create_task(
            self.project.id, "Répondre", [], None, None, mail_message_id=" <abc@example.org> "
        )
        self.assertEqual(task.mail_message_id, "<abc@example.org>")
        self.service.update_task(task.id, {"title": "Répondre vite"})
        self.service.set_task_done(task.id, True)
        reloaded = PigeService(Storage(Path(self._tmp.name))).get_task(task.id)
        self.assertEqual(reloaded.mail_message_id, "<abc@example.org>")
        self.assertEqual(reloaded.title, "Répondre vite")
        self.assertEqual(reloaded.status, "done")

    def test_tasks_written_before_the_field_existed_still_load(self) -> None:
        tasks_path = Path(self._tmp.name) / "tasks.json"
        tasks_path.write_text(
            '[{"id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "project_id": "%s", "title": "Ancienne"}]'
            % self.project.id,
            encoding="utf-8",
        )
        task = self.service.get_task("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertIsNone(task.mail_message_id)

    def test_list_all_tasks_spans_projects_and_filters_status(self) -> None:
        other = self.service.create_project("Autre", None, [])
        a = self.service.create_task(self.project.id, "A", [], None, None)
        self.service.create_task(other.id, "B", [], None, None)
        self.service.set_task_done(a.id, True)
        self.assertEqual([t.title for t in self.service.list_all_tasks("open")], ["B"])
        self.assertEqual(len(self.service.list_all_tasks("all")), 2)
        with self.assertRaises(ValueError):
            self.service.list_all_tasks("bogus")

    def test_get_task_unknown(self) -> None:
        with self.assertRaises(TaskNotFoundError):
            self.service.get_task("f" * 32)

    def test_inbox_project_is_created_once(self) -> None:
        inbox = self.service.ensure_inbox_project()
        again = self.service.ensure_inbox_project()
        self.assertEqual(inbox.id, again.id)
        self.assertIn(INBOX_TAG, inbox.tags)


if __name__ == "__main__":
    unittest.main()
