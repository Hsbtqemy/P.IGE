"""Masked exports hide free text: entry bodies and time-log notes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pige.core.service import PigeService
from pige.core.storage import Storage


class RedactedExportTests(unittest.TestCase):
    def test_narrative_export_hides_bodies_and_time_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = PigeService(Storage(Path(tmp) / "data"))
            service.init_storage()
            project = service.create_project("P", None, [])
            service.add_entry(project.id, "note", "Titre visible", [], "corps confidentiel")
            service.add_manual_time(project.id, 1800, None, "note de temps confidentielle")
            masked = service.export_project_narrative(project.id, None, None, Path(tmp) / "m.md", redact_bodies=True)
            text = masked.read_text(encoding="utf-8")
            self.assertIn("Titre visible", text)
            self.assertNotIn("corps confidentiel", text)
            self.assertNotIn("note de temps confidentielle", text)
            plain = service.export_project_narrative(project.id, None, None, Path(tmp) / "p.md")
            self.assertIn("note de temps confidentielle", plain.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
