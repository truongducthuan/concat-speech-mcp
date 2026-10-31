"""media_search and media_fetch: free stock photos, videos, music and sound effects, with their credits.

Sources:
- `commons`: Wikimedia Commons, photos and videos, no key (CC / public
  domain, the author and licence must be credited; its videos are WebM and
  are converted to H.264 mp4 on fetch);
- `pixabay`: photos and videos, free key in PIXABAY_API_KEY (Pixabay
  Content License, no credit required);
- `pexels`: photos and videos, free key in PEXELS_API_KEY (Pexels License,
  credit appreciated);
- music and sound effects (kinds "music", "sfx"): see audio_sources.

Non-commercial licences are left out unless `allowNonCommercial`. A search keeps its results in memory under ids ("pexels-video:123"); fetching
an id downloads that file (photos at most ~1920 px wide, videos the largest
file up to 1080p, audio transcoded to the asked .wav/.mp3/.m4a) and records its author and licence in credits.json beside it.
`previewDir` saves small previews to look at before choosing.
"""
import html
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

from . import audio_sources, credits, web
from .process import EngineError, run_checked

SOURCES = {"commons": None, "pixabay": "PIXABAY_API_KEY", "pexels": "PEXELS_API_KEY"}
ALL_SOURCES = {**SOURCES, **audio_sources.KEYS}
KEY_VARIABLES = {v for v in ALL_SOURCES.values() if v}
KINDS = ("image", "video", *audio_sources.KINDS)
AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a")
ORIENTATIONS = ("any", "landscape", "portrait", "square")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
MAX_WIDTH = 1920
MAX_ORIGINAL_VIDEO = 300 * 1024 * 1024  # above this a Commons video comes as its largest ready-made transcode
_found = {}  # id -> result of the searches so far (this server's lifetime)


class MediaError(ValueError):
    pass


def _key(source, env):
    variable = ALL_SOURCES[source]
    return (env.get(variable) or "").strip() if variable else None


def _shape(width, height):
    if not width or not height:
        return "any"
    ratio = width / height
    return "landscape" if ratio > 1.15 else "portrait" if ratio < 0.87 else "square"


def _plain(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _person(text):
    """An author field as one line: Commons sometimes carries a whole postal address under the name."""
    lines = [line.strip() for line in _plain(text).splitlines() if line.strip()]
    return lines[0] if lines else "unknown"


def search_commons(query, kind, orientation, count, get_json=web.get_json):
    if kind != "image":
        return []
    data = get_json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": str(min(50, count * 4)),
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": str(MAX_WIDTH)},
        what="Wikimedia Commons")
    found = []
    for page in sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        meta = {k: v.get("value") for k, v in (info.get("extmetadata") or {}).items()}
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        width, height = info.get("width"), info.get("height")
        # the original can be 9000 px and 30 MB; the 1920 px rendition is plenty for video
        scaled = (width or 0) > MAX_WIDTH and info.get("thumburl")
        if scaled:
            width, height = info.get("thumbwidth"), info.get("thumbheight")
        found.append({
            "id": f"commons:{page['pageid']}", "source": "commons", "kind": "image",
            "title": _plain(meta.get("ObjectName")) or page["title"].removeprefix("File:"),
            "author": _person(meta.get("Artist")), "license": meta.get("LicenseShortName") or "see page",
            "licenseUrl": meta.get("LicenseUrl"), "page": info.get("descriptionurl"),
            "width": width, "height": height, "shape": _shape(width, height),
            "preview": info.get("thumburl"),
            "download": info.get("thumburl") if scaled else info.get("url"),
            "creditRequired": True})
    return found


def search_commons_video(query, count, get_json=web.get_json):
    data = get_json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:video", "gsrlimit": str(min(50, count * 3)),
        "prop": "videoinfo", "viprop": "url|size|mime|extmetadata|metadata|derivatives"}, what="Wikimedia Commons")
    found = []
    for page in sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        info = (page.get("videoinfo") or [{}])[0]
        if not str(info.get("mime", "")).startswith(("video/", "application/ogg")):
            continue
        meta = {k: v.get("value") for k, v in (info.get("extmetadata") or {}).items()}
        plain = {m["name"]: m["value"] for m in info.get("metadata") or [] if not isinstance(m.get("value"), (list, dict))}
        seconds = plain.get("playtime_seconds") or plain.get("length")
        width, height, url = info.get("width"), info.get("height"), info.get("url")
        if max(width or 0, height or 0) > MAX_WIDTH or (info.get("size") or 0) > MAX_ORIGINAL_VIDEO:
            # the original is 4K or huge: its largest WebM transcode (by pixels) is plenty for a 1080p edit
            ready = [d for d in info.get("derivatives", []) if "webm" in d.get("type", "") and d.get("src")]
            if not ready:
                continue
            best = max(ready, key=lambda d: (d.get("width") or 0) * (d.get("height") or 0))
            width, height, url = best.get("width"), best.get("height"), best["src"]
        found.append({
            "id": f"commons-video:{page['pageid']}", "source": "commons", "kind": "video",
            "title": _plain(meta.get("ObjectName")) or page["title"].removeprefix("File:"),
            "author": _person(meta.get("Artist")), "license": meta.get("LicenseShortName") or "see page",
            "licenseUrl": meta.get("LicenseUrl"), "page": info.get("descriptionurl"),
            "width": width, "height": height, "shape": _shape(width, height),
            "duration": round(float(seconds), 2) if seconds else None, "download": url,
            "creditRequired": not any(free in (meta.get("LicenseShortName") or "").lower()
                                      for free in ("cc0", "public domain"))})
    return found


