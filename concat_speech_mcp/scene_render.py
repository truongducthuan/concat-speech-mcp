"""scene_render: an HTML scene (motion graphics) into an mp4 clip for Concat, or stills to check it.

The agent writes the scene as a web page (text, numbers, charts, maps,
pictures moving with CSS animations, the Web Animations API, GSAP through
scene.on); scene_worker.py plays it frame by frame in the machine's Chrome and
encodes it. The clip is silent: the voice-over and music go on Concat's
timeline. Needs Playwright in the TTS venv (local_python) and Google Chrome.
"""
import json
import subprocess
from pathlib import Path

from . import local_python
from .paths import existing_file, writable_file
from .process import EngineError, run_checked

SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
FPS = (24, 25, 30, 60)
MAX_SECONDS = 300


class SceneError(ValueError):
    pass


def missing(env=None):
    return local_python.missing("playwright", env)


def render(html, output=None, duration=5.0, size="16:9", fps=30, stills=None, stills_dir=None, run=subprocess.run):
    page = existing_file(html)
    if page.suffix.lower() not in (".html", ".htm"):
        raise SceneError(f"{page.name}: the scene must be an .html file")
    if size not in SIZES:
        raise SceneError(f"size must be one of {', '.join(SIZES)}")
    if int(fps) not in FPS:
        raise SceneError(f"fps must be one of {', '.join(map(str, FPS))}")
    duration = float(duration)
    if not 0 < duration <= MAX_SECONDS:
        raise SceneError(f"duration must be more than 0 and at most {MAX_SECONDS} s")
    if not output and not stills:
        raise SceneError("give an output .mp4, or stills (seconds) to look at first")
    width, height = SIZES[size]
    spec = {"html": str(page), "width": width, "height": height, "fps": int(fps), "duration": duration}
    if output:
        spec["output"] = str(writable_file(output, (".mp4",)))
    if stills:
        folder = Path(stills_dir) if stills_dir else page.parent / "stills"
        writable_file(folder / "probe.png", (".png",))  # same rules as any output; creates the folder
        spec.update(stills=[float(t) for t in stills][:12], stillsDir=str(folder.resolve()))
    problem = missing()
    if problem:
        raise EngineError(f"scene rendering not ready: {problem}")
    frames = round(duration * int(fps)) if output else 0
    timeout = 120 + frames * 0.5  # ~0.05 s a frame here; ten times that before giving up
    out = run_checked([str(local_python.interpreter()), "-I", str(local_python.worker_script("scene_worker.py"))],
                      run=run, timeout=timeout, input=json.dumps(spec))
    reply = json.loads(out.stdout.strip().splitlines()[-1])
    if "error" in reply:
        raise EngineError(f"scene {page.name}: {reply['error']}")
    reply.update(size=f"{width}x{height}", fps=int(fps), duration=duration)
    if not reply.get("output"):
        reply.pop("output", None)
    return reply
