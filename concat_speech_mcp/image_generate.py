"""image_engines and image_generate: pictures made from a description, for scenes in Concat.

Engines (each billed per picture by its provider, a few US cents):
- `openai`: OpenAI image generation (OPENAI_IMAGE_MODEL, default gpt-image-2),
  key in OPENAI_API_KEY; with reference pictures it uses the edits endpoint;
- `gemini`: Google Gemini image generation (GEMINI_IMAGE_MODEL, default
  gemini-2.5-flash-image), key in GEMINI_API_KEY (Google AI Studio).

Reference pictures (`references`, up to 4) keep a character, product or
style the same from scene to scene. The picture comes back at the provider's
nearest size and, unless `crop` is false, is centre-cropped to the asked
aspect so it fills the video frame. Each one is recorded in credits.json
beside it as AI-generated, with its prompt.
"""
import base64
import os
import subprocess
from pathlib import Path

from . import credits, web
from .paths import existing_file
from .process import EngineError, run_checked

ENGINE_VARIABLE = "CONCAT_IMAGE_ENGINE"
ASPECTS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "4:5": 4 / 5}
QUALITIES = ("low", "medium", "high")
REFERENCE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_REFERENCES = 4
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImageError(ValueError):
    pass


class OpenAIImages:
    KEY_VARIABLE = "OPENAI_API_KEY"
    MODEL_VARIABLE = "OPENAI_IMAGE_MODEL"
    DEFAULT_MODEL = "gpt-image-2"
    DESCRIPTION = "OpenAI image generation (gpt-image): follows long prompts well, references via edits"
    SIZES = {"16:9": "1536x1024", "4:3": "1536x1024", "9:16": "1024x1536", "3:4": "1024x1536", "4:5": "1024x1536",
             "1:1": "1024x1024"}

    def generate(self, prompt, aspect, quality, references, key, model, post=web.post):
        fields = {"model": model, "prompt": prompt, "size": self.SIZES[aspect], "quality": quality, "n": 1}
        if references:
            files = [("image[]", ref.name, ref.read_bytes(), REFERENCE_MIME[ref.suffix.lower()]) for ref in references]
            body, content_type = web.multipart({k: v for k, v in fields.items()}, files)
            reply = post("https://api.openai.com/v1/images/edits", body, what="OpenAI images", secret=key,
                         headers={"Authorization": f"Bearer {key}", "Content-Type": content_type})
        else:
            reply = post("https://api.openai.com/v1/images/generations", fields, what="OpenAI images", secret=key,
                         headers={"Authorization": f"Bearer {key}"})
        try:
            return base64.b64decode(reply["data"][0]["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise EngineError("OpenAI images answered without a picture") from None


class GeminiImages:
    KEY_VARIABLE = "GEMINI_API_KEY"
    MODEL_VARIABLE = "GEMINI_IMAGE_MODEL"
    DEFAULT_MODEL = "gemini-2.5-flash-image"
    DESCRIPTION = "Google Gemini image generation: fast, cheap, good at keeping a character from references"

    def generate(self, prompt, aspect, quality, references, key, model, post=web.post):
        parts = [{"text": prompt}]
        for ref in references:
            parts.append({"inlineData": {"mimeType": REFERENCE_MIME[ref.suffix.lower()],
                                         "data": base64.b64encode(ref.read_bytes()).decode("ascii")}})
        body = {"contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}}
        reply = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", body,
                     what="Gemini", secret=key, headers={"x-goog-api-key": key})
        candidate = (reply.get("candidates") or [{}])[0]
        for part in candidate.get("content", {}).get("parts", []):
            data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
            if data:
                return base64.b64decode(data)
        reason = candidate.get("finishReason") or reply.get("promptFeedback", {}).get("blockReason") or "no reason given"
        text = " ".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))[:200]
        raise EngineError(f"Gemini answered without a picture ({reason}){': ' + text if text else ''}")


ENGINES = {"openai": OpenAIImages(), "gemini": GeminiImages()}


def settings_variables():
    return {ENGINE_VARIABLE} | {e.KEY_VARIABLE for e in ENGINES.values()} | {e.MODEL_VARIABLE for e in ENGINES.values()}