def search_pixabay(query, kind, orientation, count, key, get_json=web.get_json):
    params = {"key": key, "q": query[:100], "per_page": str(max(3, min(200, count))), "safesearch": "true"}
    if orientation in ("landscape", "portrait"):
        params["orientation"] = "horizontal" if orientation == "landscape" else "vertical"
    if kind == "image":
        params["image_type"] = "photo"
    url = "https://pixabay.com/api/" + ("videos/" if kind == "video" else "")
    data = get_json(url, params, what="Pixabay", secret=key)
    found = []
    for hit in data.get("hits", []):
        common = {"id": f"pixabay-{kind}:{hit['id']}", "source": "pixabay", "kind": kind,
                  "title": hit.get("tags", ""), "author": hit.get("user", ""), "license": "Pixabay Content License",
                  "licenseUrl": "https://pixabay.com/service/license-summary/", "page": hit.get("pageURL"),
                  "creditRequired": False, "aiGenerated": bool(hit.get("isAiGenerated"))}
        if kind == "image":
            width, height = hit.get("imageWidth"), hit.get("imageHeight")
            found.append({**common, "width": width, "height": height, "shape": _shape(width, height),
                          "preview": hit.get("webformatURL"), "download": hit.get("largeImageURL")})
        else:
            files = hit.get("videos", {})
            sizes = [f for f in files.values() if isinstance(f, dict) and f.get("url")
                     and max(f.get("width") or 0, f.get("height") or 0) <= MAX_WIDTH]
            if not sizes:  # only 4K offered: take the smallest file there is
                sizes = sorted((f for f in files.values() if isinstance(f, dict) and f.get("url")),
                               key=lambda f: (f.get("width") or 0))[:1]
            if not sizes:
                continue
            best = max(sizes, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
            found.append({**common, "width": best.get("width"), "height": best.get("height"),
                          "shape": _shape(best.get("width"), best.get("height")), "duration": hit.get("duration"),
                          "preview": files.get("medium", {}).get("thumbnail") or best.get("thumbnail"),
                          "download": best["url"]})
    return found


def search_pexels(query, kind, orientation, count, key, get_json=web.get_json):
    params = {"query": query, "per_page": str(max(1, min(80, count)))}
    if orientation != "any":
        params["orientation"] = orientation
    url = "https://api.pexels.com/" + ("videos/search" if kind == "video" else "v1/search")
    data = get_json(url, params, headers={"Authorization": key}, what="Pexels", secret=key)
    found = []
    for item in data.get("videos" if kind == "video" else "photos", []):
        common = {"id": f"pexels-{kind}:{item['id']}", "source": "pexels", "kind": kind,
                  "license": "Pexels License", "licenseUrl": "https://www.pexels.com/license/",
                  "page": item.get("url"), "creditRequired": False}
        if kind == "image":
            width, height = item.get("width"), item.get("height")
            found.append({**common, "title": item.get("alt", ""), "author": item.get("photographer", ""),
                          "width": width, "height": height, "shape": _shape(width, height),
                          "preview": item.get("src", {}).get("medium"),
                          "download": item.get("src", {}).get("large2x") or item.get("src", {}).get("original")})
        else:
            files = [f for f in item.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")
                     and max(f.get("width") or 0, f.get("height") or 0) <= MAX_WIDTH]
            if not files:
                continue
            best = max(files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
            found.append({**common, "title": Path(item.get("url", "")).name.replace("-", " "),
                          "author": item.get("user", {}).get("name", ""), "width": best.get("width"),
                          "height": best.get("height"), "shape": _shape(best.get("width"), best.get("height")),
                          "duration": item.get("duration"), "preview": item.get("image"), "download": best["link"]})
    return found


def _search_one(name, query, kind, orientation, count, key, minimum, maximum, commercial_only, get_json):
    if kind in audio_sources.KINDS:
        if name == "commons":
            return audio_sources.search_commons(query, kind, count, minimum, maximum, get_json=get_json)
        if name == "freesound":
            return audio_sources.search_freesound(query, kind, count, minimum, maximum, key,
                                                  commercial_only=commercial_only, get_json=get_json)
        return audio_sources.search_jamendo(query, kind, count, minimum, maximum, key, get_json=get_json)
    if name == "commons":
        if kind == "video":
            return search_commons_video(query, count, get_json=get_json)
        return search_commons(query, kind, orientation, count, get_json=get_json)
    if name == "pixabay":
        return search_pixabay(query, kind, orientation, count, key, get_json=get_json)
    return search_pexels(query, kind, orientation, count, key, get_json=get_json)


def search(query, kind="image", source="all", orientation="any", count=8, preview_dir=None, min_duration=None,
           max_duration=None, allow_noncommercial=False, env=None, get_json=web.get_json, fetch=web.download):
    """Results from each source asked for that is ready; `skipped` says why a source was left out."""
    env = os.environ if env is None else env
    query = " ".join(str(query).split())
    if not query:
        raise MediaError("query is empty")
    if kind not in KINDS:
        raise MediaError(f"kind must be one of {', '.join(KINDS)}")
    if orientation not in ORIENTATIONS:
        raise MediaError(f"orientation must be one of {', '.join(ORIENTATIONS)}")
    offered = audio_sources.SOURCES_FOR[kind] if kind in audio_sources.KINDS else \
        (("pixabay", "pexels", "commons") if kind == "video" else tuple(SOURCES))
    if source != "all" and source not in offered:
        raise MediaError(f"source for {kind} must be all or one of {', '.join(offered)}")
    count = max(1, min(30, int(count)))
    results, skipped = [], {}
    for name in (offered if source == "all" else [source]):
        key = _key(name, env)
        if ALL_SOURCES[name] and not key:
            skipped[name] = f"needs a free key in {ALL_SOURCES[name]} (.env)"
            continue
        try:
            found = _search_one(name, query, kind, orientation, count, key, min_duration, max_duration,
                                not allow_noncommercial, get_json)
        except EngineError as failure:
            skipped[name] = str(failure)
            continue
        if orientation != "any" and kind in ("image", "video"):
            found = [r for r in found if r["shape"] == orientation]
        if kind == "video" and (min_duration is not None or max_duration is not None):
            found = [r for r in found if r.get("duration") is not None
                     and (min_duration is None or r["duration"] >= min_duration)
                     and (max_duration is None or r["duration"] <= max_duration)]
        if not allow_noncommercial:
            found = [r for r in found if audio_sources.commercial(r["license"])]
        results += found[:count]
    for result in results:
        _found[result["id"]] = result
    if preview_dir:
        folder = Path(preview_dir)
        for result in results:
            if result.get("preview"):
                target = folder / f"{result['id'].replace(':', '-')}.jpg"
                try:
                    fetch(result["preview"], target, what=f"the preview of {result['id']}")
                    result["previewFile"] = str(target)
                except EngineError:
                    pass
    shown = [{k: v for k, v in r.items() if k != "download"} for r in results]
    return {"query": query, "kind": kind, "results": shown, "skipped": skipped}


def suffix_of(result):
    path = urllib.parse.urlparse(result["download"]).path.lower()
    if result["kind"] == "video":
        return Path(path).suffix or ".mp4"
    if result["kind"] in audio_sources.KINDS:
        return Path(path).suffix or ".mp3"
    return next((s for s in IMAGE_SUFFIXES if path.endswith(s)), ".jpg").replace(".jpeg", ".jpg")


def fetch(media_id, output, download=web.download, run=subprocess.run):
    """Downloads the search result `media_id` to `output`: a picture or video under its real suffix, audio
    transcoded to the asked .wav/.mp3/.m4a (48 kHz) when it comes in another format."""
    result = _found.get(media_id)
    if result is None:
        raise MediaError(f"{media_id!r} is not among this session's search results: run media_search first")
    if result["kind"] in audio_sources.KINDS:
        target = Path(output) if Path(output).suffix.lower() in AUDIO_SUFFIXES else Path(output).with_suffix(".wav")
        source_suffix = suffix_of(result)
        if source_suffix == target.suffix.lower():
            size = download(result["download"], target, what=f"{media_id}")
        else:
            raw = target.with_name(f".{target.stem}.download{source_suffix}")
            try:
                download(result["download"], raw, what=f"{media_id}")
                run_checked(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-vn", "-ar", "48000", str(target)],
                            run=run, timeout=300)
            finally:
                raw.unlink(missing_ok=True)
            size = target.stat().st_size
    elif result["kind"] == "video" and suffix_of(result) != ".mp4":
        # WebM / Ogg from Commons: H.264 mp4 opens everywhere, Concat included
        target = Path(output).with_suffix(".mp4")
        raw = target.with_name(f".{target.stem}.download{suffix_of(result)}")
        try:
            download(result["download"], raw, what=f"{media_id}")
            run_checked(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-c:v", "libx264", "-preset", "medium",
                         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                         str(target)], run=run, timeout=1800)
        finally:
            raw.unlink(missing_ok=True)
        size = target.stat().st_size
    else:
        target = Path(output).with_suffix(suffix_of(result))
        size = download(result["download"], target, what=f"{media_id}")
    book = credits.record(target, {k: result.get(k) for k in ("source", "title", "author", "license", "licenseUrl",
                                                              "page", "creditRequired", "aiGenerated")}
                         | {"id": media_id})
    credit = f"{result['title']} - {result['author']}, {result['license']}" + (
        f" ({result['page']})" if result.get("page") else "")
    return {"output": str(target), "bytes": size, "kind": result["kind"], "width": result.get("width"),
            "height": result.get("height"), "duration": result.get("duration"), "credit": credit,
            "creditRequired": result["creditRequired"], "credits": book}
