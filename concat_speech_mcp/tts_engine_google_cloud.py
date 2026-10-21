"""The `google` speech engine: Google Cloud Text-to-Speech over its REST API.

Native Vietnamese and Japanese voices (the Chirp 3 HD ones, such as
vi-VN-Chirp3-HD-Aoede, sound the most natural). Needs an API key in
GOOGLE_TTS_API_KEY, restricted to the Text-to-Speech API. The key travels in
a header, never in the URL, and is scrubbed from any error passed back, so it
cannot end up in a tool result or a log.
"""
import base64
import json
import os
import socket
import urllib.error
import urllib.request

from .process import EngineError

API = "https://texttospeech.googleapis.com/v1"
DESCRIPTION = "Google Cloud Text-to-Speech (Chirp 3 HD): natural native voices, needs an API key"
KEY_VARIABLE = "GOOGLE_TTS_API_KEY"
RAW_SUFFIX = ".wav"
DEFAULT_RATES = {}
# The catalogue is large and Google's own refusal names a bad voice, so
# synthesize does not list voices before each line.
CHECKS_VOICE_FIRST = False
TIMEOUT = 60


def api_key(env=None):
    key = (os.environ if env is None else env).get(KEY_VARIABLE, "").strip()
    if not key:
        raise EngineError(f"{KEY_VARIABLE} is not set: create an API key for Cloud Text-to-Speech "
                          f"and put it in the .env file")
    return key


def fetch_json(url, payload=None, key=None, urlopen=urllib.request.urlopen):
    """GET (or POST `payload`) a Google API; returns the JSON reply, or raises EngineError."""
    key = key or api_key()
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"X-Goog-Api-Key": key, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as failure:
        detail = _google_message(failure) or failure.reason
        raise EngineError(f"Google Text-to-Speech refused the request ({failure.code}): "
                          f"{str(detail).replace(key, '***')}") from None
    except (urllib.error.URLError, socket.timeout, OSError) as failure:
        reason = getattr(failure, "reason", None) or failure
        raise EngineError(f"could not reach Google Text-to-Speech: {str(reason).replace(key, '***')}") from None
    except ValueError:
        raise EngineError("Google Text-to-Speech answered with something that is not JSON") from None
    if not isinstance(reply, dict):
        raise EngineError("Google Text-to-Speech answered in an unexpected shape")
    return reply


def _google_message(failure):
    try:
        return json.loads(failure.read().decode("utf-8"))["error"]["message"]
    except (ValueError, KeyError, TypeError, OSError):
        return None


def list_voices(run=None, fetch=fetch_json):
    voices = []
    for voice in fetch(f"{API}/voices").get("voices") or []:
        if not isinstance(voice, dict) or not voice.get("name"):
            continue
        locale = (voice.get("languageCodes") or ["und"])[0]
        voices.append({"name": voice["name"], "locale": locale, "language": locale.split("-")[0].lower(),
                       "gender": voice.get("ssmlGender", "")})
    return voices


def render(text, voice, raw, rate, run=None, fetch=fetch_json):
    """Reads `text` in `voice` into the wav file `raw` (LINEAR16 comes with its wav header)."""
    language_code = "-".join(voice.split("-")[:2])
    reply = fetch(f"{API}/text:synthesize", {"input": {"text": text},
                                             "voice": {"languageCode": language_code, "name": voice},
                                             "audioConfig": {"audioEncoding": "LINEAR16"}})
    try:
        raw.write_bytes(base64.b64decode(reply["audioContent"]))
    except (KeyError, ValueError):
        raise EngineError("Google Text-to-Speech answered without audio") from None
