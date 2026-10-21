import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from concat_speech_mcp import speech_env_file
from concat_speech_mcp.synthesize import list_engines
from concat_speech_mcp.tools import call_tool


ALLOWED = {"CONCAT_SPEECH_ENGINE", "GOOGLE_TTS_API_KEY"}


def reset_module_state():
    speech_env_file._from_file.clear()
    speech_env_file._warned.clear()


class SettingsFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "env"
        reset_module_state()
        self.addCleanup(reset_module_state)

    def apply(self, environ, real=frozenset()):
        with contextlib.redirect_stderr(io.StringIO()) as warning:
            speech_env_file.apply(ALLOWED, environ, real=real, path=self.path)
        return warning.getvalue()

    def write(self, text, mode=0o600):
        self.path.write_text(text, encoding="utf-8")
        self.path.chmod(mode)

    def test_env_file_parse_reads_comments_export_and_quotes(self):
        values = speech_env_file.parse("# note\n\nexport A=1\nB = 'two words'\nC=\"3\"\nnot a setting\n=x\n")

        self.assertEqual(values, {"A": "1", "B": "two words", "C": "3"})

    def test_env_file_missing_gives_no_settings(self):
        self.assertEqual(speech_env_file.read(self.path), {})

    def test_env_file_apply_sets_file_values_but_real_environment_wins(self):
        # Arrange
        self.write("CONCAT_SPEECH_ENGINE=google\nGOOGLE_TTS_API_KEY=k\n")
        environ = {"CONCAT_SPEECH_ENGINE": "macos"}

        # Act
        self.apply(environ, real={"CONCAT_SPEECH_ENGINE"})

        # Assert
        self.assertEqual(environ, {"CONCAT_SPEECH_ENGINE": "macos", "GOOGLE_TTS_API_KEY": "k"})

    def test_env_file_line_removed_is_gone_on_next_apply(self):
        # Arrange
        environ = {}
        self.write("CONCAT_SPEECH_ENGINE=google\nGOOGLE_TTS_API_KEY=k\n")
        self.apply(environ)

        # Act
        self.write("CONCAT_SPEECH_ENGINE=macos\n")
        self.apply(environ)

        # Assert
        self.assertEqual(environ, {"CONCAT_SPEECH_ENGINE": "macos"})

    def test_env_file_only_allowed_variables_are_taken(self):
        self.write("GOOGLE_TTS_API_KEY=k\nHTTPS_PROXY=http://evil\nCONCAT_SPEECH_ENV_FILE=/tmp/other\n")
        environ = {}

        self.apply(environ)

        self.assertEqual(environ, {"GOOGLE_TTS_API_KEY": "k"})

    def test_env_file_values_keep_equals_hash_and_survive_crlf_and_bom(self):
        self.path.write_bytes("\ufeffGOOGLE_TTS_API_KEY=ab=c#d\r\nCONCAT_SPEECH_ENGINE=google\r\n".encode())
        self.path.chmod(0o600)

        self.assertEqual(speech_env_file.read(self.path),
                         {"GOOGLE_TTS_API_KEY": "ab=c#d", "CONCAT_SPEECH_ENGINE": "google"})

    def test_env_file_unusable_keeps_previous_settings_and_warns_once(self):
        # Arrange: a good read, then the file becomes undecodable
        environ = {}
        self.write("CONCAT_SPEECH_ENGINE=google\nGOOGLE_TTS_API_KEY=k\n")
        self.apply(environ)
        self.path.write_bytes(b"\xff\xfe broken")

        # Act
        first, second = self.apply(environ), self.apply(environ)

        # Assert
        self.assertEqual(environ, {"CONCAT_SPEECH_ENGINE": "google", "GOOGLE_TTS_API_KEY": "k"})
        self.assertIn("not UTF-8", first)
        self.assertIn(str(self.path), first)
        self.assertEqual(second, "")

    def test_env_file_unreadable_does_not_raise(self):
        self.write("GOOGLE_TTS_API_KEY=k\n", mode=0o000)
        self.addCleanup(self.path.chmod, 0o600)

        warning = self.apply({})

        self.assertIn("cannot be read", warning)

    def test_env_file_writable_by_others_is_ignored(self):
        self.write("GOOGLE_TTS_API_KEY=k\n", mode=0o622)
        environ = {}

        warning = self.apply(environ)

        self.assertEqual(environ, {})
        self.assertIn("ignored", warning)

    def test_env_file_readable_by_others_warns_without_showing_values(self):
        self.write("GOOGLE_TTS_API_KEY=secret-value\n", mode=0o644)

        warning = self.apply({})

        self.assertIn("chmod 600", warning)
        self.assertNotIn("secret-value", warning)


class EngineListTest(unittest.TestCase):
    def test_list_engines_reports_readiness_and_default_without_keys(self):
        engines = {e["name"]: e for e in list_engines({"CONCAT_SPEECH_ENGINE": "google",
                                                       "GOOGLE_TTS_API_KEY": "secret-value"})}

        self.assertEqual((engines["macos"]["configured"], engines["macos"]["default"]), (True, False))
        self.assertEqual((engines["google"]["configured"], engines["google"]["default"]), (True, True))
        self.assertNotIn("secret-value", repr(engines))

    def test_list_engines_engine_without_key_is_not_configured(self):
        engines = {e["name"]: e for e in list_engines({})}

        self.assertFalse(engines["google"]["configured"])
        self.assertEqual(engines["google"]["needs"], "GOOGLE_TTS_API_KEY")
        self.assertTrue(engines["macos"]["default"])


class ToolCallReadsSettingsTest(unittest.TestCase):
    def test_tool_call_rereads_settings_file_before_answering(self):
        # Arrange: settings appear after the server started; the real environment has neither variable
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "env"
        path.write_text("CONCAT_SPEECH_ENGINE=google\nGOOGLE_TTS_API_KEY=k\n")
        path.chmod(0o600)
        reset_module_state()
        self.addCleanup(reset_module_state)
        patcher = mock.patch.dict("os.environ", {"CONCAT_SPEECH_ENV_FILE": str(path)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for variable in ("CONCAT_SPEECH_ENGINE", "GOOGLE_TTS_API_KEY"):
            os.environ.pop(variable, None)

        # Act
        with mock.patch.object(speech_env_file, "_REAL_ENVIRONMENT", frozenset()):
            engines = {e["name"]: e for e in call_tool("speech_engines", {})["engines"]}

        # Assert
        self.assertTrue(engines["google"]["default"] and engines["google"]["configured"])


if __name__ == "__main__":
    unittest.main()
