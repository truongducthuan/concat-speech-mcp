"""Scene worker: an HTML page played frame by frame in Chrome, into an mp4 or stills.

Runs in the TTS venv (python -I) with Playwright, driving the Google Chrome
installed on the machine (no browser download). One JSON request on stdin:

    {"html", "width", "height", "fps", "duration", "output"?, "stills"?: [seconds], "stillsDir"?}

and one JSON reply on stdout: {"output", "frames", "stills", "warnings"} or {"error"}.

Time is never real: before each frame every animation on the page is paused
and set to that moment, so CSS animations and transitions, the Web
Animations API, <video> elements and anything registered with
scene.on(t => ...) (GSAP: scene.on(t => timeline.seek(t))) land on exactly the
same frame however slow the machine is. requestAnimationFrame loops and
setTimeout chains are NOT driven: write motion with the means above.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

RUNTIME = """
(() => {
  const handlers = [];
  window.scene = Object.assign(window.scene || {}, {
    t: 0, ...__INFO__,
    on(fn) { handlers.push(fn); try { fn(this.t); } catch (e) { console.error(e); } },
  });
  window.__sceneSeek = async (t) => {
    window.scene.t = t;
    for (const a of document.getAnimations()) { a.pause(); a.currentTime = t * 1000; }
    for (const fn of handlers) fn(t);
    await Promise.all([...document.querySelectorAll('video')].map((v) => {
      v.pause(); v.muted = true;
      let at = Number(v.dataset.start || 0) + t * Number(v.dataset.rate || 1);
      if (v.duration) at = v.loop ? at % v.duration : Math.min(at, v.duration - 0.04);
      if (Math.abs(v.currentTime - at) < 0.001) return null;
      return new Promise((done) => { v.addEventListener('seeked', done, { once: true }); v.currentTime = at; });
    }));
    await document.fonts.ready;
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
  };
})();
"""


# every <video> knows its length before the first seek (or has failed, which the page errors report)
VIDEOS_READY = """
() => Promise.all([...document.querySelectorAll('video')].map((v) => v.readyState >= 1 ? null :
  new Promise((done) => { v.addEventListener('loadedmetadata', done, { once: true });
                          v.addEventListener('error', done, { once: true }); setTimeout(done, 20000); })))
"""


def render(spec):
    from playwright.sync_api import sync_playwright

    width, height, fps, duration = int(spec["width"]), int(spec["height"]), int(spec["fps"]), float(spec["duration"])
    warnings = []
    info = json.dumps({"width": width, "height": height, "fps": fps, "duration": duration})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required",
                                                                    "--hide-scrollbars"])
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.on("pageerror", lambda error: warnings.append(f"page error: {error}"))
            page.on("console", lambda m: m.type == "error" and warnings.append(f"console: {m.text}"[:300]))
            # Chrome aborts a <video>'s first request and refetches it in ranges: not a missing file
            page.on("requestfailed", lambda r: (r.resource_type == "media" and "ABORTED" in (r.failure or ""))
                    or warnings.append(f"not loaded: {r.url[:200]} ({r.failure})"))
            page.add_init_script(RUNTIME.replace("__INFO__", info))
            page.goto(Path(spec["html"]).resolve().as_uri(), wait_until="load", timeout=60000)
            # a page with several large videos keeps fetching ranges and may never go network-idle
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                warnings.append("the page kept loading after 15 s (large videos?); rendering anyway")
            page.evaluate(VIDEOS_READY)
            page.evaluate("() => document.fonts.ready.then(() => true)")
            stills = []
            for t in spec.get("stills") or []:
                t = min(max(float(t), 0.0), duration)
                page.evaluate("t => window.__sceneSeek(t)", t)
                target = Path(spec["stillsDir"]) / f"{Path(spec['html']).stem}-{t:06.2f}s.png"
                page.screenshot(path=str(target), type="png")
                stills.append(str(target))
            frames = 0
            if spec.get("output"):
                frames = encode(page, spec["output"], fps, duration)
        finally:
            browser.close()
    return {"output": spec.get("output"), "frames": frames, "stills": stills, "warnings": warnings[:20]}


def encode(page, output, fps, duration):
    total = max(1, round(duration * fps))
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
         "-movflags", "+faststart", output],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for frame in range(total):
            page.evaluate("t => window.__sceneSeek(t)", frame / fps)
            ffmpeg.stdin.write(page.screenshot(type="jpeg", quality=95))
        ffmpeg.stdin.close()
    except BaseException:
        ffmpeg.kill()
        raise
    if ffmpeg.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {ffmpeg.stderr.read().decode('utf-8', 'replace')[-400:]}")
    return total


def main():
    real_stdout, sys.stdout = sys.stdout, sys.stderr
    started = time.time()
    try:
        reply = render(json.loads(sys.stdin.read()))
        reply["seconds"] = round(time.time() - started, 1)
    except Exception as failure:
        reply = {"error": f"{type(failure).__name__}: {failure}"[:800]}
    real_stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
