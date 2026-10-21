"""The three tools this server offers: their schemas and what calling them does."""
import json

from .paths import existing_file, writable_file
from .synthesize import DEFAULT_MAX_SPEEDUP, list_voices, synthesize
from .transcribe import MODELS, transcribe

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
        "name": "speech_voices",
        "title": "List voices",
        "description": "Lists the voices speech_synthesize can read in, optionally only one language "
                       "(\"ja\", \"vi\", \"en\"...): name, locale and a sample sentence.",
        "inputSchema": {
            "type": "object",
            "properties": {"language": {"type": "string", "description": "Language code to filter by."}},
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
                "voice": {"type": "string", "description": "Voice name, e.g. \"Linh\" (vi) or \"Kyoko\" (ja)."},
                "output": {"type": "string", "description": "Absolute path of the .wav to write."},
                "maxDuration": {"type": "number", "minimum": 0, "description": "Seconds the line must fit in."},
                "maxSpeedup": {"type": "number", "minimum": 1, "maximum": 2, "default": DEFAULT_MAX_SPEEDUP},
            },
            "required": ["text", "voice", "output"],
        },
    },
]


def call_tool(name, arguments):
    """Runs one tool; returns its result as a JSON-able dict. Raises on bad input."""
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
        return {"voices": list_voices(arguments.get("language"))}
    if name == "speech_synthesize":
        output = writable_file(arguments["output"], (".wav",))
        return synthesize(arguments["text"], arguments["voice"], output,
                          max_duration=arguments.get("maxDuration"),
                          max_speedup=arguments.get("maxSpeedup") or DEFAULT_MAX_SPEEDUP)
    raise KeyError(name)
