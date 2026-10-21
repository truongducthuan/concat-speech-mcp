import json
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from concat_speech_mcp.process import EngineError, run_checked
from concat_speech_mcp.transcribe import TranscribeError, transcribe

WHISPER_JSON = {
    "result": {"language": "vi"},
    "transcription": [{"tokens": [
        {"text": " Xin", "offsets": {"from": 0, "to": 300}, "t_dtw": 20},
        {"text": " chào", "offsets": {"from": 300, "to": 600}, "t_dtw": 50},
        {"text": " Kyoto", "offsets": {"from": 2000, "to": 2400}, "t_dtw": 230},
    ]}],
}
FFMPEG_SILENCE_LOG = "silence_start: 1.0\nsilence_end: 2.0\n"


class FakeEngines:
    """Stands in for ffmpeg, ffprobe and whisper-cli; whisper writes `whisper_json`."""

    def __init__(self, whisper_json=WHISPER_JSON, whisper_exit=0):
        self.whisper_json = whisper_json
        self.whisper_exit = whisper_exit

    def __call__(self, cmd, **kwargs):
        if cmd[0] == "ffprobe":
            return types.SimpleNamespace(stdout="3.0\n", stderr="", returncode=0)
        if "-of" in cmd and cmd[0] != "ffprobe":  # whisper-cli
            if self.whisper_exit:
                return types.SimpleNamespace(stdout="", stderr="error: failed to read audio", returncode=1)
            if self.whisper_json is not None:
                stem = cmd[cmd.index("-of") + 1]
                Path(f"{stem}.json").write_text(json.dumps(self.whisper_json), encoding="utf-8")
            return types.SimpleNamespace(stdout="", stderr="", returncode=0)
        if "silencedetect" in " ".join(cmd):
            return types.SimpleNamespace(stdout="", stderr=FFMPEG_SILENCE_LOG, returncode=0)
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)  # ffmpeg to 16 kHz


class TranscribeTest(unittest.TestCase):
    def setUp(self):
        self.models = tempfile.TemporaryDirectory()
        self.addCleanup(self.models.cleanup)
        Path(self.models.name, "ggml-small.bin").write_bytes(b"x")
        patcher = mock.patch.dict(os.environ, {"CONCAT_SPEECH_MODEL_DIR": self.models.name,
                                               "CONCAT_SPEECH_WHISPER_CLI": "whisper-cli"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_transcribe_vietnamese_tokens_become_spaced_utterances_split_at_silence(self):
        # Act
        result = transcribe(Path("/x/in.mp4"), run=FakeEngines())

        # Assert
        self.assertEqual(result["language"], "vi")
        self.assertEqual([(u["start"], u["end"], u["text"]) for u in result["utterances"]],
                         [(0.0, 1.0, "Xin chào"), (2.0, 3.0, "Kyoto")])

    def test_transcribe_whisper_failure_reports_its_stderr(self):
        with self.assertRaises(EngineError) as caught:
            transcribe(Path("/x/in.mp4"), run=FakeEngines(whisper_exit=1))

        self.assertIn("failed to read audio", str(caught.exception))

    def test_transcribe_whisper_writing_nothing_is_an_error(self):
        with self.assertRaises(TranscribeError):
            transcribe(Path("/x/in.mp4"), run=FakeEngines(whisper_json=None))

    def test_transcribe_unknown_model_is_refused(self):
        with self.assertRaises(TranscribeError):
            transcribe(Path("/x/in.mp4"), model="large", run=FakeEngines())


class RunCheckedTest(unittest.TestCase):
    def test_run_checked_nonzero_exit_carries_stderr_tail(self):
        # Regression (review H1): the agent once got only "exit status 1".
        fake = lambda cmd, **kw: types.SimpleNamespace(stdout="", stderr="in.txt: Invalid data found", returncode=1)

        with self.assertRaises(EngineError) as caught:
            run_checked(["ffmpeg", "-i", "in.txt"], run=fake)

        self.assertIn("Invalid data found", str(caught.exception))

    def test_run_checked_timeout_is_reported_not_raised_raw(self):
        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])

        with self.assertRaises(EngineError):
            run_checked(["whisper-cli"], run=slow, timeout=1)

    def test_run_checked_missing_binary_is_reported(self):
        def missing(cmd, **kw):
            raise FileNotFoundError(cmd[0])

        with self.assertRaises(EngineError):
            run_checked(["no-such-engine"], run=missing)


if __name__ == "__main__":
    unittest.main()
