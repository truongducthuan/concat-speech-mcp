"""The three tools this server offers: their schemas and what calling them does."""
import json

from . import speech_env_file
from .paths import existing_file, writable_file
from .synthesize import (DEFAULT_MAX_SPEEDUP, ENGINES, MAX_RATE, MIN_RATE, list_engines, list_voices,
                         settings_variables, synthesize)
from .transcribe import MODELS, transcribe

ENGINE_PROPERTY = {"type": "string", "enum": list(ENGINES),
                   "description": "Speech engine: \"macos\" (system voices, offline, dated) or \"google\" "
                                  "(Google Cloud Text-to-Speech, natural; needs GOOGLE_TTS_API_KEY) or \"openai\" "
                                  "(OpenAI, natural multilingual voices; needs OPENAI_API_KEY). "
                                  "Default: CONCAT_SPEECH_ENGINE, else macos. Voice names differ per engine."}

TOOLS = [
    {
        "name": "speech_transcribe",
        "title": "Transcribe speech",
        "description": (
            "Transcribes the speech in a video or audio file (absolute path) with whisper, the engine Concat uses, "
            "and returns it as utterances - {start, end, text}, times in seconds of the source file - split where "
            "the speaker pauses, ready to become captions. `language` is a code such as \"ja\" or \"vi\", or \"auto\" "
            "to detect it. Times are the SOURCE's: after cutting clips on a Concat timeline, shift them yourself. "
            "`output` (optional, .json) also saves the result to a file. Takes about 5 s per minute of audio."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Absolute path of the video or audio file."},
                "language": {"type": "string", "default": "auto", "description": "\"auto\" or a code: ja, vi, en..."},
                "model": {"type": "string", "enum": list(MODELS), "default": "small",
                          "description": "Whisper model; small is the most accurate offered."},
                "output": {"type": "string", "description": "Optional absolute .json path to save the result to."},
            },
            "required": ["file"],
        },
    },
    {
        "name": "speech_engines",
        "title": "List speech engines",
        "description": (
            "Lists the speech engines speech_synthesize can use: name, description, whether it is configured "
            "(its API key is set), which one is the default, and the key it needs. Before a voice-over, call this; "
            "when more than one engine is configured, ask the user which to use (offer the configured ones, "
            "default first) and pass it as `engine`. An engine that is not configured is set up by the user "
            "putting it in the server's .env file (or running setup_speech.py), never by putting a key in a tool call."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "speech_voices",
        "title": "List voices",
        "description": "Lists the voices speech_synthesize can read in with an engine, optionally only one "
                       "language (\"ja\", \"vi\", \"en\"...): name, locale and language. Language "
                       "\"multi\" (openai) reads whatever language the text is in.",
        "inputSchema": {
            "type": "object",
            "properties": {"language": {"type": "string", "description": "Language code to filter by."},
                           "engine": ENGINE_PROPERTY},
        },
    },
    {
        "name": "speech_synthesize",
        "title": "Read text aloud",
        "description": (
            "Reads `text` in `voice` (a name from speech_voices) into a .wav file at `output` (absolute path, under "
            "the home folder), for a voice-over: import it with Concat's media_import and place it with clip_add. "
            "With `maxDuration` (seconds) a line that runs long is sped up to fit, at most `maxSpeedup` times; "
            "`overflow` in the result says how many seconds still do not fit."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to say."},
                "voice": {"type": "string", "description": "Voice name from speech_voices for the same engine, "
                                                           "e.g. \"Linh\" (macos), \"vi-VN-Chirp3-HD-Aoede\" (google) "
                                                           "or \"nova\" (openai)."},
                "engine": ENGINE_PROPERTY,
                "output": {"type": "string", "description": "Absolute path of the .wav to write."},
                "maxDuration": {"type": "number", "minimum": 0, "description": "Seconds the line must fit in."},
                "maxSpeedup": {"type": "number", "minimum": 1, "maximum": 2, "default": DEFAULT_MAX_SPEEDUP},
                "rate": {"type": "number", "minimum": MIN_RATE, "maximum": MAX_RATE,
                         "description": "macos engine only: speaking rate in words per minute; raise it for a "
                                        "brisker read. Default: 200 for Vietnamese voices, the voice's own rate "
                                        "otherwise."},
            },
            "required": ["text", "voice", "output"],
        },
    },
]


def call_tool(name, arguments):
    """Runs one tool; returns its result as a JSON-able dict. Raises on bad input."""
    speech_env_file.apply(settings_variables())  # the user may have changed engine or keys since the last call
    if name == "speech_engines":
        return {"engines": list_engines()}
    if name == "speech_transcribe":
        source = existing_file(arguments["file"])
        output = writable_file(arguments["output"], (".json",)) if arguments.get("output") else None
        result = transcribe(source, language=arguments.get("language") or "auto",
                            model=arguments.get("model") or "small")
        result["file"] = str(source)
        if output:
            output.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            result["savedTo"] = str(output)
        return result
    if name == "speech_voices":
        return {"voices": list_voices(arguments.get("language"), engine=arguments.get("engine"))}
    if name == "speech_synthesize":
        output = writable_file(arguments["output"], (".wav",))
        return synthesize(arguments["text"], arguments["voice"], output,
                          max_duration=arguments.get("maxDuration"),
                          max_speedup=arguments.get("maxSpeedup") or DEFAULT_MAX_SPEEDUP,
                          rate=arguments.get("rate"), engine=arguments.get("engine"))
    raise KeyError(name)
