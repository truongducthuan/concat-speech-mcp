"""End to end through the real engines: say, ffmpeg and whisper-cli.

Skipped when any of them (or Concat's small model) is missing. Writes into a
temporary folder under home, removed afterwards.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from concat_speech_mcp.tools import call_tool
from concat_speech_mcp.transcribe import TranscribeError, model_path


def engines_ready():
    if not all(shutil.which(t) for t in ("say", "ffmpeg", "ffprobe", "whisper-cli")):
        return False
    try:
        model_path("small")
    except TranscribeError:
        return False
    return True


@unittest.skipUnless(engines_ready(), "say/ffmpeg/whisper-cli or the small model not installed")
class RealEnginesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.home(), prefix=".concat-speech-test-")
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_synthesize_then_transcribe_japanese_round_trip(self):
        # Arrange: a Japanese line read by Kyoko, two sentences with a pause
        wav = self.dir / "ja.wav"
        made = call_tool("speech_synthesize", {"text": "京都へようこそ。 [[slnc 800]] 今日はお寺を紹介します。",
                                               "voice": "Kyoko", "output": str(wav)})

        # Act
        heard = call_tool("speech_transcribe", {"file": str(wav), "output": str(self.dir / "ja.json")})

        # Assert
        self.assertGreater(made["duration"], 1.0)
        self.assertEqual(heard["language"], "ja")
        text = "".join(u["text"] for u in heard["utterances"])
        # A clip this short gives whisper no context to pick kanji; kana is as right.
        self.assertTrue("京都" in text or "きょうと" in text, text)
        self.assertGreaterEqual(len(heard["utterances"]), 2)
        self.assertTrue((self.dir / "ja.json").is_file())

    def test_real_synthesize_vietnamese_fits_max_duration(self):
        # Arrange
        wav = self.dir / "vi.wav"

        # Act
        made = call_tool("speech_synthesize", {"text": "Xin chào mọi người, hôm nay chúng ta đi Kyoto.",
                                               "voice": "Linh", "output": str(wav), "maxDuration": 2.0})

        # Assert
        self.assertGreater(made["tempo"], 1.0)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate",
                                "-of", "csv=p=0", str(wav)], capture_output=True, text=True, check=True)
        self.assertEqual(probe.stdout.strip(), "48000")


if __name__ == "__main__":
    unittest.main()
