import json
import re
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from concat_speech_mcp import audio_sources, audio_tools, media_sources
from concat_speech_mcp.audio_tools import AudioError
from concat_speech_mcp.media_sources import MediaError

COMMONS_AUDIO = {"query": {"pages": {
    "5": {"pageid": 5, "index": 1, "title": "File:Calm.ogg", "imageinfo": [{
        "mime": "application/ogg", "url": "https://upload.example/calm.ogg", "descriptionurl": "https://c/Calm",
        "metadata": [{"name": "playtime_seconds", "value": 125.4}],
        "extmetadata": {"Artist": {"value": "Kevin MacLeod\n1821 S Ridge Rd"}, "LicenseShortName": {"value": "CC BY 3.0"},
                        "ObjectName": {"value": "Calm"}}}]},
    "6": {"pageid": 6, "index": 2, "title": "File:Jingle.ogg", "imageinfo": [{
        "mime": "application/ogg", "url": "https://upload.example/jingle.ogg",
        "metadata": [{"name": "playtime_seconds", "value": 9.0}],
        "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]},
    "7": {"pageid": 7, "index": 3, "title": "File:Talk.ogg", "imageinfo": [{
        "mime": "application/ogg", "url": "https://upload.example/talk.ogg",
        "metadata": [{"name": "playtime_seconds", "value": 200.0}],
        "extmetadata": {"LicenseShortName": {"value": "CC BY-NC 4.0"}}}]},
}}}
FREESOUND = {"results": [
    {"id": 11, "name": "whoosh fast", "username": "ann", "license": "http://creativecommons.org/publicdomain/zero/1.0/",
     "duration": 0.8, "url": "https://freesound.org/s/11/", "previews": {"preview-hq-mp3": "https://fs/11.mp3"}},
    {"id": 12, "name": "whoosh nc", "username": "bob", "license": "https://creativecommons.org/licenses/by-nc/4.0/",
     "duration": 1.1, "url": "https://freesound.org/s/12/", "previews": {"preview-hq-mp3": "https://fs/12.mp3"}},
]}


def get_from(replies, calls=None):
    def get(url, params=None, headers=None, what="", secret=None):
        if calls is not None:
            calls.append((url, params))
        return replies[url]
    return get


class AudioSearchTest(unittest.TestCase):
    def setUp(self):
        media_sources._found.clear()

    def test_commons_music_reads_length_keeps_duration_range_and_drops_noncommercial(self):
        get = get_from({"https://commons.wikimedia.org/w/api.php": COMMONS_AUDIO})

        found = media_sources.search("calm", kind="music", source="commons", min_duration=60, env={},
                                     get_json=get)["results"]

        self.assertEqual([r["id"] for r in found], ["commons-music:5"])
        self.assertEqual((found[0]["duration"], found[0]["author"], found[0]["creditRequired"]),
                         (125.4, "Kevin MacLeod", True))

    def test_noncommercial_kept_only_when_allowed(self):
        get = get_from({"https://commons.wikimedia.org/w/api.php": COMMONS_AUDIO})

        found = media_sources.search("calm", kind="music", source="commons", allow_noncommercial=True, env={},
                                     get_json=get)["results"]

        self.assertIn("commons-music:7", [r["id"] for r in found])

    def test_freesound_sfx_licence_from_url_and_key_as_token(self):
        calls = []
        get = get_from({"https://freesound.org/apiv2/search/text/": FREESOUND}, calls)

        found = media_sources.search("whoosh", kind="sfx", source="freesound", max_duration=2,
                                     env={"FREESOUND_API_KEY": "fk"}, get_json=get)["results"]

        self.assertEqual([(r["id"], r["license"], r["creditRequired"]) for r in found],
                         [("freesound-sfx:11", "CC0", False)])
        self.assertEqual(calls[0][1]["token"], "fk")
        self.assertEqual(calls[0][1]["filter"], 'duration:[0 TO 2] license:("Attribution" OR "Creative Commons 0")')

    def test_jamendo_failure_is_reported_as_skipped(self):
        get = get_from({"https://api.jamendo.com/v3.0/tracks/": {
            "headers": {"status": "failed", "error_message": "Invalid Client Id jk"}, "results": []}})

        result = media_sources.search("piano", kind="music", source="jamendo", env={"JAMENDO_CLIENT_ID": "jk"},
                                      get_json=get)

        self.assertEqual(result["results"], [])
        self.assertIn("Invalid Client Id ***", result["skipped"]["jamendo"])

    def test_video_source_must_offer_that_kind(self):
        with self.assertRaisesRegex(MediaError, "source for sfx"):
            media_sources.search("x", kind="sfx", source="pexels", env={})

    def test_cc_license_names_and_commercial_use(self):
        self.assertEqual(audio_sources.cc_license("https://creativecommons.org/licenses/by-sa/4.0/"), ("CC BY-SA 4.0", True))
        self.assertFalse(audio_sources.commercial("CC BY-NC-SA 3.0"))
        self.assertTrue(audio_sources.commercial("Pixabay Content License"))


class AudioFetchTest(unittest.TestCase):
    def test_fetch_music_in_another_format_is_transcoded_to_the_asked_suffix(self):
        media_sources._found.clear()
        media_sources.search("calm", kind="music", source="commons", env={},
                             get_json=get_from({"https://commons.wikimedia.org/w/api.php": COMMONS_AUDIO}))
        commands = []

        def run(cmd, **kwargs):
            commands.append(cmd)
            Path(cmd[-1]).write_bytes(b"RIFF")
            return types.SimpleNamespace(stdout="", stderr="", returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            downloaded = []
            made = media_sources.fetch("commons-music:5", Path(tmp) / "bed.wav",
                                       download=lambda url, target, what="": downloaded.append(target) or 4, run=run)

            self.assertTrue(made["output"].endswith("bed.wav"))
            self.assertEqual(downloaded[0].suffix, ".ogg")
            self.assertEqual(commands[0][-1], str(Path(tmp) / "bed.wav"))
            self.assertFalse(downloaded[0].exists())


class AudioToolsCheckTest(unittest.TestCase):
    def test_music_fit_refuses_bad_level_fades_and_duck(self):
        with tempfile.NamedTemporaryFile(suffix=".wav") as song:
            for kwargs in ({"level": -5}, {"fade_in": 3, "fade_out": 3}, {"duck": 30}):
                with self.assertRaises(AudioError):
                    audio_tools.music_fit(song.name, "/tmp/x.wav", 5, **kwargs)

    def test_sfx_make_refuses_unknown_kind(self):
        with self.assertRaises(AudioError):
            audio_tools.sfx_make("laser", "/tmp/x.wav")


def loudness(path, start=None, length=None):
    cut = (["-ss", str(start), "-t", str(length)] if start is not None else [])
    out = subprocess.run(["ffmpeg", *cut, "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", out)[-1])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class AudioToolsRealTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        # a 6 s "song" (two tones) and a 2 s "voice" (one tone)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=330:d=6", "-f", "lavfi",
                        "-i", "sine=f=495:d=6", "-filter_complex", "amix=2", str(self.dir / "song.wav")], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=200:d=2", str(self.dir / "voice.wav")],
                       check=True)

    def test_music_fit_loops_to_length_levels_and_ducks_under_the_voice(self):
        made = audio_tools.music_fit(str(self.dir / "song.wav"), self.dir / "bed.wav", 10, start=1, fade_in=0,
                                     fade_out=0, voices=[{"file": str(self.dir / "voice.wav"), "at": 6}])

        self.assertEqual((made["duration"], made["looped"], made["ducked"]), (10.0, True, True))
        before, during = loudness(made["output"], 2, 3), loudness(made["output"], 6.3, 1.5)
        self.assertAlmostEqual(before, -30, delta=2)
        self.assertLess(during, before - 4)

    def test_audio_master_reaches_target_and_keeps_the_picture(self):
        video = self.dir / "v.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=6", "-i",
                        str(self.dir / "song.wav"), "-af", "volume=-12dB", "-shortest", str(video)], check=True)

        made = audio_tools.audio_master(str(video), self.dir / "m.mp4")

        self.assertAlmostEqual(made["after"]["lufs"], -14, delta=1)
        self.assertLess(made["before"]["lufs"], -20)
        codecs = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                 str(self.dir / "m.mp4")], capture_output=True, text=True).stdout.split()
        self.assertEqual(codecs, ["video", "audio"])

    def test_sfx_make_every_kind_is_audible_and_never_clips(self):
        for kind in audio_tools.SFX:
            made = audio_tools.sfx_make(kind, self.dir / f"{kind}.wav")
            out = subprocess.run(["ffmpeg", "-i", made["output"], "-af", "astats", "-f", "null", "-"],
                                 capture_output=True, text=True).stderr
            peak = float(re.findall(r"Peak level dB:\s+(-?[\d.]+)", out)[-1])
            self.assertTrue(-12 < peak < -1, (kind, peak))


@unittest.skipUnless(shutil.which("ffmpeg") and audio_tools.local_python.missing("librosa") is None, "no librosa")
class MusicBeatsRealTest(unittest.TestCase):
    def test_beats_of_a_120_bpm_click_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            clicks = Path(tmp) / "clicks.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "aevalsrc=exprs='sin(2*PI*1000*t)*lt(mod(t\\,0.5)\\,0.03)':s=22050:d=12",
                            str(clicks)], check=True)

            found = audio_tools.music_beats(str(clicks))

        self.assertAlmostEqual(found["tempo"], 120, delta=3)
        gaps = [b - a for a, b in zip(found["beats"], found["beats"][1:])]
        self.assertAlmostEqual(sum(gaps) / len(gaps), 0.5, delta=0.02)


if __name__ == "__main__":
    unittest.main()
