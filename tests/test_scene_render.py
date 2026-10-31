import json
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from concat_speech_mcp import scene_render
from concat_speech_mcp.process import EngineError
from concat_speech_mcp.scene_render import SceneError

PAGE = """<!doctype html><html><head><style>
html, body { margin: 0; width: 1080px; height: 1080px; background: #000; }
#box { position: absolute; left: 0; top: 0; width: 100px; height: 100px; background: #fff;
       animation: move 2s linear both; }
@keyframes move { to { transform: translateX(980px); } }
</style></head><body><div id="box"></div><div id="n"></div>
<script>scene.on(t => document.getElementById('n').dataset.t = t);</script></body></html>"""


class SceneRenderTest(unittest.TestCase):
    def setUp(self):
        # Visible folder under home: outputs follow the server's write rules.
        self.tmp = tempfile.TemporaryDirectory(dir=Path.home(), prefix="concat-scene-test-")
        self.addCleanup(self.tmp.cleanup)
        self.page = Path(self.tmp.name) / "scene.html"
        self.page.write_text(PAGE, encoding="utf-8")

    def test_render_refuses_bad_size_fps_duration_and_nothing_to_make(self):
        for kwargs in ({"output": "/x.mp4", "size": "21:9"}, {"output": "/x.mp4", "fps": 50},
                       {"output": "/x.mp4", "duration": 0}, {}):
            with self.assertRaises(SceneError):
                scene_render.render(str(self.page), **kwargs)

    def test_render_sends_frame_size_and_reports_worker_error(self):
        sent = {}

        def run(cmd, **kwargs):
            sent.update(json.loads(kwargs["input"]))
            return types.SimpleNamespace(stdout=json.dumps({"error": "TimeoutError: page did not load"}),
                                         stderr="", returncode=0)

        with mock.patch.object(scene_render, "missing", return_value=None):
            with self.assertRaisesRegex(EngineError, "page did not load"):
                scene_render.render(str(self.page), output=str(Path(self.tmp.name) / "a.mp4"), size="9:16",
                                    duration=2, run=run)

        self.assertEqual((sent["width"], sent["height"], sent["fps"], sent["duration"]), (1080, 1920, 30, 2.0))

    @unittest.skipUnless(shutil.which("ffmpeg") and scene_render.missing() is None
                         and Path("/Applications/Google Chrome.app").exists(), "Playwright, Chrome or ffmpeg missing")
    def test_render_real_chrome_frames_follow_scene_time(self):
        out = Path(self.tmp.name) / "scene.mp4"

        made = scene_render.render(str(self.page), output=str(out), duration=2, size="1:1", fps=24, stills=[0, 1])

        self.assertEqual((made["frames"], made["warnings"]), (48, []))
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,nb_frames",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip().strip(",")
        self.assertEqual(probe, "1080,1080,48")
        # at 1 s the box is half way: its white pixels sit near x = 490..590, not at the left edge
        crop = subprocess.run(["ffmpeg", "-v", "error", "-i", made["stills"][1], "-vf", "crop=1080:1:0:50",
                               "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
        white = [x for x, v in enumerate(crop) if v > 200]
        self.assertAlmostEqual(white[0], 490, delta=6)


if __name__ == "__main__":
    unittest.main()
