"""Free music and sound effects for media_search (kinds "music" and "sfx").

- `commons`: Wikimedia Commons recordings, no key; good for music (e.g.
  "Kevin MacLeod calm", CC BY: credit required), poor for effects;
- `freesound`: Freesound.org effects and loops, free key in FREESOUND_API_KEY;
  served as its high-quality mp3 preview (full files need OAuth);
- `jamendo`: Jamendo independent music, free client id in JAMENDO_CLIENT_ID.

Non-commercial licences (CC BY-NC…) are left out unless asked for, as most
videos end up on monetised channels. Results join media_search's ids; fetch
them with media_fetch (transcoded to the asked .wav/.mp3/.m4a when needed).
"""
import re

from . import web
from .process import EngineError

KEYS = {"commons": None, "freesound": "FREESOUND_API_KEY", "jamendo": "JAMENDO_CLIENT_ID"}
KINDS = ("music", "sfx")
SOURCES_FOR = {"music": ("commons", "jamendo", "freesound"), "sfx": ("freesound", "commons")}
AUDIO_MIME = ("application/ogg", "audio/ogg", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/x-flac", "audio/flac",
              "audio/webm")


def cc_license(url):
    """("CC0" | "CC BY-SA 4.0" ..., credit required) from a Creative Commons licence URL."""
    url = (url or "").lower()
    if "publicdomain/zero" in url or "publicdomain/mark" in url:
        return "CC0", False
    match = re.search(r"/licenses/([a-z+-]+)/(\d\.\d)?", url)
    if match:
        return f"CC {match[1].upper()}" + (f" {match[2]}" if match[2] else ""), True
    return url or "see page", True


def commercial(license_name):
    """False for non-commercial licences (CC BY-NC…), which most monetised videos cannot use."""
    return "NC" not in re.split(r"[\s-]+", (license_name or "").upper())


def _duration_ok(seconds, minimum, maximum):
    return seconds is not None and (minimum is None or seconds >= minimum) and (maximum is None or seconds <= maximum)


def search_commons(query, kind, count, minimum, maximum, get_json=web.get_json):
    from .media_sources import _person, _plain

    data = get_json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:audio", "gsrlimit": "50",
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata|metadata"}, what="Wikimedia Commons")
    found = []
    for page in sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in AUDIO_MIME:
            continue
        meta = {k: v.get("value") for k, v in (info.get("extmetadata") or {}).items()}
        plain = {m["name"]: m["value"] for m in info.get("metadata") or [] if not isinstance(m.get("value"), list)}
        seconds = plain.get("playtime_seconds") or plain.get("length")
        seconds = round(float(seconds), 2) if seconds else None
        if not _duration_ok(seconds, minimum, maximum):
            continue
        found.append({"id": f"commons-{kind}:{page['pageid']}", "source": "commons", "kind": kind,
                      "title": _plain(meta.get("ObjectName")) or page["title"].removeprefix("File:"),
                      "author": _person(meta.get("Artist")),
                      "license": meta.get("LicenseShortName") or "see page", "licenseUrl": meta.get("LicenseUrl"),
                      "page": info.get("descriptionurl"), "duration": seconds, "download": info.get("url"),
                      "creditRequired": "cc0" not in (meta.get("LicenseShortName") or "").lower()
                                        and "public domain" not in (meta.get("LicenseShortName") or "").lower()})
    return found[: count * 2]


def search_freesound(query, kind, count, minimum, maximum, key, commercial_only=True, get_json=web.get_json):
    low = 0 if minimum is None else minimum
    high = "*" if maximum is None else maximum
    params = {"query": query, "token": key, "page_size": str(min(50, count * 2)),
              "fields": "id,name,username,license,duration,previews,url,tags",
              "filter": f"duration:[{low} TO {high}]" + (" tag:music" if kind == "music" else "")
                        # asked of Freesound itself: much of its music is CC BY-NC, which would fill the page
                        + (' license:("Attribution" OR "Creative Commons 0")' if commercial_only else "")}
    data = get_json("https://freesound.org/apiv2/search/text/", params, what="Freesound", secret=key)
    found = []
    for hit in data.get("results", []):
        short, credit = cc_license(hit.get("license"))
        preview = (hit.get("previews") or {}).get("preview-hq-mp3")
        if not preview:
            continue
        found.append({"id": f"freesound-{kind}:{hit['id']}", "source": "freesound", "kind": kind,
                      "title": hit.get("name", ""), "author": hit.get("username", ""), "license": short,
                      "licenseUrl": hit.get("license"), "page": hit.get("url"),
                      "duration": round(float(hit.get("duration") or 0), 2), "download": preview,
                      "creditRequired": credit})
    return found


def search_jamendo(query, kind, count, minimum, maximum, key, get_json=web.get_json):
    if kind != "music":
        return []
    params = {"client_id": key, "format": "json", "limit": str(min(50, count * 2)), "search": query,
              "audioformat": "mp32", "include": "musicinfo", "ccnc": "false"}
    if minimum is not None or maximum is not None:
        params["durationbetween"] = f"{int(minimum or 0)}_{int(maximum or 3600)}"
    data = get_json("https://api.jamendo.com/v3.0/tracks/", params, what="Jamendo", secret=key)
    status = data.get("headers", {})
    if status.get("status") == "failed":
        raise EngineError(f"Jamendo: {status.get('error_message', 'refused')}".replace(key, "***"))
    found = []
    for track in data.get("results", []):
        if not track.get("audiodownload_allowed", True) or not (track.get("audiodownload") or track.get("audio")):
            continue
        ccurl = track.get("license_ccurl", "")
        short, _ = cc_license(ccurl)
        found.append({"id": f"jamendo-music:{track['id']}", "source": "jamendo", "kind": "music",
                      "title": track.get("name", ""), "author": track.get("artist_name", ""), "license": short,
                      "licenseUrl": ccurl, "page": track.get("shareurl"), "duration": track.get("duration"),
                      "download": track.get("audiodownload") or track.get("audio"), "creditRequired": True})
    return found
