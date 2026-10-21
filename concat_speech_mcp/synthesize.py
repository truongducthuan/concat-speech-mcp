"""speech_voices and speech_synthesize: voice-over lines as wav files.

Concat 0.2.8's TTS has English and Chinese voices only, and is not reachable
over MCP, so lines are read by a speech engine of our own, picked per call
with `engine` or for the whole server with CONCAT_SPEECH_ENGINE:

- `macos` (default): the system voices (`say`), offline and free, dated;
- `google`: Google Cloud Text-to-Speech, natural voices, needs an API key;
- `openai`: OpenAI text-to-speech, natural multilingual voices, needs an API key.

Another engine is one module with list_voices/render beside these, named
in ENGINES. Whatever the engine, a line given `maxDuration` is then sped up
(ffmpeg atempo) to fit it, up to `maxSpeedup`; what still does not fit is
reported as overflow.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from . import tts_engine_google_cloud, tts_engine_macos_say, tts_engine_openai
from .process import run_checked
from .tts_engine_macos_say import DEFAULT_RATES, parse_voices  # noqa: F401  (part of this module's API)

ENGINES = {"macos": tts_engine_macos_say, "google": tts_engine_google_cloud, "openai": tts_engine_openai}
ENGINE_VARIABLE = "CONCAT_SPEECH_ENGINE"
DEFAULT_ENGINE = "macos"
DEFAULT_MAX_SPEEDUP = 1.35
MIN_RATE, MAX_RATE = 90, 360
SAMPLE_RATE = 48000


class SynthesizeError(RuntimeError):
    pass


def engine_named(name=None, env=None):
    """(name, module) of the engine asked for, else CONCAT_SPEECH_ENGINE's, else macos."""
    name = (name or (os.environ if env is None else env).get(ENGINE_VARIABLE) or DEFAULT_ENGINE).strip().lower()
    if name not in ENGINES:
        raise SynthesizeError(f"unknown engine {name!r}: use one of {', '.join(ENGINES)}")
    return name, ENGINES[name]


def settings_variables():
    """What the settings file may set: the engine choice and each engine's key."""
    return {ENGINE_VARIABLE} | {m.KEY_VARIABLE for m in ENGINES.values() if m.KEY_VARIABLE}


def list_engines(env=None):
    """Every engine with whether it is ready (its key is set) and which is the default; never the keys."""
    env = os.environ if env is None else env
    try:
        default = engine_named(None, env)[0]
    except SynthesizeError:
        default = None
    return [{"name": name, "description": module.DESCRIPTION, "default": name == default,
             "configured": module.KEY_VARIABLE is None or bool(env.get(module.KEY_VARIABLE, "").strip()),
             "needs": module.KEY_VARIABLE} for name, module in ENGINES.items()]


def list_voices(language=None, engine=None, run=subprocess.run, fetch=None):
    _, module = engine_named(engine)
    transport = {"fetch": fetch} if fetch else {}
    voices = module.list_voices(run=run, **transport)
    if language:
        voices = [v for v in voices if v["language"] in (language.lower(), "multi")]  # multi: reads any language
    return voices


def plan_tempo(duration, max_duration, max_speedup):
    """(tempo, overflow seconds) to fit `duration` into `max_duration`."""
    if max_duration is None or duration <= max_duration:
        return 1.0, 0.0
    if max_duration <= 0:
        return 1.0, round(duration, 3)
    tempo = min(duration / max_duration, max_speedup)
    return round(tempo, 3), round(max(0.0, duration / tempo - max_duration), 3)


def probe_duration(path, run=subprocess.run):
    out = run_checked(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                      run=run, timeout=60)
    return float(out.stdout.strip())


def synthesize(text, voice, output, max_duration=None, max_speedup=DEFAULT_MAX_SPEEDUP, rate=None,
               engine=None, known_voices=None, run=subprocess.run, fetch=None):
    """Reads `text` in `voice` with `engine` into the wav `output`; returns what was made."""
    text = " ".join(text.split())
    if not text:
        raise SynthesizeError("text is empty")
    if max_speedup < 1.0 or max_speedup > 2.0:
        raise SynthesizeError("maxSpeedup must be between 1 and 2")
    engine, module = engine_named(engine)
    if rate is not None and engine != "macos":
        raise SynthesizeError(f"rate applies to the macos engine only; with {engine}, fit lines with maxDuration")
    if rate is not None and not MIN_RATE <= rate <= MAX_RATE:
        raise SynthesizeError(f"rate must be between {MIN_RATE} and {MAX_RATE} words per minute")
    if known_voices is not None or module.CHECKS_VOICE_FIRST:
        voices = known_voices if known_voices is not None else list_voices(engine=engine, run=run, fetch=fetch)
        languages = {v["name"]: v["language"] for v in voices}
        if voice not in languages:
            raise SynthesizeError(f"unknown voice {voice!r} for the {engine} engine: call speech_voices for the list")
        language = languages[voice]
    else:
        language = None
    rate = int(round(rate)) if rate is not None else module.DEFAULT_RATES.get(language)
    transport = {"fetch": fetch} if fetch else {}
    with tempfile.TemporaryDirectory(prefix="concat-speech-") as work:
        raw = Path(work) / f"line{module.RAW_SUFFIX}"
        module.render(text, voice, raw, rate, run=run, **transport)
        natural = probe_duration(raw, run=run)
        tempo, overflow = plan_tempo(natural, max_duration, max_speedup)
        run_checked(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", f"atempo={tempo}",
                     "-ar", str(SAMPLE_RATE), "-ac", "1", str(output)], run=run, timeout=120)
    return {"output": str(output), "duration": round(probe_duration(output, run=run), 3),
            "naturalDuration": round(natural, 3), "tempo": tempo, "overflow": overflow, "voice": voice,
            "engine": engine, "rate": rate}
