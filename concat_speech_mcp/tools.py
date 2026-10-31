"""The tools this server offers: their schemas and what calling them does."""
import json
from pathlib import Path

from . import audio_tools, image_generate, media_sources, scene_render, speech_env_file, voice_library
from .paths import existing_file, writable_file
from .synthesize import (DEFAULT_MAX_SPEEDUP, ENGINES, MAX_RATE, MIN_RATE, list_engines, list_voices,
                         settings_variables, synthesize)
from .transcribe import MODELS, transcribe

ENGINE_PROPERTY = {"type": "string", "enum": list(ENGINES),
                   "description": "Speech engine: \"macos\" (system voices, offline, dated), \"edge\" "
                                  "(Microsoft Edge neural voices, free, online, returns word timings), \"vieneu\" "
                                  "(VieNeu-TTS, natural Vietnamese, free, offline, can clone a voice), \"google\" "
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
            "(its API key is set, or its packages installed - else `install` says how), which one is the default, "
            "and the key it needs. Before a voice-over, call this; "
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
                       "language (\"ja\", \"vi\", \"en\"...): name, locale and language (vieneu adds a "
                       "description: gender, region, style). Language \"multi\" (openai) reads whatever language "
                       "the text is in.",
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
            "`overflow` in the result says how many seconds still do not fit. Engines that report word timings "
            "(edge) add `words` [{start, end, text}] in seconds of the output file, for word-by-word captions. "
            "With the vieneu engine, `voice` may instead be the absolute path of a 3-8 s recording of clean speech, "
            "to read in that voice: only a voice the user owns or has permission to use."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to say."},
                "voice": {"type": "string", "description": "Voice name from speech_voices for the same engine, "
                                                           "e.g. \"Linh\" (macos), \"vi-VN-HoaiMyNeural\" (edge), "
                                                           "\"Mai Anh\" (vieneu), \"vi-VN-Chirp3-HD-Aoede\" (google) "
                                                           "or \"nova\" (openai); vieneu also takes the absolute "
                                                           "path of a recording to clone."},
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
    {
        "name": "speech_voice_clone",
        "title": "Save a voice to clone",
        "description": (
            "Saves a custom voice for the vieneu engine from a recording or a video (absolute path): `duration` "
            "seconds (3-8, VieNeu listens to 8 at most) from `start`, which should be ONE speaker talking clearly, "
            "without music or noise (find a clean stretch with speech_transcribe first). Afterwards read lines in it "
            "with speech_synthesize, engine \"vieneu\", voice \"clone:<name>\"; speech_voices lists it. Before "
            "calling, ask the user to confirm the voice is theirs or that they have the speaker's permission, and "
            "pass `consent` true only after they confirm: never clone a voice to impersonate someone."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name to save it under, e.g. \"Giọng của tôi\"."},
                "file": {"type": "string", "description": "Absolute path of the recording or video."},
                "start": {"type": "number", "minimum": 0, "default": 0, "description": "Seconds into the file."},
                "duration": {"type": "number", "minimum": voice_library.MIN_SECONDS,
                             "maximum": voice_library.MAX_SECONDS, "default": voice_library.MAX_SECONDS},
                "replace": {"type": "boolean", "default": False, "description": "Overwrite a voice of that name."},
                "consent": {"type": "boolean", "description": "True only once the user confirmed they own the "
                                                              "voice or have the speaker's permission."},
            },
            "required": ["name", "file", "consent"],
        },
    },
    {
        "name": "speech_voice_remove",
        "title": "Remove a saved voice",
        "description": "Deletes a voice saved with speech_voice_clone (\"clone:<name>\" or just the name).",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
    {
        "name": "media_search",
        "title": "Find free stock photos, videos, music and sound effects",
        "description": (
            "Searches free stock media. kind image: Wikimedia Commons (no key; credit the author and licence), "
            "Pixabay, Pexels. kind video: Pixabay, Pexels, Commons (no key; fewer, documentary-style; converted to mp4 on fetch). kind music: Commons (no key; e.g. \"Kevin MacLeod "
            "calm piano\", \"Kevin MacLeod upbeat\"), Jamendo, Freesound. kind sfx: Freesound (\"whoosh\", "
            "\"camera shutter\"), Commons (poor for effects: prefer sfx_make). Keys are free, in the .env: "
            "PIXABAY_API_KEY, PEXELS_API_KEY, FREESOUND_API_KEY, JAMENDO_CLIENT_ID; `skipped` says which source "
            "was left out and why. English queries find far more. Non-commercial licences are left out unless "
            "`allowNonCommercial`. Returns results with an `id`, author, licence, size, shape, duration; with "
            "`previewDir` (absolute folder) picture previews are saved there to look at before choosing. You cannot "
            "hear music: offer the user 2-3 tracks by title, length and mood and let them choose. Then media_fetch."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, e.g. \"Hanoi old quarter street\"."},
                "kind": {"type": "string", "enum": list(media_sources.KINDS), "default": "image"},
                "source": {"type": "string", "enum": ["all", *media_sources.ALL_SOURCES], "default": "all"},
                "orientation": {"type": "string", "enum": list(media_sources.ORIENTATIONS), "default": "any",
                                "description": "landscape for 16:9 videos, portrait for 9:16 (TikTok, Reels)."},
                "count": {"type": "integer", "minimum": 1, "maximum": 30, "default": 8,
                          "description": "Results per source."},
                "previewDir": {"type": "string", "description": "Optional absolute folder for preview pictures."},
                "minDuration": {"type": "number", "minimum": 0, "description": "video/music/sfx: shortest, seconds."},
                "maxDuration": {"type": "number", "minimum": 0, "description": "video/music/sfx: longest, seconds (keep stock video short: a 45-minute film is a huge download)."},
                "allowNonCommercial": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "media_fetch",
        "title": "Download a stock photo or video",
        "description": (
            "Downloads a media_search result by `id` to `output` (absolute path; a picture or video keeps its real "
            "type's extension, see `output` in the result; music and effects are converted to the asked .wav, .mp3 "
            "or .m4a), ready for Concat's media_import. Its author and "
            "licence go into credits.json in the same folder; when `creditRequired` is true, show `credit` in "
            "the video or its description."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "output": {"type": "string"}},
            "required": ["id", "output"],
        },
    },
    {
        "name": "scene_render",
        "title": "Render an HTML scene to video",
        "description": (
            "Turns a scene written as an HTML page (absolute path) into a silent mp4 clip for Concat: titles, "
            "numbers, charts, lists, maps, pictures with motion. The page is played frame by frame in Chrome, so "
            "motion must come from CSS animations/transitions, the Web Animations API, <video> elements or "
            "`scene.on(t => ...)` (t in seconds; GSAP: `scene.on(t => tl.seek(t))`), never requestAnimationFrame "
            "loops or timers. Make the page exactly the frame size (`size`), with an opaque background; pictures by "
            "relative path beside the page. Check it first with `stills` (seconds, up to 12): PNGs are saved to "
            "`stillsDir` (default: stills/ beside the page) to look at; then give `output` (.mp4). `warnings` lists "
            "page errors and files that did not load. About 2 s of rendering per second of 1080p30 clip."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "html": {"type": "string", "description": "Absolute path of the scene's .html file."},
                "output": {"type": "string", "description": "Absolute path of the .mp4 to write."},
                "duration": {"type": "number", "exclusiveMinimum": 0, "maximum": scene_render.MAX_SECONDS,
                             "default": 5},
                "size": {"type": "string", "enum": list(scene_render.SIZES), "default": "16:9",
                         "description": "16:9 = 1920x1080, 9:16 = 1080x1920, 1:1 = 1080x1080, 4:5 = 1080x1350."},
                "fps": {"type": "integer", "enum": list(scene_render.FPS), "default": 30},
                "stills": {"type": "array", "items": {"type": "number"},
                           "description": "Seconds to save as PNG stills, to check the scene before rendering."},
                "stillsDir": {"type": "string", "description": "Absolute folder for the stills."},
            },
            "required": ["html"],
        },
    },
    {
        "name": "image_engines",
        "title": "List image engines",
        "description": "Lists the engines image_generate can use: name, description, model, whether its API key is "
                       "set, and which is the default. Image generation is billed by the provider per picture.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "image_generate",
        "title": "Generate a picture",
        "description": (
            "Makes one picture from a description with an AI engine (see image_engines), saved as .png at `output` "
            "(absolute path), cropped to `aspect` to fill the video frame; then use it in Concat (media_import, "
            "keyframe a slow zoom) or in a scene_render page. Each call is BILLED by the provider (a few cents): "
            "agree with the user how many pictures to make before a batch, and reuse pictures. Describe subject, "
            "setting, style, light and framing; keep the same style words across a video. `references` (up to 4 "
            "absolute paths to .png/.jpg/.webp) keep a character or product looking the same: pass the first "
            "picture of that character to every later one. Recorded in credits.json as AI-generated."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "output": {"type": "string", "description": "Absolute path of the .png to write."},
                "aspect": {"type": "string", "enum": list(image_generate.ASPECTS), "default": "16:9"},
                "quality": {"type": "string", "enum": list(image_generate.QUALITIES), "default": "medium",
                            "description": "openai only: low is cheapest, for drafts."},
                "references": {"type": "array", "items": {"type": "string"}, "maxItems": image_generate.MAX_REFERENCES},
                "engine": {"type": "string", "enum": list(image_generate.ENGINES)},
                "crop": {"type": "boolean", "default": True},
            },
            "required": ["prompt", "output"],
        },
    },
    {
        "name": "music_fit",
        "title": "Fit music under the video",
        "description": (
            "Makes a music bed (.wav) for the whole timeline from a song (absolute path, e.g. from media_fetch): "
            "from `start` seconds in the song, looped or cut to `duration` (the timeline's length), levelled to "
            "`level` LUFS (-30 sits under a voice-over; -18 for music alone), faded in/out, and lowered by `duck` dB "
            "while the voice lines play: give `voices` as [{file, at}] with each voice clip's file and its start on "
            "the timeline (timeline_read). Place the result on its own lane at 0 s, volume 1; keep the voice clips "
            "where they are. Redo it after moving voice clips."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "music": {"type": "string"},
                "output": {"type": "string", "description": "Absolute path of the .wav to write."},
                "duration": {"type": "number", "exclusiveMinimum": 0, "maximum": audio_tools.MAX_BED_SECONDS},
                "start": {"type": "number", "minimum": 0, "default": 0,
                          "description": "Seconds into the song to begin (skip a slow intro)."},
                "level": {"type": "number", "minimum": -40, "maximum": -10, "default": -30},
                "fadeIn": {"type": "number", "minimum": 0, "default": 1},
                "fadeOut": {"type": "number", "minimum": 0, "default": 2},
                "duck": {"type": "number", "minimum": 0, "maximum": 24, "default": 8,
                         "description": "dB the music drops under the voices; 0 = no ducking."},
                "voices": {"type": "array", "items": {"type": "object", "properties": {
                    "file": {"type": "string"}, "at": {"type": "number", "minimum": 0}}, "required": ["file", "at"]}},
            },
            "required": ["music", "output", "duration"],
        },
    },
    {
        "name": "music_beats",
        "title": "Find the beats of a song",
        "description": "Beat and downbeat times (seconds from `start` in the song, i.e. timeline times when the bed "
                       "starts there at 0 s) and the tempo, to put cuts and transitions on the music: cut scenes on "
                       "downbeats, pop titles on beats. Needs librosa in the TTS venv.",
        "inputSchema": {
            "type": "object",
            "properties": {"music": {"type": "string"}, "start": {"type": "number", "minimum": 0, "default": 0},
                           "duration": {"type": "number", "exclusiveMinimum": 0,
                                        "description": "Seconds to analyse; the rest of the song when absent."}},
            "required": ["music"],
        },
    },
    {
        "name": "audio_master",
        "title": "Master an exported video's loudness",
        "description": "After export_wait: brings the exported video's sound to `target` LUFS (-14: YouTube, TikTok, "
                       "Reels, Facebook), true peak -1.5 dB, in two passes, the picture copied untouched, into a new "
                       "`output` .mp4. Reports the loudness before and after.",
        "inputSchema": {
            "type": "object",
            "properties": {"video": {"type": "string"}, "output": {"type": "string"},
                           "target": {"type": "number", "minimum": -24, "maximum": -9, "default": -14}},
            "required": ["video", "output"],
        },
    },
    {
        "name": "sfx_make",
        "title": "Make a sound effect",
        "description": "Synthesises a short effect here, free and with nothing to credit: whoosh (transitions, "
                       "things flying in), riser (build-up before a reveal), pop (an item appears), click, tick "
                       "(counters, typing), ding (a point made, a correct answer), impact (a big title lands). "
                       "Saved as .wav; place it on a lane at the moment it marks, quiet (volume 0.3-0.6) under the "
                       "voice. For real recorded effects use media_search kind sfx.",
        "inputSchema": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": list(audio_tools.SFX)},
                           "output": {"type": "string", "description": "Absolute path of the .wav to write."},
                           "duration": {"type": "number", "minimum": 0.02, "maximum": 10,
                                        "description": "Seconds; each kind has its own default."}},
            "required": ["kind", "output"],
        },
    },
]


