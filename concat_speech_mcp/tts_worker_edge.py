"""edge-tts worker: runs in the TTS venv (python -I), one call per process.

    tts_worker_edge.py voices              -> JSON [{name, locale, language, gender}] on stdout
    tts_worker_edge.py say <voice> <out>   text on stdin -> mp3 at <out>, JSON {words} on stdout

`words` are [{start, end, text}] in seconds, from the service's word
boundaries. The service now and then answers without audio, in bursts of a
few seconds; a line is tried again with a growing wait (1, 2, 4, 8 s) before
giving up. Errors go to stderr with exit status 1.
"""
import asyncio
import json
import sys
import time

ATTEMPTS = 5


async def voices():
    import edge_tts

    return [{"name": v["ShortName"], "locale": v["Locale"], "language": v["Locale"].split("-")[0].lower(),
             "gender": v.get("Gender", "")} for v in await edge_tts.list_voices()]


async def say(text, voice, out):
    import edge_tts

    words = []
    with open(out, "wb") as audio:
        async for chunk in edge_tts.Communicate(text, voice, boundary="WordBoundary").stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"start": round(start, 3), "end": round(start + chunk["duration"] / 1e7, 3),
                              "text": chunk["text"]})
    return {"words": words}


def main():
    try:
        if sys.argv[1] == "voices":
            result = asyncio.run(voices())
        else:
            voice, out = sys.argv[2], sys.argv[3]
            text = sys.stdin.read()
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    result = asyncio.run(say(text, voice, out))
                    break
                except Exception as failure:  # NoAudioReceived, dropped websocket...
                    if attempt == ATTEMPTS:
                        raise
                    print(f"attempt {attempt} failed ({type(failure).__name__}), retrying", file=sys.stderr)
                    time.sleep(2 ** (attempt - 1))
    except Exception as failure:
        print(f"{type(failure).__name__}: {failure}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
