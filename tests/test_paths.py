import tempfile
import unittest
from pathlib import Path

from concat_speech_mcp.paths import PathError, allowed_roots, existing_file, writable_file


class WritableFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_writable_file_under_root_creates_parent_folder(self):
        # Arrange
        target = self.root / "dub" / "line.wav"

        # Act
        result = writable_file(str(target), (".wav",), roots=[self.root])

        # Assert
        self.assertEqual(result, target)
        self.assertTrue(target.parent.is_dir())

    def test_writable_file_outside_roots_is_refused(self):
        with self.assertRaises(PathError):
            writable_file("/etc/line.wav", (".wav",), roots=[self.root])

    def test_writable_file_dot_dot_escape_is_refused(self):
        sneaky = str(self.root / ".." / "escape.wav")

        with self.assertRaises(PathError):
            writable_file(sneaky, (".wav",), roots=[self.root])

    def test_writable_file_relative_path_is_refused(self):
        with self.assertRaises(PathError):
            writable_file("line.wav", (".wav",), roots=[self.root])

    def test_writable_file_wrong_suffix_is_refused(self):
        with self.assertRaises(PathError):
            writable_file(str(self.root / "line.mp3"), (".wav",), roots=[self.root])


class ExistingFileTest(unittest.TestCase):
    def test_existing_file_missing_file_is_refused(self):
        with self.assertRaises(PathError):
            existing_file("/definitely/not/here.mp4")

    def test_existing_file_relative_path_is_refused(self):
        with self.assertRaises(PathError):
            existing_file("here.mp4")


class AllowedRootsTest(unittest.TestCase):
    def test_allowed_roots_env_adds_extra_folders_after_home(self):
        roots = allowed_roots({"CONCAT_SPEECH_ROOTS": "/tmp"})

        self.assertEqual(roots[0], Path.home().resolve())
        self.assertIn(Path("/tmp").resolve(), roots)


if __name__ == "__main__":
    unittest.main()
