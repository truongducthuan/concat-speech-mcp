"""The `vieneu` speech engine: VieNeu-TTS v3 Turbo, Vietnamese voices on this machine.

Free and offline after a one-time ~550 MB model download; 25 natural
Vietnamese voices (northern, central, southern; news, storytelling, ...)
that also read English words and numbers ("2,5%", "28/10") correctly. A
`voice` "clone:<name>" reads in a voice saved with speech_voice_clone
(voice_library), and an absolute path to a recording (3-8 s of clean speech)
clones that recording directly.

The model loads once into a worker process (tts_worker_vieneu.py, in the TTS
venv) that stays up while the server runs, so only the first line pays the
load; the worker ends when the server does (its stdin closes). Its log is
kept at ~/.cache/concat-speech/vieneu-worker.log for failures.
"""
import json
import selectors
import subprocess
import threading
from pathlib import Path

from . import local_python, voice_library
from .paths import existing_file
from .process import EngineError

DESCRIPTION = "VieNeu-TTS: natural Vietnamese voices, free and offline, voice cloning from a recording"
KEY_VARIABLE = None
PACKAGE = "vieneu"
RAW_SUFFIX = ".wav"
DEFAULT_RATES = {}
CHECKS_VOICE_FIRST = False  # the worker checks the name itself, and a path to a recording is a voice too
CLONE_SUFFIXES = (".wav", ".mp3", ".m4a", ".flac", ".ogg")
FIRST_TIMEOUT = 1800  # the first request may download the models
LINE_TIMEOUT = 600
LOG = Path.home() / ".cache" / "concat-speech" / "vieneu-worker.log"


def missing(env=None):
    return local_python.missing(PACKAGE, env)


class Worker:
    """One long-lived tts_worker_vieneu.py; requests go one at a time."""

    def __init__(self):
        self.process = None
        self.answered = False
        self.lock = threading.Lock()  # the HTTP transport may call from several threads

    def _start(self):
        problem = missing()
        if problem:
            raise EngineError(f"vieneu engine not ready: {problem}")
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "w", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                [str(local_python.interpreter()), "-I", str(local_python.worker_script("tts_worker_vieneu.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8")
        self.answered = False

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.process = None

    def request(self, payload):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._start()
            timeout = LINE_TIMEOUT if self.answered else FIRST_TIMEOUT
            try:
                self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                self.stop()
                raise EngineError(f"the VieNeu worker stopped: {_log_tail()}") from None
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                ready = selector.select(timeout)
            line = self.process.stdout.readline() if ready else ""
            if not line:
                reason = f"took longer than {timeout}s" if not ready else "stopped"
                self.stop()
                raise EngineError(f"the VieNeu worker {reason}: {_log_tail()}")
            self.answered = True
            reply = json.loads(line)
            if "error" in reply:
                raise EngineError(f"VieNeu: {reply['error']}")
            return reply


def _log_tail():
    try:
        lines = [l for l in LOG.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except OSError:
        return "no log"
    return " | ".join(lines[-5:])[-500:] or "no log"


WORKER = Worker()


def list_voices(run=None, fetch=None):
    clones = [{"name": v["voice"], "locale": "vi-VN", "language": "vi",
               "description": f"saved voice, from {Path(v['source']).name} at {v['start']:g} s"}
              for v in voice_library.saved()]
    return WORKER.request({"cmd": "voices"})["voices"] + clones


def render(text, voice, raw, rate, run=None, fetch=None):
    """Reads `text` in the preset `voice`, a saved "clone:<name>", or the recording at that path, into `raw`."""
    request = {"cmd": "say", "text": text, "out": str(raw)}
    if voice.startswith(voice_library.PREFIX):
        try:
            request["ref"] = str(voice_library.clip_of(voice))
        except voice_library.VoiceLibraryError as problem:
            raise EngineError(str(problem)) from None
    elif voice.startswith(("/", "~")):
        reference = existing_file(voice)
        if reference.suffix.lower() not in CLONE_SUFFIXES:
            raise EngineError(f"{reference.name}: a voice to clone must be a recording ({', '.join(CLONE_SUFFIXES)})")
        request["ref"] = str(reference)
    else:
        request["voice"] = voice
    WORKER.request(request)