def _configured(engine, env):
    return bool((env.get(engine.KEY_VARIABLE) or "").strip())


def list_engines(env=None):
    env = os.environ if env is None else env
    default = _default_name(env)
    return [{"name": name, "description": e.DESCRIPTION, "configured": _configured(e, env), "default": name == default,
             "needs": e.KEY_VARIABLE, "model": (env.get(e.MODEL_VARIABLE) or "").strip() or e.DEFAULT_MODEL}
            for name, e in ENGINES.items()]


def _default_name(env):
    chosen = (env.get(ENGINE_VARIABLE) or "").strip().lower()
    if chosen in ENGINES:
        return chosen
    return next((name for name, e in ENGINES.items() if _configured(e, env)), None)


def generate(prompt, output, aspect="16:9", quality="medium", references=(), engine=None, crop=True, env=None,
             post=web.post, run=subprocess.run):
    """Makes one picture of `prompt` into the .png `output`; returns what was made."""
    env = os.environ if env is None else env
    prompt = " ".join(str(prompt).split())
    if not prompt:
        raise ImageError("prompt is empty")
    if aspect not in ASPECTS:
        raise ImageError(f"aspect must be one of {', '.join(ASPECTS)}")
    if quality not in QUALITIES:
        raise ImageError(f"quality must be one of {', '.join(QUALITIES)}")
    name = (engine or _default_name(env) or "").strip().lower()
    if name not in ENGINES:
        raise ImageError(f"no image engine ready: put OPENAI_API_KEY or GEMINI_API_KEY in the .env file, "
                         f"or pass engine ({', '.join(ENGINES)})" if not engine else
                         f"unknown image engine {engine!r}: use one of {', '.join(ENGINES)}")
    chosen = ENGINES[name]
    key = (env.get(chosen.KEY_VARIABLE) or "").strip()
    if not key:
        raise EngineError(f"{chosen.KEY_VARIABLE} is not set: put it in the .env file (or run setup_speech.py)")
    refs = [existing_file(r) for r in (references or [])]
    if len(refs) > MAX_REFERENCES:
        raise ImageError(f"at most {MAX_REFERENCES} reference pictures")
    for ref in refs:
        if ref.suffix.lower() not in REFERENCE_MIME:
            raise ImageError(f"{ref.name}: a reference must be {', '.join(REFERENCE_MIME)}")
    model = (env.get(chosen.MODEL_VARIABLE) or "").strip() or chosen.DEFAULT_MODEL
    picture = chosen.generate(prompt, aspect, quality, refs, key, model, post=post)
    output = Path(output)
    raw = output.with_name(f".{output.stem}.raw{output.suffix}")
    raw.write_bytes(picture)
    try:
        width, height = _size(raw, run)
        if crop and abs(width / height - ASPECTS[aspect]) > 0.02:
            # centre crop to the asked aspect, so the picture fills the frame without bars
            target = ASPECTS[aspect]
            w, h = (round(height * target), height) if width / height > target else (width, round(width / target))
            w, h = w - w % 2, h - h % 2
            run_checked(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-vf", f"crop={w}:{h}", str(output)],
                        run=run, timeout=60)
            width, height = w, h
        elif picture[:8] != PNG_SIGNATURE:  # a provider may answer in JPEG or WebP; the file says .png
            run_checked(["ffmpeg", "-v", "error", "-y", "-i", str(raw), str(output)], run=run, timeout=60)
        else:
            raw.replace(output)
    finally:
        raw.unlink(missing_ok=True)
    book = credits.record(output, {"source": f"AI ({name} {model})", "aiGenerated": True, "prompt": prompt,
                                   "references": [r.name for r in refs] or None})
    return {"output": str(output), "engine": name, "model": model, "width": width, "height": height,
            "aspect": aspect, "quality": quality, "references": len(refs), "credits": book}


def _size(picture, run):
    out = run_checked(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                       "-of", "csv=p=0:s=x", str(picture)], run=run, timeout=30).stdout.strip()
    width, height = out.split("x")[:2]
    return int(width), int(height)
