# concat-speech-mcp

MCP server giving an agent (Claude Code) what Concat 0.2.8 does not offer over MCP: **transcription**, **voice-over**, **pictures for the edit** (free stock photos and videos, HTML motion-graphics scenes rendered to clips, AI-generated pictures) and **sound** (free music and effects, music fitted and ducked under the voice, beats, final loudness). With `CONCAT_BIN` set it also runs Concat's own MCP server (`concat --mcp`) behind it and offers its 42 editing tools, so **one registration covers the whole edit** (57 tools).

| Tool | Does |
|---|---|
| `speech_transcribe` | whisper.cpp over a video/audio file → utterances `{start, end, text}` split at pauses (caption-ready) |
| `speech_engines` | speech engines (`macos`, `edge`, `vieneu`, `google`, `openai`), which are configured and which is the default, so the agent can ask which to use |
| `speech_voices` | voices available for `speech_synthesize`, filterable by language (`ja`, `vi`, `en`…) |
| `speech_synthesize` | text → `.wav` in a voice, optionally sped up to fit `maxDuration`; with `edge`, also each word's start/end for word-by-word captions |
| `speech_voice_clone` | saves a custom voice for `vieneu` from 3–8 s of one speaker in any recording **or video** (`start`, `duration`); then read in it with voice `clone:<name>`. Needs `consent: true`, which the agent passes only after you confirm the voice is yours or you have the speaker's permission |
| `speech_voice_remove` | deletes a saved voice |
| `media_search` | free stock photos (Wikimedia Commons, no key; Pixabay, Pexels with free keys), videos (Pixabay, Pexels; Commons with no key, converted to mp4), music (Commons, no key; Jamendo, Freesound) and sound effects (Freesound), with author, licence, size or length; non-commercial licences left out unless asked |
| `media_fetch` | downloads a search result (photos ≤ 1920 px, videos ≤ 1080p, audio converted to .wav/.mp3/.m4a) and records its credit in `credits.json` beside it |
| `scene_render` | an HTML page (titles, numbers, charts, maps, moving pictures) → silent 1080p mp4 clip, played frame by frame in Chrome; or PNG stills to check it first |
| `image_engines` | image engines (`openai`, `gemini`), which have a key, which is the default |
| `music_fit` | a song → music bed for the whole timeline: start point, looped or cut to length, levelled (−30 LUFS under a voice), faded, **ducked under the voice lines** |
| `music_beats` | tempo, beat and downbeat times of a song (librosa), to cut on the music |
| `audio_master` | an exported video's sound brought to −14 LUFS / −1.5 dB true peak (YouTube, TikTok, Reels), picture copied |
| `sfx_make` | short effects synthesised locally (whoosh, riser, pop, click, tick, ding, impact): free, nothing to credit |
| `image_generate` | one AI picture from a prompt → `.png` cropped to the video's aspect, with reference pictures to keep a character the same; **billed per picture** |

Files are written only under the home folder (plus `CONCAT_SPEECH_ROOTS`), as Concat's MCP server does.

## Requirements

