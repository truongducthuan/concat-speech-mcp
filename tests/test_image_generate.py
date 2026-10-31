import base64
import json
import tempfile
import types
import unittest
from pathlib import Path

from concat_speech_mcp import image_generate
from concat_speech_mcp.image_generate import ImageError
from concat_speech_mcp.process import EngineError

PNG = b"\x89PNG\r\n\x1a\nfake"
KEY = "secret-key-123"


class FakePost:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, url, body, headers=None, what="", secret=None):
        self.calls.append({"url": url, "body": body, "headers": headers, "secret": secret})
        return self.reply


class FakeRun:
    """ffprobe answers `size`; ffmpeg writes its output file."""

    def __init__(self, size):
        self.size = size
        self.commands = []

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(PNG)
        out = self.size if cmd[0] == "ffprobe" else ""
        return types.SimpleNamespace(stdout=out, stderr="", returncode=0)


class ImageGenerateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "shot.png"

    def test_openai_16_9_asks_landscape_size_then_crops_to_fill_the_frame(self):
        post = FakePost({"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
        run = FakeRun("1536x1024")

        made = image_generate.generate("a lake at dawn", self.out, engine="openai", env={"OPENAI_API_KEY": KEY},
                                       post=post, run=run)

        call = post.calls[0]
        self.assertEqual(call["url"], "https://api.openai.com/v1/images/generations")
        self.assertEqual((call["body"]["size"], call["body"]["model"]), ("1536x1024", "gpt-image-2"))
        self.assertEqual((call["headers"]["Authorization"], call["secret"]), (f"Bearer {KEY}", KEY))
        crop = run.commands[-1]
        self.assertEqual(crop[crop.index("-vf") + 1], "crop=1536:864")
        self.assertEqual((made["width"], made["height"]), (1536, 864))
        book = json.loads((Path(self.tmp.name) / "credits.json").read_text())
        self.assertEqual((book[0]["aiGenerated"], book[0]["prompt"]), (True, "a lake at dawn"))

    def test_openai_with_references_uses_edits_as_multipart(self):
        ref = Path(self.tmp.name) / "hero.png"
        ref.write_bytes(PNG)
        post = FakePost({"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

        image_generate.generate("the hero waves", self.out, aspect="1:1", references=[str(ref)], engine="openai",
                                env={"OPENAI_API_KEY": KEY}, post=post, run=FakeRun("1024x1024"))

        call = post.calls[0]
        self.assertEqual(call["url"], "https://api.openai.com/v1/images/edits")
        self.assertIn(b'name="image[]"; filename="hero.png"', call["body"])
        self.assertTrue(call["headers"]["Content-Type"].startswith("multipart/form-data; boundary="))

    def test_gemini_sends_aspect_and_references_inline_and_keeps_exact_aspect(self):
        ref = Path(self.tmp.name) / "hero.jpg"
        ref.write_bytes(b"jpeg")
        post = FakePost({"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "image/png", "data": base64.b64encode(PNG).decode()}}]}}]})
        run = FakeRun("1344x768")

        made = image_generate.generate("the hero in a market", self.out, references=[str(ref)],
                                       env={"GEMINI_API_KEY": KEY}, post=post, run=run)

        body = post.calls[0]["body"]
        self.assertIn("gemini-2.5-flash-image:generateContent", post.calls[0]["url"])
        self.assertEqual(body["generationConfig"]["imageConfig"]["aspectRatio"], "16:9")
        self.assertEqual(body["contents"][0]["parts"][1]["inlineData"]["mimeType"], "image/jpeg")
        self.assertEqual(made["engine"], "gemini")  # the only engine with a key is the default
        self.assertEqual(self.out.read_bytes(), PNG)

    def test_gemini_without_picture_says_why(self):
        post = FakePost({"candidates": [{"finishReason": "SAFETY", "content": {"parts": [{"text": "cannot"}]}}]})

        with self.assertRaisesRegex(EngineError, r"without a picture \(SAFETY\): cannot"):
            image_generate.generate("x", self.out, engine="gemini", env={"GEMINI_API_KEY": KEY}, post=post,
                                    run=FakeRun("1x1"))

    def test_no_key_at_all_is_refused_before_any_call(self):
        post = FakePost({})

        with self.assertRaisesRegex(ImageError, "no image engine ready"):
            image_generate.generate("x", self.out, env={}, post=post)
        self.assertEqual(post.calls, [])

    def test_list_engines_default_follows_setting_then_first_with_key(self):
        engines = {e["name"]: e for e in image_generate.list_engines({"OPENAI_API_KEY": KEY,
                                                                      "GEMINI_IMAGE_MODEL": "gemini-x"})}

        self.assertTrue(engines["openai"]["default"])
        self.assertFalse(engines["gemini"]["configured"])
        self.assertEqual(engines["gemini"]["model"], "gemini-x")


if __name__ == "__main__":
    unittest.main()
