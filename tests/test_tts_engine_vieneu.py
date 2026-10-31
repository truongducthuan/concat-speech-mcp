import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from concat_speech_mcp import local_python, tts_engine_vieneu
from concat_speech_mcp.paths import PathError
from concat_speech_mcp.process import EngineError

# Stands in for tts_worker_vieneu.py: same line protocol, no model. "die" exits mid-request.
FAKE_WORKER = textwrap.dedent("""
    import json, sys
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("text") == "die":
            sys.exit(3)
        if request["cmd"] == "voices":
            reply = {"voices": [{"name": "Mai Anh", "locale": "vi-VN", "language": "vi"}]}
        elif request.get("voice") == "Nobody":
            reply = {"error": "ValueError: unknown VieNeu voice 'Nobody'"}
        else:
            reply = {"ok": True, "echo": request}
        print(json.dumps(reply, ensure_ascii=False), flush=True)
""")


class VieneuWorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        script = Path(self.tmp.name) / "fake_worker.py"
        script.write_text(FAKE_WORKER, encoding="utf-8")
        for patcher in (mock.patch.object(local_python, "interpreter", return_value=Path(sys.executable)),
                        mock.patch.object(local_python, "worker_script", return_value=script),
                        mock.patch.object(tts_engine_vieneu, "missing", return_value=None),
                        mock.patch.object(tts_engine_vieneu, "LOG", Path(self.tmp.name) / "worker.log"),
                        mock.patch.object(tts_engine_vieneu, "WORKER", tts_engine_vieneu.Worker())):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: tts_engine_vieneu.WORKER.stop())

    def test_vieneu_worker_stays_up_between_requests(self):
        voices = tts_engine_vieneu.list_voices()
        first = tts_engine_vieneu.WORKER.process.pid
        tts_engine_vieneu.render("xin chào", "Mai Anh", Path("/tmp/a.wav"), None)

        self.assertEqual([v["name"] for v in voices], ["Mai Anh"])
        self.assertEqual(tts_engine_vieneu.WORKER.process.pid, first)

    def test_vieneu_worker_error_reply_becomes_engine_error(self):
        with self.assertRaisesRegex(EngineError, "unknown VieNeu voice 'Nobody'"):
            tts_engine_vieneu.render("xin chào", "Nobody", Path("/tmp/a.wav"), None)

    def test_vieneu_worker_that_dies_is_reported_then_started_again(self):
        with self.assertRaisesRegex(EngineError, "the VieNeu worker stopped"):
            tts_engine_vieneu.render("die", "Mai Anh", Path("/tmp/a.wav"), None)

        self.assertEqual([v["name"] for v in tts_engine_vieneu.list_voices()], ["Mai Anh"])

    def test_vieneu_render_path_voice_clones_from_that_recording(self):
        recording = Path(self.tmp.name) / "me.wav"
        recording.write_bytes(b"RIFF")
        with mock.patch.object(tts_engine_vieneu.WORKER, "request") as request:
            tts_engine_vieneu.render("xin chào", str(recording), Path("/tmp/a.wav"), None)

        self.assertEqual(request.call_args.args[0],
                         {"cmd": "say", "text": "xin chào", "out": "/tmp/a.wav", "ref": str(recording.resolve())})

    def test_vieneu_render_clone_from_a_file_that_is_not_audio_is_refused(self):
        notes = Path(self.tmp.name) / "notes.txt"
        notes.write_text("x")

        with self.assertRaisesRegex(EngineError, "must be a recording"):
            tts_engine_vieneu.render("xin chào", str(notes), Path("/tmp/a.wav"), None)
        with self.assertRaises(PathError):
            tts_engine_vieneu.render("xin chào", "/no/such/voice.wav", Path("/tmp/a.wav"), None)


if __name__ == "__main__":
    unittest.main()
