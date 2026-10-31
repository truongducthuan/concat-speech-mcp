"""Saved voices: short reference clips the vieneu engine clones, kept by name.

A voice is cut once from any recording or video (a stretch of clean speech,
3-8 s: VieNeu listens to 8 s at most), levelled and stored as a 48 kHz mono
wav with a small JSON note of where it came from. It is then used as voice
"clone:<name>" with the vieneu engine, and listed by speech_voices.

Kept in CONCAT_SPEECH_VOICES_DIR, default ~/.local/share/concat-speech/voices.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from .paths import existing_file
from .process import run_checked

PREFIX = "clone:"
MIN_SECONDS, MAX_SECONDS = 3.0, 8.0
NAME = re.compile(r"^[\w][\w \-]{0,39}$")  # letters (any script), digits, space, - and _


class VoiceLibraryError(ValueError):
    pass


def folder(env=None):
    env = os.environ if env is None else env
    return Path(env.get("CONCAT_SPEECH_VOICES_DIR") or Path.home() / ".local" / "share" / "concat-speech" / "voices")


def _checked_name(name):
    name = " ".join(str(name).split())
    if not NAME.match(name):
        raise VoiceLibraryError(f"voice name {name!r}: up to 40 letters, digits, spaces, - or _")
    return name


def clip_of(name):
    """The saved wav of voice `name` (with or without the clone: prefix)."""
    name = _checked_name(name[len(PREFIX):] if name.startswith(PREFIX) else name)
    clip = folder() / f"{name}.wav"
    if not clip.is_file():
        raise VoiceLibraryError(f"no saved voice {name!r}: save one with speech_voice_clone, "
                                f"or call speech_voices for the list")
    return clip


def saved():
    """Every saved voice: [{name, voice, source, start, duration, created}]."""
    voices = []
    for note in sorted(folder().glob("*.json")):
        try:
            info = json.loads(note.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if note.with_suffix(".wav").is_file():
            voices.append({**info, "voice": PREFIX + info["name"]})
    return voices


def save(name, source, start=0.0, duration=MAX_SECONDS, replace=False, run=subprocess.run):
    """Cuts `duration` s of `source` from `start` into the library as voice `name`; returns its note."""
    name = _checked_name(name)
    source = existing_file(source)
    if not MIN_SECONDS <= duration <= MAX_SECONDS:
        raise VoiceLibraryError(f"duration must be {MIN_SECONDS:g}-{MAX_SECONDS:g} s of clean speech")
    if start < 0:
        raise VoiceLibraryError("start must be 0 or more")
    home = folder()
    clip, note = home / f"{name}.wav", home / f"{name}.json"
    if clip.exists() and not replace:
        raise VoiceLibraryError(f"a voice named {name!r} is saved already: pass replace to overwrite it")
    home.mkdir(parents=True, exist_ok=True)
    work = home / f".{name}.{os.getpid()}.wav"
    try:
        # Speech only (-vn), one channel, levelled so a quiet recording clones as well as a loud one.
        run_checked(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
                     "-vn", "-ac", "1", "-ar", "48000", "-af", "loudnorm=I=-20:TP=-2", str(work)], run=run, timeout=120)
        got = float(run_checked(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(work)], run=run, timeout=60).stdout.strip() or 0)
        if got < MIN_SECONDS:
            raise VoiceLibraryError(f"only {got:.1f} s of audio from {start:g} s on in {source.name}: "
                                    f"need at least {MIN_SECONDS:g} s of speech")
        os.replace(work, clip)
    finally:
        work.unlink(missing_ok=True)
    info = {"name": name, "source": str(source), "start": round(start, 3), "duration": round(got, 3),
            "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    note.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**info, "voice": PREFIX + name, "clip": str(clip)}


def remove(name):
    clip = clip_of(name)
    clip.unlink()
    clip.with_suffix(".json").unlink(missing_ok=True)
    return {"removed": PREFIX + clip.stem}

