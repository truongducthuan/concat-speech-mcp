"""speech_voices and speech_synthesize: voice-over lines as wav files.

Concat 0.2.8's TTS has English and Chinese voices only, and is not reachable
over MCP. Until a better engine is chosen (phase 3), the system voices of
macOS (`say`) are used: they include Japanese (Kyoko, ...) and Vietnamese
(Linh). A line given `maxDuration` is sped up (ffmpeg atempo) to fit it, up
to `maxSpeedup`; what still does not fit is reported as overflow.
"""
import re
import subprocess
import tempfile
from pathlib import Path

from .process import run_checked

VOICE_LINE = re.compile(r"^(?P<name>.+?)\s+(?P<locale>[a-z]{2,3}_[A-Z0-9]{2,3})\s+#\s?(?P<sample>.*)$")
DEFAULT_MAX_SPEEDUP = 1.35
SAMPLE_RATE = 48000


class SynthesizeError(RuntimeError):
    pass


def parse_voices(say_listing):
    """Voices from `say -v ?`: [{name, locale, language, sample}]."""
    voices = []
    for line in say_listing.splitlines():
        match = VOICE_LINE.match(line.rstrip())
        if match:
            locale = match["locale"]
            voices.append({"name": match["name"].strip(), "locale": locale,
                           "language": locale.split("_")[0], "sample": match["sample"].strip()})
    return voices


def list_voices(language=None, run=subprocess.run):
    out = run_checked(["say", "-v", "?"], run=run, timeout=60)
    voices = parse_voices(out.stdout)
    if language:
        voices = [v for v in voices if v["language"] == language.lower()]
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


def synthesize(text, voice, output, max_duration=None, max_speedup=DEFAULT_MAX_SPEEDUP,
               known_voices=None, run=subprocess.run):
    """Reads `text` in `voice` into the wav `output`; returns what was made."""
    text = " ".join(text.split())
    if not text:
        raise SynthesizeError("text is empty")
    if max_speedup < 1.0 or max_speedup > 2.0:
        raise SynthesizeError("maxSpeedup must be between 1 and 2")
    names = {v["name"] for v in (known_voices if known_voices is not None else list_voices(run=run))}
    if voice not in names:
        raise SynthesizeError(f"unknown voice {voice!r}: call speech_voices for the list")
    with tempfile.TemporaryDirectory(prefix="concat-speech-") as work:
        raw = Path(work) / "line.aiff"
        # Text on stdin, so a line starting with "-" is never read as an option.
        run_checked(["say", "-v", voice, "-o", str(raw)], run=run, timeout=120, input=text)
        natural = probe_duration(raw, run=run)
        tempo, overflow = plan_tempo(natural, max_duration, max_speedup)
        run_checked(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", f"atempo={tempo}",
                     "-ar", str(SAMPLE_RATE), "-ac", "1", str(output)], run=run, timeout=120)
    return {"output": str(output), "duration": round(probe_duration(output, run=run), 3),
            "naturalDuration": round(natural, 3), "tempo": tempo, "overflow": overflow, "voice": voice}
