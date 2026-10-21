"""speech_transcribe: whisper.cpp over a media file, as caption-ready utterances.

Uses the model Concat itself downloads (Settings > Speech in the app), so the
words match what the window's own transcription would hear.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .process import run_checked
from .segmentation import detect_silences, group_tokens_by_span, speech_spans, tokens_from_whisper_json

MODELS = ("tiny", "base", "small")
WHISPER_TIMEOUT = 1800  # the small model runs ~10x realtime here: a 2-hour file still fits
NO_SPACE_LANGUAGES = ("ja", "zh")
CONCAT_MODEL_DIR = Path.home() / "Library/Application Support/app.concat.editor/whisper-models"


class TranscribeError(RuntimeError):
    pass


def whisper_cli():
    found = os.environ.get("CONCAT_SPEECH_WHISPER_CLI") or shutil.which("whisper-cli")
    if not found:
        raise TranscribeError("whisper-cli not found: install it (brew install whisper-cpp) "
                              "or set CONCAT_SPEECH_WHISPER_CLI")
    return found


def model_path(model):
    if model not in MODELS:
        raise TranscribeError(f"model must be one of {', '.join(MODELS)}")
    folder = Path(os.environ.get("CONCAT_SPEECH_MODEL_DIR", CONCAT_MODEL_DIR))
    path = folder / f"ggml-{model}.bin"
    if not path.is_file():
        raise TranscribeError(f"{path} is missing: download the '{model}' multilingual model "
                              "in Concat (Settings > Speech) or set CONCAT_SPEECH_MODEL_DIR")
    return path


def media_duration(path, run=subprocess.run):
    out = run_checked(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                      run=run)
    return float(out.stdout.strip())


def transcribe(source, language="auto", model="small", min_silence=0.35, run=subprocess.run):
    """Utterances of `source`: {language, duration, utterances: [{start, end, text}]}."""
    with tempfile.TemporaryDirectory(prefix="concat-speech-") as work:
        audio = Path(work) / "audio16k.wav"
        run_checked(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vn", "-ar", "16000", "-ac", "1",
                     str(audio)], run=run)
        stem = Path(work) / "whisper"
        threads = str(max(1, min(8, (os.cpu_count() or 4) - 2)))
        run_checked([whisper_cli(), "-m", str(model_path(model)), "-l", language, "-t", threads,
                     "-ojf", "-nfa", "--dtw", model, "-of", str(stem), str(audio)],
                    run=run, timeout=WHISPER_TIMEOUT)
        produced = Path(f"{stem}.json")
        if not produced.is_file():
            raise TranscribeError("whisper-cli finished but wrote no transcript")
        data = json.loads(produced.read_text(encoding="utf-8"))
        heard = data.get("result", {}).get("language", language)
        total = media_duration(audio, run=run)
        spans = speech_spans(detect_silences(audio, min_silence=min_silence, run=run), total)
    utterances = group_tokens_by_span(tokens_from_whisper_json(data), spans,
                                      drop_spaces=heard in NO_SPACE_LANGUAGES)
    return {"language": heard, "duration": round(total, 3), "model": model, "utterances": utterances}
