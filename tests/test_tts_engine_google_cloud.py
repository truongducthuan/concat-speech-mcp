import base64
import io
import json
import socket
import types
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from concat_speech_mcp.process import EngineError
from concat_speech_mcp.synthesize import SynthesizeError, engine_named, list_voices, synthesize
from concat_speech_mcp.tools import call_tool
from concat_speech_mcp.tts_engine_google_cloud import api_key, fetch_json

KEY = "fake-google-key-123"
VOICES_REPLY = {"voices": [
    {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Aoede", "ssmlGender": "FEMALE"},
    {"languageCodes": ["ja-JP"], "name": "ja-JP-Chirp3-HD-Kore", "ssmlGender": "FEMALE"},
]}
WAV_BYTES = b"RIFF....WAVEfmt "


class FakeFetch:
    """Answers the voices listing and synthesis; records what was asked."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, payload=None):
        self.calls.append((url, payload))
        if url.endswith("/voices"):
            return VOICES_REPLY
        return {"audioContent": base64.b64encode(WAV_BYTES).decode()}


class FakeRun:
    """ffprobe answers fixed durations; ffmpeg records its input file's bytes."""

    def __init__(self, durations):
        self.durations = list(durations)
        self.commands = []
        self.ffmpeg_input = None

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd[0] == "ffmpeg":
            self.ffmpeg_input = Path(cmd[cmd.index("-i") + 1]).read_bytes()
        out = f"{self.durations.pop(0)}\n" if cmd[0] == "ffprobe" else ""
        return types.SimpleNamespace(stdout=out, stderr="", returncode=0)


class EngineChoiceTest(unittest.TestCase):
    def test_engine_named_nothing_set_is_macos(self):
        self.assertEqual(engine_named(None, env={})[0], "macos")

    def test_engine_named_environment_picks_google(self):
        self.assertEqual(engine_named(None, env={"CONCAT_SPEECH_ENGINE": "google"})[0], "google")

    def test_engine_named_argument_beats_environment(self):
        self.assertEqual(engine_named("macos", env={"CONCAT_SPEECH_ENGINE": "google"})[0], "macos")

    def test_engine_named_unknown_is_refused(self):
        with self.assertRaises(SynthesizeError):
            engine_named("retell", env={})


class GoogleSynthesizeTest(unittest.TestCase):
    def test_google_synthesize_asks_voice_in_its_language_and_converts_reply_audio(self):
        # Arrange
        fetch, run = FakeFetch(), FakeRun([2.0, 2.0])

        # Act
        result = synthesize("Hãy cứ tiếp tục", "vi-VN-Chirp3-HD-Aoede", Path("/tmp/out.wav"),
                            engine="google", run=run, fetch=fetch)

        # Assert
        url, payload = fetch.calls[-1]
        self.assertTrue(url.endswith("/text:synthesize"))
        self.assertEqual(payload["voice"], {"languageCode": "vi-VN", "name": "vi-VN-Chirp3-HD-Aoede"})
        self.assertEqual(payload["input"], {"text": "Hãy cứ tiếp tục"})
        self.assertEqual(run.ffmpeg_input, WAV_BYTES)
        self.assertNotIn("say", [c[0] for c in run.commands])
        self.assertEqual((result["engine"], result["rate"], result["duration"]), ("google", None, 2.0))

    def test_google_synthesize_makes_one_request_per_line_without_listing_voices(self):
        fetch = FakeFetch()

        synthesize("xin chào", "vi-VN-Chirp3-HD-Aoede", Path("/tmp/out.wav"), engine="google",
                   run=FakeRun([1.0, 1.0]), fetch=fetch)

        self.assertEqual([url.rsplit("/", 1)[-1] for url, _ in fetch.calls], ["text:synthesize"])

    def test_google_synthesize_reply_without_audio_is_reported(self):
        def fetch(url, payload=None):
            return {}

        with self.assertRaisesRegex(EngineError, "without audio"):
            synthesize("xin chào", "vi-VN-Chirp3-HD-Aoede", Path("/tmp/out.wav"), engine="google",
                       run=FakeRun([]), fetch=fetch)

    def test_google_synthesize_rate_is_refused(self):
        with self.assertRaises(SynthesizeError):
            synthesize("xin chào", "vi-VN-Chirp3-HD-Aoede", Path("/tmp/out.wav"), rate=185, engine="google",
                       run=FakeRun([]), fetch=FakeFetch())

    def test_google_list_voices_filters_by_language(self):
        voices = list_voices("vi", engine="google", fetch=FakeFetch())

        self.assertEqual([(v["name"], v["locale"], v["language"]) for v in voices],
                         [("vi-VN-Chirp3-HD-Aoede", "vi-VN", "vi")])


class GoogleFetchTest(unittest.TestCase):
    def test_google_api_key_missing_raises_named_variable(self):
        with self.assertRaisesRegex(EngineError, "GOOGLE_TTS_API_KEY is not set"):
            api_key(env={})

    def test_google_fetch_sends_key_in_header_not_in_url(self):
        # Arrange
        seen = {}

        def urlopen(request, timeout):
            seen["request"], seen["timeout"] = request, timeout
            return io.BytesIO(b'{"voices": []}')

        # Act
        reply = fetch_json("https://example.test/v1/voices", key=KEY, urlopen=urlopen)

        # Assert
        self.assertEqual(reply, {"voices": []})
        self.assertNotIn(KEY, seen["request"].full_url)
        self.assertEqual(seen["request"].get_header("X-goog-api-key"), KEY)
        self.assertEqual(seen["request"].get_method(), "GET")

    def test_google_fetch_refusal_reports_google_reason_without_key(self):
        # Arrange: Google echoes the key back in its message
        body = json.dumps({"error": {"message": f"API key {KEY} not valid"}}).encode()

        def urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(body))

        # Act
        with self.assertRaises(EngineError) as caught:
            fetch_json("https://example.test/v1/text:synthesize", {"input": {}}, key=KEY, urlopen=urlopen)

        # Assert
        message = str(caught.exception)
        self.assertIn("(400)", message)
        self.assertIn("not valid", message)
        self.assertNotIn(KEY, message)

    def test_google_fetch_unreachable_reports_reason_without_key(self):
        def urlopen(request, timeout):
            raise urllib.error.URLError(f"proxy refused {KEY}")

        with self.assertRaisesRegex(EngineError, "could not reach Google Text-to-Speech") as caught:
            fetch_json("https://example.test/v1/voices", key=KEY, urlopen=urlopen)
        self.assertNotIn(KEY, str(caught.exception))

    def test_google_fetch_timeout_reports_unreachable(self):
        def urlopen(request, timeout):
            raise socket.timeout("timed out")

        with self.assertRaisesRegex(EngineError, "could not reach Google Text-to-Speech: timed out"):
            fetch_json("https://example.test/v1/voices", key=KEY, urlopen=urlopen)

    def test_google_fetch_non_json_reply_is_reported(self):
        def urlopen(request, timeout):
            return io.BytesIO(b"<html>captive portal</html>")

        with self.assertRaisesRegex(EngineError, "not JSON"):
            fetch_json("https://example.test/v1/voices", key=KEY, urlopen=urlopen)

    def test_google_list_voices_skips_entries_without_name(self):
        def fetch(url, payload=None):
            return {"voices": [{"languageCodes": ["vi-VN"]}, VOICES_REPLY["voices"][0]]}

        voices = list_voices(engine="google", fetch=fetch)

        self.assertEqual([v["name"] for v in voices], ["vi-VN-Chirp3-HD-Aoede"])


class ToolArgumentsTest(unittest.TestCase):
    def test_tools_speech_synthesize_passes_engine_and_rate_through(self):
        with mock.patch("concat_speech_mcp.tools.synthesize", return_value={}) as fake:
            call_tool("speech_synthesize", {"text": "x", "voice": "v", "engine": "google", "rate": 185,
                                            "output": str(Path.home() / "concat-speech-x.wav")})

        self.assertEqual((fake.call_args.kwargs["engine"], fake.call_args.kwargs["rate"]), ("google", 185))

    def test_tools_speech_voices_passes_engine_through(self):
        with mock.patch("concat_speech_mcp.tools.list_voices", return_value=[]) as fake:
            call_tool("speech_voices", {"language": "vi", "engine": "google"})

        fake.assert_called_once_with("vi", engine="google")


if __name__ == "__main__":
    unittest.main()
