"""VieNeu-TTS worker: runs in the TTS venv (python -I) and stays up between lines.

Loading the model takes seconds, reading a line about real time on CPU, so
the server starts this once and sends it one JSON request per line on stdin;
each gets one JSON line back on stdout:

    {"cmd": "voices"}                                -> {"voices": [{name, locale, language, description}]}
    {"cmd": "say", "text", "voice", "out"}           -> {"ok": true}            (48 kHz wav at out)
    {"cmd": "say", "text", "ref", "out"}             -> {"ok": true}            (voice cloned from ref audio)
    any failure                                      -> {"error": "..."}

Everything the libraries print goes to stderr, so stdout carries replies only.
Models (VieNeu-TTS v3 Turbo ONNX + MOSS audio codec, Apache-2.0) download once
to CONCAT_SPEECH_VIENEU_DIR (default ~/.cache/concat-speech/vieneu) as real
files: onnxruntime refuses external weights reached through the symlinks of
the Hugging Face cache.
"""
import json
import os
import sys
from pathlib import Path

MODELS = Path(os.environ.get("CONCAT_SPEECH_VIENEU_DIR") or Path.home() / ".cache" / "concat-speech" / "vieneu")


def fetch_into_models(repo, files, subfolder):
    from huggingface_hub import hf_hub_download

    dest = MODELS / repo.replace("/", "--")
    for name in files:
        try:
            hf_hub_download(repo, name, subfolder=subfolder or None, local_dir=dest)
        except Exception:
            if not name.endswith(".json"):  # optional metadata, as the engine's own fetch allows
                raise
    return dest / (subfolder or "")


def load():
    from vieneu import Vieneu
    from vieneu._v3_turbo_engine.onnx_runtime_lite import OnnxV3LiteEngine

    OnnxV3LiteEngine._fetch = staticmethod(fetch_into_models)
    return Vieneu()


def voices(tts):
    found = []
    for label, name in tts.list_preset_voices():
        found.append({"name": name, "locale": "vi-VN", "language": "vi",
                      "description": label.replace("⭐", "").strip()})
    return found


def say(tts, request):
    import soundfile

    if request.get("ref"):
        audio = tts.infer(text=request["text"], ref_audio=request["ref"], apply_watermark=False)
    else:
        names = {v["name"] for v in voices(tts)}
        if request["voice"] not in names:
            raise ValueError(f"unknown VieNeu voice {request['voice']!r}: one of {', '.join(sorted(names))}")
        audio = tts.infer(text=request["text"], voice=request["voice"], apply_watermark=False)
    if not len(audio):
        raise ValueError("VieNeu produced no audio for this text")
    soundfile.write(request["out"], audio, tts.sample_rate)
    return {"ok": True}


def main():
    replies = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)  # anything printed to stdout, by Python or native code, lands on stderr
    sys.stdout = sys.stderr
    tts = None
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            tts = tts or load()
            reply = {"voices": voices(tts)} if request["cmd"] == "voices" else say(tts, request)
        except Exception as failure:
            reply = {"error": f"{type(failure).__name__}: {failure}"}
        replies.write(json.dumps(reply, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
