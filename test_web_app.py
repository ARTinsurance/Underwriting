from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_app


class WebAppStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.path_patch = patch.object(web_app, "DATABASE_PATH", self.database_path)
        self.path_patch.start()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_state_validation_and_database_upsert(self) -> None:
        state = {"review": {"quotationRef": "ART-1"}, "evidence": []}
        encoded = web_app.validate_state(state)
        now = web_app.utc_now()
        with web_app.database() as connection:
            connection.execute(
                "INSERT INTO reviews (id, state_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("browser-1", encoded, now, now),
            )
        with sqlite3.connect(self.database_path) as connection:
            stored = connection.execute("SELECT state_json FROM reviews WHERE id = ?", ("browser-1",)).fetchone()
        self.assertEqual(json.loads(stored[0]), state)

    def test_invalid_review_id_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            web_app.validate_review_id("../bad")

    def test_equasis_lookup_rejects_invalid_imo_before_subprocess(self) -> None:
        with self.assertRaises(Exception):
            web_app.run_equasis_lookup("93428")

if __name__ == "__main__":
    unittest.main()
