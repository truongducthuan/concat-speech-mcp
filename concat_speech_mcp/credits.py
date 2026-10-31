"""credits.json beside the media: where each fetched or generated file came from.

Stock media needs its author and licence shown (in the video or its
description), and AI images are best disclosed; one list per folder keeps
that at hand when the video is published. An entry for the same file is
replaced, not repeated.
"""
import json
import os
from pathlib import Path

NAME = "credits.json"


def record(media_file, entry):
    """Adds or replaces `media_file`'s entry in credits.json of its folder; returns that file's path."""
    media_file = Path(media_file)
    book = media_file.parent / NAME
    try:
        entries = json.loads(book.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            entries = []
    except (OSError, ValueError):
        entries = []
    entries = [e for e in entries if e.get("file") != media_file.name]
    entries.append({"file": media_file.name, **{k: v for k, v in entry.items() if v not in (None, "")}})
    temp = book.with_name(f".{NAME}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(book)
    return str(book)
