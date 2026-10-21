import subprocess
import types
import unittest
from pathlib import Path

from concat_speech_mcp.synthesize import SynthesizeError, parse_voices, plan_tempo, synthesize

SAY_LISTING = """Kyoko               ja_JP    # こんにちは! 私の名前はKyokoです。
Linh                vi_VN    # Xin chào! Tên tôi là Linh.
Eddy (Japanese (Japan)) ja_JP    # こんにちは! 私の名前はEddyです。
not a voice line
"""
VOICES = parse_voices(SAY_LISTING)


class FakeRun:
    """Records commands; answers ffprobe with a fixed duration per call."""

    def __init__(self, durations):
        self.durations = list(durations)
        self.commands = []

    def __call__(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        out = f"{self.durations.pop(0)}\n" if cmd[0] == "ffprobe" else ""
        return types.SimpleNamespace(stdout=out, stderr="", returncode=0)


class VoicesTest(unittest.TestCase):
    def test_parse_voices_reads_names_with_spaces_and_locales(self):
        self.assertEqual([(v["name"], v["language"]) for v in VOICES],
                         [("Kyoko", "ja"), ("Linh", "vi"), ("Eddy (Japanese (Japan))", "ja")])


class TempoTest(unittest.TestCase):
    def test_plan_tempo_no_limit_keeps_normal_speed(self):
        self.assertEqual(plan_tempo(5.0, None, 1.35), (1.0, 0.0))

    def test_plan_tempo_long_line_is_capped_and_overflow_reported(self):
        tempo, overflow = plan_tempo(6.0, 3.0, 1.35)

        self.assertEqual(tempo, 1.35)
        self.assertAlmostEqual(overflow, 6.0 / 1.35 - 3.0, places=3)


class SynthesizeTest(unittest.TestCase):
    def test_synthesize_text_goes_on_stdin_and_tempo_reaches_ffmpeg(self):
        # Arrange: natural 4.0 s, must fit 3.2 s → 1.25x; final file 3.2 s
        run = FakeRun([4.0, 3.2])

        # Act
        result = synthesize("-dash first line", "Linh", Path("/tmp/out.wav"), max_duration=3.2,
                            known_voices=VOICES, run=run)

        # Assert
        say_cmd, say_kwargs = run.commands[0]
        self.assertEqual(say_cmd[:3], ["say", "-v", "Linh"])
        self.assertNotIn("-dash first line", say_cmd)
        self.assertEqual(say_kwargs["input"], "-dash first line")
        ffmpeg_cmd, ffmpeg_kwargs = run.commands[2]
        self.assertEqual(ffmpeg_kwargs["stdin"], subprocess.DEVNULL)
        self.assertIn("timeout", ffmpeg_kwargs)
        self.assertIn("atempo=1.25", ffmpeg_cmd)
        self.assertEqual((result["tempo"], result["overflow"], result["duration"]), (1.25, 0.0, 3.2))

    def test_synthesize_unknown_voice_is_refused_before_running_anything(self):
        run = FakeRun([])

        with self.assertRaises(SynthesizeError):
            synthesize("xin chào", "Nobody", Path("/tmp/out.wav"), known_voices=VOICES, run=run)
        self.assertEqual(run.commands, [])

    def test_synthesize_blank_text_is_refused(self):
        with self.assertRaises(SynthesizeError):
            synthesize("   ", "Linh", Path("/tmp/out.wav"), known_voices=VOICES, run=FakeRun([]))

    def test_synthesize_speedup_out_of_range_is_refused(self):
        with self.assertRaises(SynthesizeError):
            synthesize("x", "Linh", Path("/tmp/out.wav"), max_speedup=3.0, known_voices=VOICES, run=FakeRun([]))


if __name__ == "__main__":
    unittest.main()
