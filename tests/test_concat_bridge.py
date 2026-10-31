import io
import json
import os
import sys
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from concat_speech_mcp.concat_bridge import BridgeError, ConcatBridge
from concat_speech_mcp.protocol import bridge_from_env, handle, serve

FAKE = [sys.executable, str(Path(__file__).with_name("fake_concat_mcp.py"))]


def request(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


class BridgeTestCase(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="concat-bridge-test-")
        self.starts = Path(self.workdir) / "starts.log"
        os.environ["FAKE_CONCAT_STARTS"] = str(self.starts)
        self.bridge = ConcatBridge(FAKE, call_timeout=2, start_timeout=5)

    def tearDown(self):
        self.bridge.close()
        os.environ.pop("FAKE_CONCAT_STARTS", None)
        shutil.rmtree(self.workdir, ignore_errors=True)

    def start_count(self):
        return len(self.starts.read_text().splitlines()) if self.starts.exists() else 0


class ConcatBridgeTest(BridgeTestCase):
    def test_bridge_tools_list_offers_speech_then_concat_tools(self):
        # Act
        tools = handle(request("tools/list"), bridge=self.bridge)["result"]["tools"]

        # Assert
        names = [t["name"] for t in tools]
        self.assertEqual(names[:15], ["speech_transcribe", "speech_engines", "speech_voices", "speech_synthesize",
                                     "speech_voice_clone", "speech_voice_remove", "media_search", "media_fetch",
                                                 "scene_render", "image_engines", "image_generate", "music_fit",
                                                 "music_beats", "audio_master", "sfx_make"])
        self.assertEqual(names[15:], ["echo", "frame", "crash", "stall", "garbage", "ask", "orphan"])

    def test_bridge_initialize_merges_concat_instructions(self):
        result = handle(request("initialize", {"protocolVersion": "2025-06-18"}), bridge=self.bridge)["result"]

        self.assertTrue(result["instructions"].startswith("FAKE CONCAT INSTRUCTIONS"))
        self.assertIn("speech_transcribe", result["instructions"])

    def test_bridge_concat_tool_call_result_passes_through_unchanged(self):
        # Arrange
        arguments = {"path": "/x", "n": 1}

        # Act
        result = handle(request("tools/call", {"name": "echo", "arguments": arguments}), bridge=self.bridge)["result"]

        # Assert
        self.assertEqual(json.loads(result["content"][0]["text"]), arguments)
        self.assertFalse(result["isError"])

    def test_bridge_image_content_is_not_rewritten(self):
        result = handle(request("tools/call", {"name": "frame"}), bridge=self.bridge)["result"]

        self.assertEqual(result["content"][0], {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"})

    def test_bridge_unknown_tool_keeps_concat_rpc_error(self):
        response = handle(request("tools/call", {"name": "nope"}), bridge=self.bridge)

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("nope", response["error"]["message"])

    def test_bridge_speech_tool_is_answered_locally_not_by_concat(self):
        # Arrange
        local = lambda name, args: {"voices": []}

        # Act
        result = handle(request("tools/call", {"name": "speech_voices"}), call=local, bridge=self.bridge)["result"]

        # Assert
        self.assertEqual(result["structuredContent"], {"voices": []})
        self.assertEqual(self.start_count(), 0)

    def test_bridge_concat_crash_is_tool_error_then_restarts(self):
        # Act
        crashed = handle(request("tools/call", {"name": "crash"}), bridge=self.bridge)["result"]
        after = handle(request("tools/call", {"name": "echo", "arguments": {"ok": True}}, 2), bridge=self.bridge)

        # Assert
        self.assertTrue(crashed["isError"])
        self.assertIn("exited", crashed["content"][0]["text"])
        self.assertEqual(json.loads(after["result"]["content"][0]["text"]), {"ok": True})
        self.assertEqual(self.start_count(), 2)

    def test_bridge_stalled_call_times_out_then_next_call_restarts_concat(self):
        # Regression (review M3): a hung child was kept, so every later call hung too.
        # Act
        stalled = handle(request("tools/call", {"name": "stall"}), bridge=self.bridge)["result"]
        after = handle(request("tools/call", {"name": "echo", "arguments": {"n": 2}}, 2), bridge=self.bridge)

        # Assert
        self.assertTrue(stalled["isError"])
        self.assertIn("did not answer", stalled["content"][0]["text"])
        self.assertEqual(json.loads(after["result"]["content"][0]["text"]), {"n": 2})
        self.assertEqual(self.start_count(), 2)

    def test_bridge_non_utf8_line_does_not_kill_the_reader(self):
        # Regression (review H2): a bad byte killed the reader thread; the answer behind it never arrived.
        result = handle(request("tools/call", {"name": "garbage"}), bridge=self.bridge)["result"]

        self.assertEqual(result["content"][0]["text"], "after")

    def test_bridge_child_ping_is_answered(self):
        # Regression (review M2): requests from Concat were dropped, leaving it waiting forever.
        result = handle(request("tools/call", {"name": "ask"}), bridge=self.bridge)["result"]

        self.assertEqual(json.loads(result["content"][0]["text"]), {"jsonrpc": "2.0", "id": "srv-1", "result": {}})

    def test_bridge_exit_with_pipe_held_open_is_seen_quickly(self):
        # Regression (review H1): a child exiting while a process it started held stdout looked alive
        # until the call timed out, and close() blocked on the held pipe.
        # Arrange
        self.bridge.call_timeout = 20
        began = time.monotonic()

        # Act
        result = handle(request("tools/call", {"name": "orphan"}), bridge=self.bridge)["result"]
        self.bridge.close()

        # Assert
        self.assertIn("exited", result["content"][0]["text"])
        self.assertLess(time.monotonic() - began, 5)

    def test_bridge_serve_closes_concat_when_client_leaves(self):
        # Arrange
        stdin = io.StringIO(json.dumps(request("tools/list")) + "\n")

        # Act
        serve(stdin, io.StringIO(), bridge=self.bridge)

        # Assert
        self.assertFalse(self.bridge.running())
        self.assertEqual(self.start_count(), 1)


class BridgeUnavailableTest(unittest.TestCase):
    def test_bridge_missing_binary_keeps_speech_tools_working(self):
        # Arrange
        bridge = ConcatBridge(["/nonexistent/concat", "--mcp"])

        # Act
        init = handle(request("initialize"), bridge=bridge)["result"]
        tools = handle(request("tools/list", request_id=2), bridge=bridge)["result"]["tools"]
        call = handle(request("tools/call", {"name": "clip_add"}, 3), bridge=bridge)["result"]

        # Assert
        self.assertEqual(init["serverInfo"]["name"], "concat-speech")
        self.assertEqual([t["name"] for t in tools], ["speech_transcribe", "speech_engines", "speech_voices", "speech_synthesize",
                                                 "speech_voice_clone", "speech_voice_remove", "media_search", "media_fetch",
                                                 "scene_render", "image_engines", "image_generate", "music_fit",
                                                 "music_beats", "audio_master", "sfx_make"])
        self.assertTrue(call["isError"])
        self.assertIn("cannot start Concat", call["content"][0]["text"])

    def test_bridge_from_env_without_binary_is_speech_only(self):
        self.assertIsNone(bridge_from_env({}))

    def test_bridge_from_env_passes_mode_to_concat(self):
        bridge = bridge_from_env({"CONCAT_BIN": "/opt/concat", "CONCAT_MCP_MODE": "headless"})

        self.assertEqual(bridge.command, ["/opt/concat", "--mcp", "headless"])

    def test_bridge_closed_bridge_raises_bridge_error_not_crash(self):
        bridge = ConcatBridge(["/nonexistent/concat"])

        with self.assertRaises(BridgeError):
            bridge.call("echo", {})


if __name__ == "__main__":
    unittest.main()
