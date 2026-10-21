import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from concat_speech_mcp import speech_env_file
from concat_speech_mcp.process import EngineError
from concat_speech_mcp.synthesize import SynthesizeError, list_engines, list_voices, synthesize
from concat_speech_mcp.tts_engine_openai import api_key, fetch_audio
from tests.test_tts_engine_google_cloud import WAV_BYTES, FakeRun

KEY = "sk-test-key-123"


class FakeFetch:
    """Answers synthesis with fixed wav bytes; records each payload."""

    def __init__(self, audio=WAV_BYTES):
        self.audio = audio
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        return self.audio


class OpenAISynthesizeTest(unittest.TestCase):
    def test_openai_synthesize_sends_model_voice_text_and_converts_reply_audio(self):
        # Arrange
        fetch, run = FakeFetch(), FakeRun([2.0, 2.0])

        # Act
        result = synthesize("Hãy cứ tiếp tục", "nova", Path("/tmp/out.wav"), engine="openai", run=run, fetch=fetch)

        # Assert
        self.assertEqual(fetch.payloads, [{"model": "gpt-4o-mini-tts", "input": "Hãy cứ tiếp tục",
                                           "voice": "nova", "response_format": "wav"}])
        self.assertEqual(run.ffmpeg_input, WAV_BYTES)
        self.assertEqual((result["engine"], result["rate"]), ("openai", None))

    def test_openai_synthesize_unknown_voice_is_refused_before_a_billed_call(self):
        fetch = FakeFetch()

        with self.assertRaisesRegex(SynthesizeError, "unknown voice 'Linh' for the openai engine"):
            synthesize("xin chào", "Linh", Path("/tmp/out.wav"), engine="openai", run=FakeRun([]), fetch=fetch)
        self.assertEqual(fetch.payloads, [])

    def test_openai_synthesize_rate_is_refused(self):
        with self.assertRaisesRegex(SynthesizeError, "rate applies to the macos engine only"):
            synthesize("xin chào", "nova", Path("/tmp/out.wav"), rate=185, engine="openai",
                       run=FakeRun([]), fetch=FakeFetch())

    def test_openai_list_voices_multilingual_voices_match_any_language(self):
        voices = list_voices("vi", engine="openai")

        self.assertIn("nova", [v["name"] for v in voices])
        self.assertEqual({v["language"] for v in voices}, {"multi"})

    def test_list_voices_language_filter_keeps_that_language_and_multilingual_voices(self):
        # Arrange: one engine's catalogue mixing two languages and a multilingual voice
        catalogue = [{"name": "Linh", "language": "vi"}, {"name": "Kyoko", "language": "ja"},
                     {"name": "nova", "language": "multi"}]

        # Act
        with mock.patch("concat_speech_mcp.tts_engine_openai.list_voices", return_value=catalogue):
            voices = list_voices("vi", engine="openai")

        # Assert
        self.assertEqual([v["name"] for v in voices], ["Linh", "nova"])

    def test_openai_list_engines_configured_only_with_its_key(self):
        engines = {e["name"]: e for e in list_engines({"OPENAI_API_KEY": KEY})}

        self.assertTrue(engines["openai"]["configured"])
        self.assertFalse(engines["google"]["configured"])
        self.assertNotIn(KEY, repr(engines))


class OpenAIFetchTest(unittest.TestCase):
    def test_openai_api_key_missing_raises_named_variable(self):
        with self.assertRaisesRegex(EngineError, "OPENAI_API_KEY is not set"):
            api_key(env={})

    def test_openai_fetch_sends_key_as_bearer_and_returns_audio_bytes(self):
        # Arrange
        seen = {}

        def urlopen(request, timeout):
            seen["request"] = request
            return io.BytesIO(WAV_BYTES)

        # Act
        audio = fetch_audio({"input": "x"}, key=KEY, urlopen=urlopen)

        # Assert
        self.assertEqual(audio, WAV_BYTES)
        self.assertEqual(seen["request"].get_header("Authorization"), f"Bearer {KEY}")
        self.assertNotIn(KEY, seen["request"].full_url)

    def test_openai_fetch_refusal_reports_reason_without_key(self):
        # Arrange: OpenAI quotes part of the key back in its message
        body = json.dumps({"error": {"message": f"Incorrect API key provided: {KEY}"}}).encode()

        def urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(body))

        # Act
        with self.assertRaises(EngineError) as caught:
            fetch_audio({"input": "x"}, key=KEY, urlopen=urlopen)

        # Assert
        self.assertIn("(401)", str(caught.exception))
        self.assertIn("Incorrect API key", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))

    def test_openai_fetch_unreachable_reports_reason_without_key(self):
        def urlopen(request, timeout):
            raise urllib.error.URLError(f"proxy refused {KEY}")

        with self.assertRaisesRegex(EngineError, "could not reach OpenAI") as caught:
            fetch_audio({"input": "x"}, key=KEY, urlopen=urlopen)
        self.assertNotIn(KEY, str(caught.exception))

    def test_openai_fetch_empty_reply_is_reported(self):
        def urlopen(request, timeout):
            return io.BytesIO(b"")

        with self.assertRaisesRegex(EngineError, "without audio"):
            fetch_audio({"input": "x"}, key=KEY, urlopen=urlopen)


class SettingsFileLocationTest(unittest.TestCase):
    def test_env_file_default_is_dotenv_beside_server(self):
        root = Path(__file__).resolve().parent.parent

        self.assertEqual(speech_env_file.settings_path({}), root / ".env")
        self.assertTrue((root / "server.py").is_file())


if __name__ == "__main__":
    unittest.main()
