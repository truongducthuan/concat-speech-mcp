# concat-speech-mcp

MCP server giving an agent (Claude Code) the speech features that Concat 0.2.8 keeps inside its window: **transcription** and **voice-over**. Use it beside Concat's own MCP server (`concat --mcp`), which does the editing.

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

```sh
claude mcp add -s user concat-speech -- python3 /abs/path/to/concat-speech-mcp/server.py
claude mcp list   # concat-speech … ✔ Connected
```

Environment overrides: `CONCAT_SPEECH_WHISPER_CLI`, `CONCAT_SPEECH_MODEL_DIR`, `CONCAT_SPEECH_ROOTS`.

## Test

```sh
python3 -m unittest discover -s tests -t .
```

`tests/test_integration_real_tools.py` runs the real engines and skips itself when they are missing.

## Limits

- Utterance times are the **source file's**; after cutting on a Concat timeline the agent shifts them itself.
- macOS voices are a stopgap: they read Japanese names in Vietnamese poorly ("Kyoto" → "Cô To"). A better engine is phase-3 work.
