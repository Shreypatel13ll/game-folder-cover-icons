import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import auto_folder_icons as icons


class MatchingTests(unittest.TestCase):
    def test_title_matching_rejects_a_different_sequel_or_addon(self):
        self.assertEqual(icons.title_score("Forza Horizon 6", "Forza Horizon 5"), 0.0)
        self.assertEqual(icons.title_score("Firewatch", "Firewatch Soundtrack"), 0.0)
        self.assertEqual(icons.title_score("Firewatch", "Firewatch"), 1.0)

    def test_repeated_search_result_is_not_counted_as_ambiguous(self):
        payload = {
            "items": [
                {"type": "app", "id": 383870, "name": "Firewatch"},
                {"type": "app", "id": 435910, "name": "Firewatch Original Soundtrack"},
            ]
        }
        with mock.patch.object(icons, "http_bytes", return_value=(json.dumps(payload).encode(), "application/json")):
            match = icons.search_steam(["Firewatch", "Firewatch"])
        self.assertIsNotNone(match)
        self.assertEqual(match["appid"], "383870")


class FolderIconTests(unittest.TestCase):
    def test_desktop_ini_keeps_unrelated_metadata(self):
        original = "[.ShellClassInfo]\r\nLocalizedResourceName=My Game\r\n\r\n[ViewState]\r\nMode=\r\n".encode("utf-16")
        updated = icons.merge_ini(original, ".folder-icon-auto-example.ico")
        decoded = updated.decode("utf-16")
        self.assertIn("LocalizedResourceName=My Game", decoded)
        self.assertIn("[ViewState]", decoded)
        self.assertIn("IconResource=.folder-icon-auto-example.ico,0", decoded)

    @unittest.skipUnless(__import__("os").name == "nt", "Windows Explorer metadata test")
    def test_managed_icon_can_be_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "Sample Game"
            folder.mkdir()
            state_path = root / "state.json"
            state = {"version": icons.VERSION, "folders": {}, "history": []}
            source = Image.new("RGBA", (600, 900), "#336699")
            master = icons.make_master(source)

            with mock.patch.object(icons, "STATE_PATH", state_path):
                record = icons.apply_icon(folder, "Sample Game", master, "test-image", state)
                key = str(folder.resolve()).lower()
                state["folders"][key] = record
                icons.save_state(state)

                self.assertTrue((folder / "desktop.ini").exists())
                self.assertTrue(Path(record["icon"]).exists())
                self.assertEqual(icons.restore_managed(root), 0)

            self.assertFalse((folder / "desktop.ini").exists())
            self.assertFalse(Path(record["icon"]).exists())


if __name__ == "__main__":
    unittest.main()
