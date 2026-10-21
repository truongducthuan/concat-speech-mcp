"""The `openai` speech engine: OpenAI's text-to-speech (POST /v1/audio/speech).

Its voices are a fixed set, each multilingual: the language is taken from the
text, so they are listed with language "multi" and match any language filter.
Needs an API key in OPENAI_API_KEY. The key travels in the Authorization
header and is scrubbed from any error passed back.
"""
import json
import os
import socket
import urllib.error
import urllib.request

from .process import EngineError

API = "https://api.openai.com/v1/audio/speech"
MODEL = "gpt-4o-mini-tts"
VOICES = ("alloy", "ash", "ballad", "cedar", "coral", "echo", "fable", "marin", "nova", "onyx", "sage",
          "shimmer", "verse")
DESCRIPTION = f"OpenAI text-to-speech ({MODEL}): natural multilingual voices, needs an API key"
KEY_VARIABLE = "OPENAI_API_KEY"
RAW_SUFFIX = ".wav"
DEFAULT_RATES = {}
CHECKS_VOICE_FIRST = True  # the list is local, so a wrong name is caught before a billed call
TIMEOUT = 60


def api_key(env=None):
    key = (os.environ if env is None else env).get(KEY_VARIABLE, "").strip()
    if not key:
        raise EngineError(f"{KEY_VARIABLE} is not set: create an API key at platform.openai.com "
                          f"and put it in the .env file")
    return key


def fetch_audio(payload, key=None, urlopen=urllib.request.urlopen):
    """POSTs `payload` to the speech endpoint; returns the audio bytes, or raises EngineError."""
    key = key or api_key()
    request = urllib.request.Request(API, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            audio = response.read()
    except urllib.error.HTTPError as failure:
        detail = _openai_message(failure) or failure.reason
        raise EngineError(f"OpenAI text-to-speech refused the request ({failure.code}): "
                          f"{str(detail).replace(key, '***')}") from None
    except (urllib.error.URLError, socket.timeout, OSError) as failure:
        reason = getattr(failure, "reason", None) or failure
        raise EngineError(f"could not reach OpenAI text-to-speech: {str(reason).replace(key, '***')}") from None
    if not audio:
        raise EngineError("OpenAI text-to-speech answered without audio")
    return audio


def _openai_message(failure):
    try:
        return json.loads(failure.read().decode("utf-8"))["error"]["message"]
    except (ValueError, KeyError, TypeError, OSError):
        return None


def list_voices(run=None, fetch=None):
    return [{"name": name, "locale": "multi", "language": "multi"} for name in VOICES]


def render(text, voice, raw, rate, run=None, fetch=fetch_audio):
    """Reads `text` in `voice` into the wav file `raw`."""
    raw.write_bytes(fetch({"model": MODEL, "input": text, "voice": voice, "response_format": "wav"}))
