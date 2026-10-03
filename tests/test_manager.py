import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import auto_folder_icons as icons
from manager import ManagerWindow
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


class ManagerWindowTests(unittest.TestCase):
    def test_adding_library_starts_bounded_first_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            window = object.__new__(ManagerWindow)
            window.window = object()
            window.roots = []
            window.busy = False
            window.root_tree = mock.Mock()
            window.refresh = mock.Mock()
            window._background = mock.Mock()
            with mock.patch("manager.filedialog.askdirectory", return_value=str(root)), \
                    mock.patch.object(core, "save_roots") as save_roots:
                window.add_root()

            save_roots.assert_called_once_with([str(root)])
            window.root_tree.selection_set.assert_called_once_with(str(root))
            background = window._background.call_args
            self.assertEqual(background.kwargs["scanning_root"], root)
            self.assertIn("First check complete", background.kwargs["completion_text"])
            with mock.patch.object(core, "scan_roots", return_value=0) as scan_roots:
                background.args[1]()
            scan_roots.assert_called_once_with([str(root)], max_candidates_per_root=2, busy_is_error=True)

    def test_explicit_check_reports_another_scan_in_progress(self):
        with mock.patch.object(icons, "SingleInstance") as single_instance:
            single_instance.return_value.__enter__.return_value = False
            with self.assertRaisesRegex(RuntimeError, "already running"):
                core.scan_roots(["unused"], busy_is_error=True)

    def test_new_library_shows_checking_status_without_overwriting_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / "Sample Game"
            game.mkdir()
            window = object.__new__(ManagerWindow)
            window.game_tree = mock.Mock()
            window.game_tree.get_children.return_value = []
            window.selected_root = mock.Mock(return_value=root)
            window.scanning_root = root
            window.task_state = "current"
            window.busy = True
            window.status_text = mock.Mock()
            with mock.patch.object(icons, "load_state", return_value={"folders": {}}), \
                    mock.patch.object(icons, "direct_child_folders", return_value=[game]), \
                    mock.patch.object(icons, "existing_icon", return_value=(False, None, None)):
                window.refresh_games()

            self.assertEqual(window.game_tree.insert.call_args.kwargs["values"],
                             ("Sample Game", "Checking cover…"))
            window.status_text.set.assert_not_called()


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
