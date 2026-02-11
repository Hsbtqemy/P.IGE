import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pige.core.storage import Storage


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
