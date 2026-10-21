"""Regroup whisper tokens into caption-sized utterances.

whisper.cpp cuts its segments on a fixed ~6 s window, straight through
sentences, which is no use as captions. Its token offsets run back to back
(each token ends where the next begins), so pauses cannot be read from them
either. Pauses are read from the audio instead (ffmpeg silencedetect), and
each token goes to the stretch of speech its time falls in. With `--dtw`
whisper gives each token a `t_dtw` (centiseconds) that is far closer to when
it was said than the offsets, which lag by about half a second.

Ported from the PoC pipeline (plans/20261021-0931-poc-concat-gd1-gd2).
"""
import re
import subprocess

from .process import run_checked

SPECIAL_TOKEN = re.compile(r"^\[_[A-Z0-9_]+_?\]$|^\[_TT_\d+\]$")
SILENCE_LINE = re.compile(r"silence_(start|end): (-?[\d.]+)")


def tokens_from_whisper_json(data):
    """Every spoken token as (start_ms, end_ms, text), special tokens dropped."""
    tokens = []
    for segment in data.get("transcription", []):
        for token in segment.get("tokens", []):
            text = token.get("text", "")
            if not text.strip() or SPECIAL_TOKEN.match(text.strip()):
                continue
            dtw = token.get("t_dtw", -1)
            if dtw is not None and dtw >= 0:
                tokens.append((dtw * 10, dtw * 10, text))
            else:
                tokens.append((token["offsets"]["from"], token["offsets"]["to"], text))
    return tokens


def detect_silences(audio_path, noise_db=-35, min_silence=0.35, run=subprocess.run):
    """(start, end) seconds of every silence ffmpeg hears in `audio_path`."""
    out = run_checked(
        ["ffmpeg", "-hide_banner", "-i", str(audio_path), "-af",
         f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
        run=run,
    )
    return parse_silences(out.stderr)


def parse_silences(ffmpeg_log):
    """Pairs silence_start/silence_end lines; an unclosed start runs to the end."""
    silences, start = [], None
    for kind, value in SILENCE_LINE.findall(ffmpeg_log):
        if kind == "start":
            start = max(0.0, float(value))
        elif start is not None:
            silences.append((start, float(value)))
            start = None
    if start is not None:
        silences.append((start, float("inf")))
    return silences


def speech_spans(silences, total):
    """The stretches between silences, within [0, total]."""
    spans, cursor = [], 0.0
    for start, end in silences:
        if start > cursor:
            spans.append((cursor, min(start, total)))
        cursor = max(cursor, end)
    if cursor < total:
        spans.append((cursor, total))
    return spans


def group_tokens_by_span(tokens, spans, drop_spaces=False):
    """Utterances: the tokens whose time falls in each speech span.

    Times are the span's (the audio's own start and end of speech). A token
    falling in no span (whisper drifting into a silence) joins the nearest.
    `drop_spaces` is for languages written without them (Japanese, Chinese),
    where whisper's token spaces are noise; elsewhere they separate words.
    """
    if not spans:
        return []
    buckets = [[] for _ in spans]
    for start_ms, end_ms, text in tokens:
        mid = (start_ms + end_ms) / 2000
        index = min(range(len(spans)), key=lambda i: 0 if spans[i][0] <= mid <= spans[i][1]
                    else min(abs(mid - spans[i][0]), abs(mid - spans[i][1])))
        buckets[index].append(text)
    joined = ["".join(b).replace(" ", "") if drop_spaces else " ".join("".join(b).split()) for b in buckets]
    return [
        {"start": round(s, 3), "end": round(e, 3), "text": text}
        for (s, e), b, text in zip(spans, buckets, joined) if b
    ]
