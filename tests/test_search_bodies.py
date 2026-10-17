"""The full-text index covers entry bodies, projects and tasks without manual rebuilds."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pige.core.indexing import SearchIndex, index_content_version, INDEX_CONTENT_VERSION
from pige.core.service import PigeService
from pige.core.storage import Storage


class SearchBodiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.service = PigeService(Storage(self.data_dir))
        self.service.init_storage()
        self.project = self.service.create_project("Revue Edito", "numéro d'automne", [])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def search(self, kind: str, query: str) -> list[str]:
        with SearchIndex(self.service.storage.index_path) as idx:
            return getattr(idx, f"search_{kind}")(query)

    def test_entry_body_is_searchable_and_follows_edits(self) -> None:
        entry, _ = self.service.add_entry(self.project.id, "note", "Réunion", [], "budget imprimeur validé")
        self.assertEqual(self.search("entries", "imprimeur"), [entry.id])
        self.service.update_entry_content(entry.id, "maquette envoyée")
        self.assertEqual(self.search("entries", "imprimeur"), [])
        self.assertEqual(self.search("entries", "maquette"), [entry.id])
        self.service.delete_entry(entry.id)
        self.assertEqual(self.search("entries", "maquette"), [])

    def test_projects_and_tasks_indexed_without_rebuild(self) -> None:
        self.assertEqual(self.search("projects", "automne"), [self.project.id])
        task = self.service.create_task(self.project.id, "Relancer la graphiste", [], None, None)
        self.assertEqual(self.search("tasks", "graphiste"), [task.id])
        self.service.update_task(task.id, {"title": "Appeler l'imprimeur"})
        self.assertEqual(self.search("tasks", "graphiste"), [])
        self.assertEqual(self.search("tasks", "imprimeur"), [task.id])

    def test_old_index_without_bodies_is_rebuilt_once(self) -> None:
        entry, _ = self.service.add_entry(self.project.id, "note", "Titre", [], "contenu introuvable avant")
        # Simulate an index built by the previous version (no content_version).
        conn = sqlite3.connect(self.service.storage.index_path)
        conn.execute("DELETE FROM index_metadata WHERE key = 'content_version'")
        conn.execute("DELETE FROM entries_fts")
        conn.commit()
        conn.close()
        fresh = PigeService(Storage(self.data_dir))
        fresh.create_task(self.project.id, "déclenche une écriture", [], None, None)
        self.assertEqual(index_content_version(fresh.storage.index_path), INDEX_CONTENT_VERSION)
        self.assertEqual(self.search("entries", "introuvable"), [entry.id])


class InterruptedRebuildTests(unittest.TestCase):
    def test_rebuild_interrupted_midway_is_redone(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            service = PigeService(Storage(Path(tmp)))
            service.init_storage()
            project = service.create_project("P", None, [])
            service.add_entry(project.id, "note", "t", [], "phrase témoin")
            with mock.patch.object(SearchIndex, "index_projects_bulk", side_effect=RuntimeError("crash")):
                with self.assertRaises(RuntimeError):
                    service.storage.rebuild_search_index()
            self.assertIsNone(index_content_version(service.storage.index_path))
            fresh = PigeService(Storage(Path(tmp)))
            fresh.create_task(project.id, "x", [], None, None)
            with SearchIndex(fresh.storage.index_path) as idx:
                self.assertEqual(len(idx.search_entries("témoin")), 1)


if __name__ == "__main__":
    unittest.main()
