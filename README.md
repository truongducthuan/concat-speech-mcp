# concat-speech-mcp

MCP server giving an agent (Claude Code) the speech features that Concat 0.2.8 keeps inside its window: **transcription** and **voice-over**. With `CONCAT_BIN` set it also runs Concat's own MCP server (`concat --mcp`) behind it and offers its 42 editing tools, so **one registration covers the whole edit** (45 tools).

| Tool | Does |
|---|---|
| `speech_transcribe` | whisper.cpp over a video/audio file → utterances `{start, end, text}` split at pauses (caption-ready) |
| `speech_voices` | voices available for `speech_synthesize`, filterable by language (`ja`, `vi`, `en`…) |
| `speech_synthesize` | text → `.wav` in a voice, optionally sped up to fit `maxDuration` |

Files are written only under the home folder (plus `CONCAT_SPEECH_ROOTS`), as Concat's MCP server does.

## Requirements

- macOS, Python 3.9+ (stdlib only), `ffmpeg`/`ffprobe`
- `whisper-cli` (`brew install whisper-cpp`)
- Concat's multilingual whisper model, `ggml-small.bin` in `~/Library/Application Support/app.concat.editor/whisper-models/` (download it in Concat, Settings > Speech)
- Voices: macOS system voices (`say`). Japanese (Kyoko…) and Vietnamese (Linh) ship with macOS.

## Register with Claude Code

One server for everything (Concat's tools + speech):

```sh
claude mcp add -s user concat -e CONCAT_BIN=/abs/path/to/concat -- python3 /abs/path/to/concat-speech-mcp/server.py
claude mcp list   # concat … ✔ Connected
```

Concat's MCP server is started at `initialize` and stopped when the client leaves; if it dies or stops answering (30 min per call), the call in flight returns `isError` and the next call starts a fresh one — unsaved project changes are then lost, so `project_save` often. Calls are handled one at a time: a long `export_wait` holds the server until it returns. Its tools, results (images included) and errors are passed on unchanged. Without `CONCAT_BIN` the server offers the 3 speech tools only, to sit beside a separately registered `concat --mcp`.

Environment: `CONCAT_BIN` (Concat binary), `CONCAT_MCP_MODE` (`auto`/`window`/`headless`, Concat's default when unset), `CONCAT_SPEECH_WHISPER_CLI`, `CONCAT_SPEECH_MODEL_DIR`, `CONCAT_SPEECH_ROOTS`.

## Test

```sh
python3 -m unittest discover -s tests -t .
```

`tests/test_integration_real_tools.py` runs the real engines and skips itself when they are missing. `tests/test_concat_bridge.py` drives the bridge against a scripted stand-in (`tests/fake_concat_mcp.py`) over real pipes.

## Limits

- Utterance times are the **source file's**; after cutting on a Concat timeline the agent shifts them itself.
- macOS voices are a stopgap: they read Japanese names in Vietnamese poorly ("Kyoto" → "Cô To"). A better engine is phase-3 work.