def call_tool(name, arguments):
    """Runs one tool; returns its result as a JSON-able dict. Raises on bad input."""
    # the user may have changed engine or keys since the last call
    speech_env_file.apply(settings_variables() | media_sources.KEY_VARIABLES | image_generate.settings_variables())
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
    if name == "speech_voice_clone":
        if arguments.get("consent") is not True:
            raise ValueError("ask the user to confirm the voice is theirs or that they have the speaker's "
                             "permission, then pass consent: true")
        start = arguments.get("start") or 0.0
        return voice_library.save(arguments["name"], arguments["file"], start=float(start),
                                  duration=float(arguments.get("duration") or voice_library.MAX_SECONDS),
                                  replace=bool(arguments.get("replace")))
    if name == "speech_voice_remove":
        return voice_library.remove(arguments["name"])
    if name == "media_search":
        preview_dir = arguments.get("previewDir")
        if preview_dir:
            preview_dir = writable_file(Path(preview_dir) / "probe.jpg", (".jpg",)).parent
        return media_sources.search(arguments["query"], kind=arguments.get("kind") or "image",
                                    source=arguments.get("source") or "all",
                                    orientation=arguments.get("orientation") or "any",
                                    count=arguments.get("count") or 8, preview_dir=preview_dir,
                                    min_duration=arguments.get("minDuration"),
                                    max_duration=arguments.get("maxDuration"),
                                    allow_noncommercial=bool(arguments.get("allowNonCommercial")))
    if name == "media_fetch":
        output = writable_file(arguments["output"], (*media_sources.IMAGE_SUFFIXES, ".mp4",
                                                     *media_sources.AUDIO_SUFFIXES))
        return media_sources.fetch(arguments["id"], output)
    if name == "scene_render":
        return scene_render.render(arguments["html"], output=arguments.get("output"),
                                   duration=arguments.get("duration") or 5, size=arguments.get("size") or "16:9",
                                   fps=arguments.get("fps") or 30, stills=arguments.get("stills"),
                                   stills_dir=arguments.get("stillsDir"))
    if name == "image_engines":
        return {"engines": image_generate.list_engines()}
    if name == "image_generate":
        output = writable_file(arguments["output"], (".png",))
        return image_generate.generate(arguments["prompt"], output, aspect=arguments.get("aspect") or "16:9",
                                       quality=arguments.get("quality") or "medium",
                                       references=arguments.get("references") or (), engine=arguments.get("engine"),
                                       crop=arguments.get("crop", True) is not False)
    if name == "music_fit":
        return audio_tools.music_fit(arguments["music"], writable_file(arguments["output"], (".wav",)),
                                     arguments["duration"], start=arguments.get("start") or 0.0,
                                     level=arguments.get("level", -30), fade_in=arguments.get("fadeIn", 1),
                                     fade_out=arguments.get("fadeOut", 2), voices=arguments.get("voices") or (),
                                     duck=arguments.get("duck", 8))
    if name == "music_beats":
        return audio_tools.music_beats(arguments["music"], start=arguments.get("start") or 0.0,
                                       duration=arguments.get("duration"))
    if name == "audio_master":
        return audio_tools.audio_master(arguments["video"], writable_file(arguments["output"], (".mp4",)),
                                        target=arguments.get("target", audio_tools.PLATFORM_LOUDNESS))
    if name == "sfx_make":
        return audio_tools.sfx_make(arguments["kind"], writable_file(arguments["output"], (".wav",)),
                                    duration=arguments.get("duration"))
    raise KeyError(name)
