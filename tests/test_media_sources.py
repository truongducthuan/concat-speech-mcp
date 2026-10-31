import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from concat_speech_mcp import media_sources
from concat_speech_mcp.media_sources import MediaError

COMMONS = {"query": {"pages": {
    "2": {"pageid": 2, "index": 2, "title": "File:Small.jpg", "imageinfo": [{
        "mime": "image/jpeg", "width": 800, "height": 1200, "url": "https://upload.example/small.jpg",
        "thumburl": "https://upload.example/thumb-small.jpg", "descriptionurl": "https://commons.example/Small",
        "extmetadata": {"Artist": {"value": "<a href='x'>Ann</a>"}, "LicenseShortName": {"value": "CC0"}}}]},
    "1": {"pageid": 1, "index": 1, "title": "File:Lake.jpg", "imageinfo": [{
        "mime": "image/jpeg", "width": 4000, "height": 2000, "url": "https://upload.example/lake.jpg",
        "thumburl": "https://upload.example/thumb-lake.jpg", "thumbwidth": 1920, "thumbheight": 960,
        "descriptionurl": "https://commons.example/Lake",
        "extmetadata": {"Artist": {"value": "Bob &amp; Co"}, "LicenseShortName": {"value": "CC BY 4.0"},
                        "LicenseUrl": {"value": "https://cc.example/by4"}, "ObjectName": {"value": "Lake"}}}]},
    "3": {"pageid": 3, "index": 3, "title": "File:Map.svg", "imageinfo": [{"mime": "image/svg+xml"}]},
}}}
PEXELS_VIDEOS = {"videos": [{"id": 7, "url": "https://www.pexels.com/video/hanoi-street-7/", "duration": 12,
                             "image": "https://pexels.example/7.jpg", "user": {"name": "Chi"},
                             "video_files": [
                                 {"file_type": "video/mp4", "width": 3840, "height": 2160, "link": "https://p/4k"},
                                 {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "https://p/hd"},
                                 {"file_type": "video/mp4", "width": 1280, "height": 720, "link": "https://p/720"}]}]}


class FakeGet:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def __call__(self, url, params=None, headers=None, what="", secret=None):
        self.calls.append((url, params, headers, secret))
        return self.replies[url]


