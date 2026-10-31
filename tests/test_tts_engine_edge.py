import json
import types
import unittest
from pathlib import Path
from unittest import mock

from concat_speech_mcp import local_python, tts_engine_edge
from concat_speech_mcp.process import EngineError
from concat_speech_mcp.synthesize import SynthesizeError, list_engines, synthesize

VOICES = [{"name": "vi-VN-HoaiMyNeural", "locale": "vi-VN", "language": "vi", "gender": "Female"}]
WORDS = [{"start": 0.1, "end": 0.4, "text": "Xin"}, {"start": 0.4, "end": 1.0, "text": "chào"}]


class FakeRun:
    """Answers the edge worker with word timings and ffprobe with fixed durations; records each call."""

    def __init__(self, durations):
        self.durations = list(durations)
        self.commands = []

    def __call__(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        if str(tts_engine_edge.WORKER) in cmd:
            out = json.dumps({"words": WORDS})
        elif cmd[0] == "ffprobe":
            out = f"{self.durations.pop(0)}\n"
        else:
            out = ""
        return types.SimpleNamespace(stdout=out, stderr="", returncode=0)


class EdgeSynthesizeTest(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(tts_engine_edge, "_voices", list(VOICES)),
                        mock.patch.object(tts_engine_edge, "missing", return_value=None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_edge_synthesize_text_on_stdin_and_word_times_follow_the_tempo(self):
        # Arrange: natural 2.0 s must fit 1.6 s → 1.25x
        run = FakeRun([2.0, 1.6])

        # Act
        result = synthesize("Xin chào", "vi-VN-HoaiMyNeural", Path("/tmp/out.wav"), max_duration=1.6,
                            engine="edge", run=run)

        # Assert
        worker_cmd, worker_kwargs = run.commands[0]
        self.assertEqual(worker_cmd[1:3], ["-I", str(tts_engine_edge.WORKER)])
        self.assertEqual(worker_cmd[3:5], ["say", "vi-VN-HoaiMyNeural"])
        self.assertTrue(worker_cmd[5].endswith(".mp3"))
        self.assertEqual(worker_kwargs["input"], "Xin chào")
        self.assertEqual(result["tempo"], 1.25)
        self.assertEqual(result["words"], [{"start": 0.08, "end": 0.32, "text": "Xin"},
                                           {"start": 0.32, "end": 0.8, "text": "chào"}])

    def test_edge_synthesize_unknown_voice_is_refused_before_reading(self):
        run = FakeRun([])

        with self.assertRaisesRegex(SynthesizeError, "unknown voice 'Linh' for the edge engine"):
            synthesize("xin chào", "Linh", Path("/tmp/out.wav"), engine="edge", run=run)
        self.assertEqual(run.commands, [])

    def test_edge_synthesize_rate_is_refused(self):
        with self.assertRaisesRegex(SynthesizeError, "rate applies to the macos engine only"):
            synthesize("xin chào", "vi-VN-HoaiMyNeural", Path("/tmp/out.wav"), rate=200, engine="edge",
                       run=FakeRun([]))

    def test_edge_synthesize_service_without_audio_says_to_use_vieneu(self):
        def run(cmd, **kwargs):
            return types.SimpleNamespace(stdout="", stderr="NoAudioReceived: No audio was received.", returncode=1)

        with self.assertRaisesRegex(EngineError, "after 5 tries.*vieneu engine"):
            synthesize("xin chào", "vi-VN-HoaiMyNeural", Path("/tmp/out.wav"), engine="edge", run=run)


class LocalEngineReadinessTest(unittest.TestCase):
    def test_list_engines_local_engine_without_its_python_is_not_configured_and_says_how_to_install(self):
        engines = {e["name"]: e for e in list_engines({"CONCAT_SPEECH_PYTHON": "/no/such/python"})}

        for name in ("edge", "vieneu"):
            self.assertFalse(engines[name]["configured"])
            self.assertIn("/no/such/python does not exist", engines[name]["install"])
        self.assertNotIn("install", engines["macos"])

    def test_missing_package_not_in_the_venv_names_the_pip_install(self):
        python = Path(__file__)  # any existing file stands in for the interpreter
        run = mock.Mock(return_value=types.SimpleNamespace(returncode=1))

        problem = local_python.missing("edge_tts", {"CONCAT_SPEECH_PYTHON": str(python)}, run=run)

        self.assertIn("pip install edge_tts", problem)
        self.assertEqual(run.call_args.args[0][1:3], ["-I", "-c"])


if __name__ == "__main__":
    unittest.main()
