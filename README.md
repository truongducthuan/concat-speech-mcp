# concat-speech-mcp

MCP server giving an agent (Claude Code) the speech features that Concat 0.2.8 keeps inside its window: **transcription** and **voice-over**. With `CONCAT_BIN` set it also runs Concat's own MCP server (`concat --mcp`) behind it and offers its 42 editing tools, so **one registration covers the whole edit** (46 tools).

| Tool | Does |
|---|---|
| `speech_transcribe` | whisper.cpp over a video/audio file → utterances `{start, end, text}` split at pauses (caption-ready) |
| `speech_engines` | speech engines (`macos`, `google`, `openai`), which are configured and which is the default, so the agent can ask which to use |
| `speech_voices` | voices available for `speech_synthesize`, filterable by language (`ja`, `vi`, `en`…) |
| `speech_synthesize` | text → `.wav` in a voice, optionally sped up to fit `maxDuration` |

Files are written only under the home folder (plus `CONCAT_SPEECH_ROOTS`), as Concat's MCP server does.

## Requirements

- macOS, Python 3.9+ (stdlib only), `ffmpeg`/`ffprobe`
- `whisper-cli` (`brew install whisper-cpp`)
- Concat's multilingual whisper model, `ggml-small.bin` in `~/Library/Application Support/app.concat.editor/whisper-models/` (download it in Concat, Settings > Speech)
- Voices come from a speech engine, chosen per call with `engine` or by default with `CONCAT_SPEECH_ENGINE` (default `macos`). `speech_engines` lists the engines and which are configured, so the agent can ask which one to use. Voice names differ per engine: list them with `speech_voices`.
  - `macos`: system voices (`say`), offline and free. Japanese (Kyoko…) and Vietnamese (Linh) ship with macOS. Takes `rate` (words per minute, 90–360); without it Vietnamese voices read at 200 (Linh's own ~175 is sluggish) and other voices at their own rate.
  - `google`: Google Cloud Text-to-Speech, natural native voices (e.g. `vi-VN-Chirp3-HD-Aoede`). Needs a Google Cloud project with billing on and the Text-to-Speech API enabled, and an API key restricted to that API, in `.env` as `GOOGLE_TTS_API_KEY`. Chirp 3 HD: 1M characters free per month. The key goes in a header and is scrubbed from errors. With this engine the line's text is sent to Google Cloud; keep confidential scripts on `macos`. Like every variable of the server's environment, the key is also visible to the engines it starts (ffmpeg, whisper-cli, Concat).
  - `openai`: OpenAI text-to-speech (`gpt-4o-mini-tts`), 13 multilingual voices (`alloy`, `nova`, `coral`, `marin`…) that read whatever language the text is in (`speech_voices` lists them as language `multi`). Needs `OPENAI_API_KEY` in `.env`. Billed per use (about $0.015 per minute of audio). The line's text is sent to OpenAI. The variable is the one other OpenAI tools use: an `OPENAI_API_KEY` already exported in the shell that starts Claude Code wins over `.env`, so check `echo ${OPENAI_API_KEY:+set}` is empty there, or calls are billed to that key's account. Like the Google key, it is also visible to the engines the server starts.
  - Another engine is one `tts_engine_<name>.py` module (`list_voices`, `render`, `DESCRIPTION`, `KEY_VARIABLE`, `RAW_SUFFIX`, `DEFAULT_RATES`, `CHECKS_VOICE_FIRST`) added to `ENGINES` in `synthesize.py`; the setup menu and `speech_engines` pick it up.

## Choose an engine, add API keys

Like a web app, settings live in `.env` at the repository root, which git ignores; `.env.example` lists every variable:

```sh
cp .env.example .env && chmod 600 .env   # then fill in the keys you have
```

Or let a menu write it: `python3 setup_speech.py` picks the default engine and, for an engine that needs a key, asks for it hidden (Enter keeps the saved one). `CONCAT_SPEECH_ENV_FILE` points the server at another file. A `.env` that others can change is ignored; one others can read draws a warning. The server reads that file before every call: switching engine or adding a key needs no restart. Variables given at registration (`claude mcp add -e`) win over the file. Run the setup again to switch, or to add another engine's key.

## Register with Claude Code

One server for everything (Concat's tools + speech):

```sh
claude mcp add -s user concat -e CONCAT_BIN=/abs/path/to/concat -- python3 /abs/path/to/concat-speech-mcp/server.py
claude mcp list   # concat … ✔ Connected
```

Concat's MCP server is started at `initialize` and stopped when the client leaves; if it dies or stops answering (30 min per call), the call in flight returns `isError` and the next call starts a fresh one — unsaved project changes are then lost, so `project_save` often. Calls are handled one at a time: a long `export_wait` holds the server until it returns. Its tools, results (images included) and errors are passed on unchanged. Without `CONCAT_BIN` the server offers the 4 speech tools only, to sit beside a separately registered `concat --mcp`.

Environment: `CONCAT_BIN` (Concat binary), `CONCAT_MCP_MODE` (`auto`/`window`/`headless`, Concat's default when unset), `CONCAT_SPEECH_WHISPER_CLI`, `CONCAT_SPEECH_MODEL_DIR`, `CONCAT_SPEECH_ROOTS`, `CONCAT_SPEECH_ENGINE`, `GOOGLE_TTS_API_KEY`, `OPENAI_API_KEY`, `CONCAT_SPEECH_ENV_FILE`. On a server, set these as real environment variables from its secret store (they win over `.env`); never bake keys into an image or commit them.

## Serve other machines (HTTP)

`--http` serves MCP over Streamable HTTP at `/mcp`, so a Claude Code on another machine can edit with the Concat and the speech engines of this one:

```sh
export CONCAT_MCP_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
CONCAT_BIN=/abs/path/to/concat python3 server.py --http --host 0.0.0.0 --port 8765
# on the other machine:
claude mcp add -s user --transport http concat http://<this-machine-ip>:8765/mcp --header "Authorization: Bearer <token>"
```

- Every request needs the bearer token (16+ characters; the server refuses to start without one). A request with an `Origin` header is refused unless listed in `CONCAT_MCP_ALLOWED_ORIGINS` (comma-separated), so a web page cannot drive it.
- It listens on `127.0.0.1` unless `--host` says otherwise. The HTTP is not encrypted: on a shared network the token travels in clear, so use it on a network you trust, or put it behind TLS or a VPN (Tailscale); never forward the port to the internet as is.
- Each client gets its own session (`Mcp-Session-Id`, minted at `initialize`, ended by `DELETE` or after 4 h idle) with its own Concat; at most 8 at once; a 9th client ends the least recently used idle session (a call in flight is never cut), and is refused only while all 8 are busy. Calls within a session are answered one at a time. A connection that sends nothing is dropped after 30 s.
- Paths are this machine's: clients edit media already here and find exports here. Speech engine calls are billed to this machine's keys.

## Test

```sh
python3 -m unittest discover -s tests -t .
```

`tests/test_integration_real_tools.py` runs the real engines and skips itself when they are missing. `tests/test_concat_bridge.py` drives the bridge against a scripted stand-in (`tests/fake_concat_mcp.py`) over real pipes.

## Limits

- Utterance times are the **source file's**; after cutting on a Concat timeline the agent shifts them itself.
- macOS voices are a stopgap: they read Japanese names in Vietnamese poorly ("Kyoto" → "Cô To"); use the `google` engine for natural voices.