- macOS, Python 3.9+ (stdlib only), `ffmpeg`/`ffprobe`
- `whisper-cli` (`brew install whisper-cpp`)
- Concat's multilingual whisper model, `ggml-small.bin` in `~/Library/Application Support/app.concat.editor/whisper-models/` (download it in Concat, Settings > Speech)
- Voices come from a speech engine, chosen per call with `engine` or by default with `CONCAT_SPEECH_ENGINE` (default `macos`). `speech_engines` lists the engines and which are configured, so the agent can ask which one to use. Voice names differ per engine: list them with `speech_voices`.
  - `macos`: system voices (`say`), offline and free. Japanese (Kyoko…) and Vietnamese (Linh) ship with macOS. Takes `rate` (words per minute, 90–360); without it Vietnamese voices read at 200 (Linh's own ~175 is sluggish) and other voices at their own rate.
  - `edge`: Microsoft Edge's neural voices through [edge-tts](https://github.com/rany2/edge-tts): free, no key, natural, ~300 voices (Vietnamese: `vi-VN-HoaiMyNeural`, `vi-VN-NamMinhNeural`). Online: the line's text goes to Microsoft's service, an unofficial endpoint that can change without notice and, at times, answers about a third of requests without audio (the worker tries a line 5 times over ~15 s; when that still fails, use `vieneu` for Vietnamese). Returns `words` (each word's start/end, already timed to the output file after any speed-up), for karaoke-style captions.
  - `vieneu`: [VieNeu-TTS](https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo) v3 Turbo (Apache-2.0): 25 natural Vietnamese voices (north, central, south; news, storytelling, audiobook…), free and **offline**; it reads numbers, dates and English words itself. The models (~550 MB) download once, on first use, to `~/.cache/concat-speech/vieneu` (`CONCAT_SPEECH_VIENEU_DIR`). The model loads once into a worker that stays up while the server runs (~7 s, then ~2 s per line on an 8-core Mac). Clone a voice by passing, as `voice`, the absolute path of a 3–8 s clean recording (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`): only a voice you own or have permission to use. Worker log: `~/.cache/concat-speech/vieneu-worker.log`. Saved voices (`speech_voice_clone`) live in `~/.local/share/concat-speech/voices` (`CONCAT_SPEECH_VOICES_DIR`) as a levelled 48 kHz mono clip plus a note of its source; pick a stretch without music or other voices (VieNeu denoises, but a clean clip clones best).
  - `edge` and `vieneu` need Python packages, kept out of the server (stdlib only) in a venv of their own at `.venv-tts` (or the interpreter in `CONCAT_SPEECH_PYTHON`):
    ```sh
    python3 -m venv .venv-tts && .venv-tts/bin/pip install edge-tts vieneu playwright   # or just the ones you need
    ```
    `speech_engines` reports an engine whose packages are missing as not configured, with the command to fix it.
  - `google`: Google Cloud Text-to-Speech, natural native voices (e.g. `vi-VN-Chirp3-HD-Aoede`). Needs a Google Cloud project with billing on and the Text-to-Speech API enabled, and an API key restricted to that API, in `.env` as `GOOGLE_TTS_API_KEY`. Chirp 3 HD: 1M characters free per month. The key goes in a header and is scrubbed from errors. With this engine the line's text is sent to Google Cloud; keep confidential scripts on `macos`. Like every variable of the server's environment, the key is also visible to the engines it starts (ffmpeg, whisper-cli, Concat).
  - `openai`: OpenAI text-to-speech (`gpt-4o-mini-tts`), 13 multilingual voices (`alloy`, `nova`, `coral`, `marin`…) that read whatever language the text is in (`speech_voices` lists them as language `multi`). Needs `OPENAI_API_KEY` in `.env`. Billed per use (about $0.015 per minute of audio). The line's text is sent to OpenAI. The variable is the one other OpenAI tools use: an `OPENAI_API_KEY` already exported in the shell that starts Claude Code wins over `.env`, so check `echo ${OPENAI_API_KEY:+set}` is empty there, or calls are billed to that key's account. Like the Google key, it is also visible to the engines the server starts.
  - Another engine is one `tts_engine_<name>.py` module (`list_voices`, `render`, `DESCRIPTION`, `KEY_VARIABLE`, `RAW_SUFFIX`, `DEFAULT_RATES`, `CHECKS_VOICE_FIRST`) added to `ENGINES` in `synthesize.py`; the setup menu and `speech_engines` pick it up.

## Pictures for the edit

- **Stock** (`media_search`, `media_fetch`): Wikimedia Commons works with no key (photos; CC licences: the author and licence must be credited, `creditRequired`). Pixabay and Pexels add photos **and videos** with free keys (`PIXABAY_API_KEY` from pixabay.com/api/docs, `PEXELS_API_KEY` from pexels.com/api) in `.env`; neither requires credit. English queries find far more. Every fetched file gets an entry in `credits.json` in its folder.
- **Scenes** (`scene_render`): the agent writes a scene as a web page and the tool plays it in the Google Chrome on this machine through [Playwright](https://playwright.dev/python/) (no browser download), seeking every animation to each frame's time, so the result is the same however slow the machine. Motion must come from CSS animations/transitions, the Web Animations API, `<video>` or `scene.on(t => …)` (GSAP: `scene.on(t => tl.seek(t))`). Sizes 16:9, 9:16, 1:1, 4:5 at 24–60 fps; clips are silent (voice and music go on Concat's timeline). About 2 s of work per second of 1080p30. Install: `.venv-tts/bin/pip install playwright` (Chrome must be installed).
- **AI pictures** (`image_generate`): `openai` (`OPENAI_IMAGE_MODEL`, default `gpt-image-2`, key `OPENAI_API_KEY`) or `gemini` (`GEMINI_IMAGE_MODEL`, default `gemini-2.5-flash-image`, key `GEMINI_API_KEY` from aistudio.google.com); `CONCAT_IMAGE_ENGINE` picks the default, else the first with a key. Each call is billed by the provider. The prompt (and any reference pictures) go to that provider. Pictures are recorded in `credits.json` as AI-generated, with the prompt.
- AI **video** generation is not included (cost); a still picture with a keyframed zoom in Concat, or a `scene_render` clip, stands in for now.

## Sound for the edit

- **Music** (`media_search` kind `music`, then `media_fetch` to `.wav`): Wikimedia Commons needs no key and holds much of Kevin MacLeod's catalogue ("Kevin MacLeod calm piano", "…upbeat", CC BY: credit him). Jamendo (`JAMENDO_CLIENT_ID`, devportal.jamendo.com) and Freesound (`FREESOUND_API_KEY`, freesound.org/apiv2/apply) add more with free keys. Freesound files are its high-quality mp3 previews (full downloads need OAuth).
- **Effects**: `sfx_make` synthesises the common ones offline; `media_search` kind `sfx` finds recorded ones on Freesound. (Concat's own sound shelf is not online yet: its manifest is still missing.)
- **Mixing**: Concat mixes clips but cannot duck. `music_fit` renders one bed for the whole timeline with the music lowered under the voice clips (`voices`: their files and timeline starts); it goes on its own lane at 0 s. Re-run it after moving voice clips. `music_beats` gives cut points. After `export_wait`, `audio_master` sets the final loudness.
- Non-commercial licences (CC BY-NC…) are filtered out of every search unless `allowNonCommercial`: most videos end up on monetised channels.

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

Concat's MCP server is started at `initialize` and stopped when the client leaves; if it dies or stops answering (30 min per call), the call in flight returns `isError` and the next call starts a fresh one — unsaved project changes are then lost, so `project_save` often. Calls are handled one at a time: a long `export_wait` holds the server until it returns. Its tools, results (images included) and errors are passed on unchanged. Without `CONCAT_BIN` the server offers its own 15 tools only, to sit beside a separately registered `concat --mcp`.

Environment: `CONCAT_BIN` (Concat binary), `CONCAT_MCP_MODE` (`auto`/`window`/`headless`, Concat's default when unset), `CONCAT_SPEECH_WHISPER_CLI`, `CONCAT_SPEECH_MODEL_DIR`, `CONCAT_SPEECH_ROOTS`, `CONCAT_SPEECH_ENGINE`, `GOOGLE_TTS_API_KEY`, `OPENAI_API_KEY`, `CONCAT_SPEECH_PYTHON`, `CONCAT_SPEECH_VIENEU_DIR`, `CONCAT_SPEECH_VOICES_DIR`, `PIXABAY_API_KEY`, `PEXELS_API_KEY`, `FREESOUND_API_KEY`, `JAMENDO_CLIENT_ID`, `CONCAT_IMAGE_ENGINE`, `GEMINI_API_KEY`, `OPENAI_IMAGE_MODEL`, `GEMINI_IMAGE_MODEL`, `CONCAT_SPEECH_ENV_FILE`. On a server, set these as real environment variables from its secret store (they win over `.env`); never bake keys into an image or commit them.

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
