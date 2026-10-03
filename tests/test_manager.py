import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import auto_folder_icons as icons
import manager_core as core


class ManagerConfigTests(unittest.TestCase):
    def test_roots_are_saved_atomically_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "Games"
            root.mkdir()
            config = base / "config.json"
            core.save_roots([str(root), str(root)], config)
            self.assertEqual(core.load_roots(config), [str(root.resolve())])
            self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["version"], 1)

    def test_invalid_configuration_is_not_overwritten_silently(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            config.write_text('{"version": 3, "roots": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                core.load_roots(config)


@unittest.skipUnless(os.name == "nt", "Windows folder metadata test")
class ManagerIconTests(unittest.TestCase):
    def test_replacing_existing_icon_can_restore_its_previous_setting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / "Sample Game"
            game.mkdir()
            (game / "old.ico").write_bytes(b"previous icon")
            original_ini = "[.ShellClassInfo]\r\nIconResource=old.ico,0\r\n".encode("utf-16")
            (game / "desktop.ini").write_bytes(original_ini)
            cover = root / "cover.png"
            Image.new("RGB", (500, 750), "#225588").save(cover)
            with mock.patch.object(icons, "STATE_PATH", root / "state.json"):
                core.set_cover(game, cover)
                self.assertNotEqual((game / "desktop.ini").read_bytes(), original_ini)
                self.assertEqual(core.restore_folder(game), 0)
            self.assertEqual((game / "desktop.ini").read_bytes(), original_ini)
            self.assertTrue((game / "old.ico").exists())

    def test_manual_cover_and_selected_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / "Sample Game"
            other = root / "Other Game"
            game.mkdir()
            other.mkdir()
            cover = root / "cover.png"
            Image.new("RGB", (500, 750), "#225588").save(cover)
            state_path = root / "state.json"
            with mock.patch.object(icons, "STATE_PATH", state_path):
                core.set_cover(game, cover)
                record = icons.load_state()["folders"][str(game.resolve()).lower()]
                self.assertEqual(record["status"], "managed")
                self.assertTrue((game / "desktop.ini").exists())
                self.assertEqual(core.restore_folder(other), 0)
                self.assertTrue((game / "desktop.ini").exists())
                self.assertEqual(core.restore_folder(game), 0)
                self.assertFalse((game / "desktop.ini").exists())


if __name__ == "__main__":
    unittest.main()
