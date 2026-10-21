import stat
import tempfile
import unittest
from pathlib import Path

import setup_speech
from concat_speech_mcp import speech_env_file


class Answers:
    """Plays the user: answers prompts in order, records what was shown."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.shown = []

    def ask(self, prompt):
        self.shown.append(prompt)
        return self.answers.pop(0)

    def say(self, text):
        self.shown.append(text)


class SetupSpeechTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "concat-speech" / "env"

    def run_setup(self, user):
        return setup_speech.main(ask=user.ask, ask_secret=user.ask, say=user.say, path=self.path)

    def test_setup_choosing_google_saves_key_private_and_never_prints_it(self):
        # Arrange: menu number 2 is google
        user = Answers("2", "secret-value")

        # Act
        code = self.run_setup(user)

        # Assert
        self.assertEqual(code, 0)
        self.assertEqual(speech_env_file.read(self.path),
                         {"GOOGLE_TTS_API_KEY": "secret-value", "CONCAT_SPEECH_ENGINE": "google"})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertNotIn("secret-value", "\n".join(user.shown))

    def test_setup_existing_readable_file_is_replaced_private(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("CONCAT_SPEECH_ENGINE=macos\n")
        self.path.chmod(0o644)

        self.run_setup(Answers("2", "secret-value"))

        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(list(self.path.parent.glob(".*.tmp")), [])

    def test_setup_symlinked_file_keeps_the_link(self):
        real = Path(self.tmp.name) / "real-env"
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(real)

        self.run_setup(Answers("2", "k"))

        self.assertTrue(self.path.is_symlink())
        self.assertEqual(speech_env_file.read(real)["GOOGLE_TTS_API_KEY"], "k")

    def test_setup_enter_at_key_prompt_keeps_saved_key(self):
        self.run_setup(Answers("2", "old-key"))

        self.run_setup(Answers("2", ""))

        self.assertEqual(speech_env_file.read(self.path)["GOOGLE_TTS_API_KEY"], "old-key")

    def test_setup_switching_to_macos_keeps_other_engine_keys(self):
        self.run_setup(Answers("2", "old-key"))

        self.run_setup(Answers("1"))

        self.assertEqual(speech_env_file.read(self.path),
                         {"GOOGLE_TTS_API_KEY": "old-key", "CONCAT_SPEECH_ENGINE": "macos"})

    def test_setup_engine_needing_key_without_one_changes_nothing(self):
        code = self.run_setup(Answers("2", ""))

        self.assertEqual(code, 1)
        self.assertFalse(self.path.exists())

    def test_setup_wrong_number_asks_again_and_enter_cancels(self):
        user = Answers("9", "")

        code = self.run_setup(user)

        self.assertEqual(code, 1)
        self.assertIn("  Not one of the numbers above.", user.shown)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
