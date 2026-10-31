import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from concat_speech_mcp import tts_engine_vieneu, voice_library
from concat_speech_mcp.process import EngineError
from concat_speech_mcp.tools import call_tool
from concat_speech_mcp.voice_library import VoiceLibraryError


class FakeRun:
    """ffmpeg writes a stand-in clip; ffprobe answers `seconds`."""

    def __init__(self, seconds=8.0):
        self.seconds = seconds
        self.commands = []

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"RIFF")
        out = f"{self.seconds}\n" if cmd[0] == "ffprobe" else ""
        return types.SimpleNamespace(stdout=out, stderr="", returncode=0)


class VoiceLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.voices = Path(self.tmp.name) / "voices"
        patcher = mock.patch.dict("os.environ", {"CONCAT_SPEECH_VOICES_DIR": str(self.voices)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.video = Path(self.tmp.name) / "interview.mp4"
        self.video.write_bytes(b"")

    def test_save_cuts_speech_only_mono_from_start_and_lists_it(self):
        run = FakeRun()

        made = voice_library.save("Giọng của tôi", str(self.video), start=12.5, duration=8, run=run)

        ffmpeg = run.commands[0]
        self.assertEqual(ffmpeg[ffmpeg.index("-ss") + 1], "12.500")
        self.assertEqual(ffmpeg[ffmpeg.index("-t") + 1], "8.000")
        self.assertIn("-vn", ffmpeg)
        self.assertEqual(ffmpeg[ffmpeg.index("-ac") + 1], "1")
        self.assertEqual(made["voice"], "clone:Giọng của tôi")
        self.assertTrue((self.voices / "Giọng của tôi.wav").is_file())
        self.assertEqual([v["voice"] for v in voice_library.saved()], ["clone:Giọng của tôi"])

    def test_save_too_little_audio_is_refused_and_keeps_nothing(self):
        with self.assertRaisesRegex(VoiceLibraryError, "need at least 3 s"):
            voice_library.save("ngan", str(self.video), start=58, run=FakeRun(seconds=1.2))
        self.assertEqual(list(self.voices.iterdir()), [])

    def test_save_same_name_needs_replace(self):
        voice_library.save("a", str(self.video), run=FakeRun())

        with self.assertRaisesRegex(VoiceLibraryError, "saved already"):
            voice_library.save("a", str(self.video), run=FakeRun())
        voice_library.save("a", str(self.video), replace=True, run=FakeRun())

    def test_save_refuses_names_that_are_paths_and_durations_out_of_range(self):
        for name in ("../x", "a/b", ""):
            with self.assertRaises(VoiceLibraryError):
                voice_library.save(name, str(self.video), run=FakeRun())
        for duration in (2, 9):
            with self.assertRaises(VoiceLibraryError):
                voice_library.save("a", str(self.video), duration=duration, run=FakeRun())

    def test_remove_deletes_clip_and_note(self):
        voice_library.save("a", str(self.video), run=FakeRun())

        self.assertEqual(voice_library.remove("clone:a"), {"removed": "clone:a"})
        self.assertEqual(list(self.voices.iterdir()), [])

    def test_clone_tool_without_consent_is_refused_before_cutting(self):
        with mock.patch.object(voice_library, "save") as save:
            with self.assertRaisesRegex(ValueError, "consent: true"):
                call_tool("speech_voice_clone", {"name": "a", "file": str(self.video), "consent": False})
        save.assert_not_called()

    def test_vieneu_render_saved_voice_sends_its_clip_and_unknown_one_is_refused(self):
        voice_library.save("a", str(self.video), run=FakeRun())

        with mock.patch.object(tts_engine_vieneu.WORKER, "request") as request:
            tts_engine_vieneu.render("xin chào", "clone:a", Path("/tmp/x.wav"), None)
            with self.assertRaisesRegex(EngineError, "no saved voice 'b'"):
                tts_engine_vieneu.render("xin chào", "clone:b", Path("/tmp/x.wav"), None)

        self.assertEqual(request.call_args.args[0]["ref"], str(self.voices / "a.wav"))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class VoiceLibraryRealFfmpegTest(unittest.TestCase):
    def test_save_from_a_video_with_real_ffmpeg_keeps_only_the_asked_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "talk.mp4"
            voice_library.run_checked(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=12",
                                       "-f", "lavfi", "-i", "color=c=black:s=64x64:d=12", "-shortest", str(video)])
            with mock.patch.dict("os.environ", {"CONCAT_SPEECH_VOICES_DIR": str(Path(tmp) / "voices")}):
                made = voice_library.save("talk", str(video), start=2, duration=5)

        self.assertAlmostEqual(made["duration"], 5.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
