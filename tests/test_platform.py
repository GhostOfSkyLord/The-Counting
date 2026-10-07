"""Checks the Windows, Mac and Linux branches from any machine."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tally_app import osutil, paths  # noqa: E402


class DataFolders(unittest.TestCase):
    def test_each_platform_gets_its_own_normal_location(self):
        env = {"APPDATA": "C:/Users/Sam/AppData/Roaming"}
        self.assertEqual(paths.default_base("win32", env, "C:/Users/Sam").as_posix(), "C:/Users/Sam/AppData/Roaming/The Counting")
        self.assertEqual(paths.default_base("darwin", {}, "/Users/sam").as_posix(), "/Users/sam/Library/Application Support/The Counting")
        self.assertEqual(paths.default_base("linux", {}, "/home/sam").as_posix(), "/home/sam/.local/share/the-counting")

    def test_windows_without_appdata_falls_back(self):
        self.assertTrue(paths.default_base("win32", {}, "C:/Users/Sam").as_posix().endswith("AppData/Roaming/The Counting"))


class OpenFolder(unittest.TestCase):
    def test_mac_uses_open(self):
        with mock.patch.object(osutil.subprocess, "Popen") as p:
            osutil.open_folder("/x/y", platform="darwin")
        p.assert_called_once_with(["open", "/x/y"])

    def test_linux_uses_xdg_open(self):
        with mock.patch.object(osutil.subprocess, "Popen") as p:
            osutil.open_folder("/x/y", platform="linux")
        p.assert_called_once_with(["xdg-open", "/x/y"])

    def test_windows_uses_explorer(self):
        with mock.patch.object(osutil.os, "startfile", create=True) as sf:
            osutil.open_folder("C:/x", platform="win32")
        sf.assert_called_once_with("C:/x")


class Dialogs(unittest.TestCase):
    def test_mac_dialog_is_built_safely(self):
        script = osutil.applescript_dialog('It said "no"\\ and more', "Tally")
        self.assertIn('It said \\"no\\"', script)
        self.assertTrue(script.startswith("display dialog"))
        with mock.patch.object(osutil.subprocess, "run") as run:
            osutil.message_box("Problem", platform="darwin")
        self.assertEqual(run.call_args[0][0][:2], ["osascript", "-e"])

    def test_other_systems_do_not_crash_without_a_dialog(self):
        osutil.message_box("Problem", platform="linux")

    def test_only_windows_has_an_app_mode_browser(self):
        self.assertIsNone(osutil.app_mode_browser(platform="darwin"))
        self.assertIsNone(osutil.app_mode_browser(platform="linux"))


if __name__ == "__main__":
    unittest.main()