class MediaSearchTest(unittest.TestCase):
    def setUp(self):
        media_sources._found.clear()

    def test_commons_search_reads_credit_and_takes_1920_rendition_of_big_originals(self):
        get = FakeGet({"https://commons.wikimedia.org/w/api.php": COMMONS})

        found = media_sources.search("lake", source="commons", env={}, get_json=get)["results"]

        self.assertEqual([r["id"] for r in found], ["commons:1", "commons:2"])  # svg left out, search order kept
        lake = found[0]
        self.assertEqual((lake["author"], lake["license"], lake["title"]), ("Bob & Co", "CC BY 4.0", "Lake"))
        self.assertEqual((lake["width"], lake["height"], lake["shape"]), (1920, 960, "landscape"))
        self.assertNotIn("download", lake)
        self.assertEqual(media_sources._found["commons:1"]["download"], "https://upload.example/thumb-lake.jpg")
        self.assertEqual(media_sources._found["commons:2"]["download"], "https://upload.example/small.jpg")
        self.assertEqual(found[1]["author"], "Ann")

    def test_search_orientation_keeps_only_that_shape(self):
        get = FakeGet({"https://commons.wikimedia.org/w/api.php": COMMONS})

        found = media_sources.search("lake", source="commons", orientation="portrait", env={}, get_json=get)

        self.assertEqual([r["id"] for r in found["results"]], ["commons:2"])

    def test_search_sources_without_keys_are_skipped_with_reason(self):
        get = FakeGet({"https://commons.wikimedia.org/w/api.php": COMMONS})

        result = media_sources.search("lake", env={}, get_json=get)

        self.assertIn("PIXABAY_API_KEY", result["skipped"]["pixabay"])
        self.assertIn("PEXELS_API_KEY", result["skipped"]["pexels"])
        self.assertEqual(len(get.calls), 1)

    def test_pexels_video_takes_largest_mp4_up_to_1080p_and_sends_key_in_header(self):
        get = FakeGet({"https://api.pexels.com/videos/search": PEXELS_VIDEOS})

        found = media_sources.search("hanoi", kind="video", source="pexels", env={"PEXELS_API_KEY": "k1"},
                                     get_json=get)["results"]

        self.assertEqual(media_sources._found["pexels-video:7"]["download"], "https://p/hd")
        self.assertEqual((found[0]["duration"], found[0]["author"]), (12, "Chi"))
        self.assertEqual((get.calls[0][2], get.calls[0][3]), ({"Authorization": "k1"}, "k1"))

    def test_search_refuses_blank_query_and_unknown_kind(self):
        with self.assertRaises(MediaError):
            media_sources.search("  ", env={})
        with self.assertRaises(MediaError):
            media_sources.search("x", kind="gif", env={})

    def test_commons_video_takes_original_when_small_else_largest_webm_and_filters_length(self):
        pages = {"query": {"pages": {
            "1": {"pageid": 1, "index": 1, "title": "File:Bay.webm", "videoinfo": [{
                "mime": "video/webm", "width": 1920, "height": 1080, "size": 30_000_000, "url": "https://u/bay.webm",
                "metadata": [{"name": "playtime_seconds", "value": 15.6}],
                "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"}, "Artist": {"value": "Ann"}}}]},
            "2": {"pageid": 2, "index": 2, "title": "File:Big.webm", "videoinfo": [{
                "mime": "video/webm", "width": 3840, "height": 2160, "size": 900_000_000, "url": "https://u/big.webm",
                "metadata": [{"name": "playtime_seconds", "value": 30}],
                "derivatives": [{"type": "video/webm", "width": 854, "height": 480, "src": "https://u/480.webm"},
                                {"type": "video/webm", "width": 1920, "height": 1080, "src": "https://u/1080.webm"},
                                {"type": "video/quicktime", "width": 640, "height": 360, "src": "https://u/360.mov"}],
                "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]},
            "3": {"pageid": 3, "index": 3, "title": "File:Film.webm", "videoinfo": [{
                "mime": "video/webm", "width": 1280, "height": 720, "size": 400_000_000, "url": "https://u/film.webm",
                "metadata": [{"name": "playtime_seconds", "value": 2700}], "derivatives": [],
                "extmetadata": {"LicenseShortName": {"value": "CC BY 3.0"}}}]},
        }}}
        get = FakeGet({"https://commons.wikimedia.org/w/api.php": pages})

        found = media_sources.search("bay", kind="video", source="commons", max_duration=60, env={},
                                     get_json=get)["results"]

        self.assertEqual([r["id"] for r in found], ["commons-video:1", "commons-video:2"])
        self.assertEqual(media_sources._found["commons-video:1"]["download"], "https://u/bay.webm")
        self.assertEqual(media_sources._found["commons-video:2"]["download"], "https://u/1080.webm")
        self.assertEqual((found[1]["width"], found[1]["creditRequired"]), (1920, False))


class CloudflareBlockTest(unittest.TestCase):
    def test_bot_check_page_becomes_a_plain_reason(self):
        import io
        import urllib.error

        from concat_speech_mcp import web
        from concat_speech_mcp.process import EngineError

        def blocked(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {"cf-mitigated": "challenge"},
                                         io.BytesIO(b"<!DOCTYPE html><html><head><title>Just a moment...</title>"))

        with self.assertRaisesRegex(EngineError, "Cloudflare bot check .*not a key problem"):
            web.get_json("https://pixabay.com/api/", {"key": "k"}, what="Pixabay", secret="k", urlopen=blocked)


class MediaFetchTest(unittest.TestCase):
    def setUp(self):
        media_sources._found.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_fetch_sets_real_suffix_and_records_credit_once(self):
        media_sources.search("lake", source="commons", env={},
                             get_json=FakeGet({"https://commons.wikimedia.org/w/api.php": COMMONS}))
        written = []

        def download(url, target, what=""):
            written.append(url)
            target.write_bytes(b"jpg")
            return 3

        made = media_sources.fetch("commons:1", Path(self.tmp.name) / "lake.png", download=download)
        media_sources.fetch("commons:1", Path(self.tmp.name) / "lake.png", download=download)

        self.assertTrue(made["output"].endswith("lake.jpg"))
        self.assertTrue(made["creditRequired"])
        self.assertIn("Bob & Co, CC BY 4.0", made["credit"])
        book = json.loads((Path(self.tmp.name) / "credits.json").read_text())
        self.assertEqual([(e["file"], e["license"]) for e in book], [("lake.jpg", "CC BY 4.0")])

    def test_fetch_unknown_id_asks_to_search_first(self):
        with self.assertRaisesRegex(MediaError, "run media_search first"):
            media_sources.fetch("pexels-image:1", Path(self.tmp.name) / "x.jpg", download=mock.Mock())


if __name__ == "__main__":
    unittest.main()
