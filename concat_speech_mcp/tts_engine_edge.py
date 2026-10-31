"""The `edge` speech engine: Microsoft Edge's online neural voices, through edge-tts.

Free, no key, natural voices in many languages (Vietnamese: HoaiMy, NamMinh),
and it reports when each word is said, so a line comes back with word times
for karaoke captions. Needs the network, and edge-tts in the TTS venv
(local_python). The service is unofficial: it can refuse or change without
notice, and at times answers a third of requests without audio; the worker
retries a dropped line, and a line that still fails says to use vieneu.
"""
import json
import subprocess

from . import local_python
from .process import EngineError, run_checked

DESCRIPTION = "Microsoft Edge neural voices (edge-tts): free, natural, online, word timings for captions"
KEY_VARIABLE = None
PACKAGE = "edge_tts"
RAW_SUFFIX = ".mp3"
DEFAULT_RATES = {}
CHECKS_VOICE_FIRST = True  # an unknown name only comes back as "no audio received" after the retries
WORKER = local_python.worker_script("tts_worker_edge.py")
ATTEMPTS = 5  # as tts_worker_edge.py, which cannot import it
_voices = []  # the list is fetched once per server: it is ~300 voices over the network


def missing(env=None):
    return local_python.missing(PACKAGE, env)


def _worker(args, run, timeout, input=None):
    problem = missing()
    if problem:
        raise EngineError(f"edge engine not ready: {problem}")
    return run_checked([str(local_python.interpreter()), "-I", str(WORKER), *args], run=run, timeout=timeout,
                       input=input)


def list_voices(run=subprocess.run, fetch=None):
    if not _voices:
        _voices.extend(json.loads(_worker(["voices"], run, timeout=60).stdout))
    return list(_voices)


def render(text, voice, raw, rate, run=subprocess.run, fetch=None):
    """Reads `text` in `voice` into the mp3 `raw`; returns {words} (seconds of `raw`)."""
    try:
        return json.loads(_worker(["say", voice, str(raw)], run, timeout=180, input=text).stdout)
    except EngineError as failure:
        if "NoAudioReceived" not in str(failure):
            raise
        raise EngineError(f"Edge's speech service gave no audio for this line after {ATTEMPTS} tries (it drops "
                          f"requests at times): try again in a minute, or read it with the vieneu engine") from None
