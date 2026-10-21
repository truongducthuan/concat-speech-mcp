import io
import json
import unittest

from concat_speech_mcp.paths import PathError
from concat_speech_mcp.protocol import handle, negotiate, serve


def request(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


class HandshakeTest(unittest.TestCase):
    def test_protocol_initialize_known_version_is_echoed(self):
        # Act
        response = handle(request("initialize", {"protocolVersion": "2025-06-18"}))

        # Assert
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "concat-speech")
        self.assertIn("tools", result["capabilities"])

    def test_protocol_negotiate_unknown_version_falls_back_to_newest(self):
        self.assertEqual(negotiate("1999-01-01"), "2025-11-25")

    def test_protocol_notification_gets_no_response(self):
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_protocol_ping_answers_empty_result(self):
        self.assertEqual(handle(request("ping"))["result"], {})


class ToolCallTest(unittest.TestCase):
    def test_protocol_tools_list_offers_the_three_speech_tools(self):
        tools = handle(request("tools/list"))["result"]["tools"]

        self.assertEqual([t["name"] for t in tools], ["speech_transcribe", "speech_voices", "speech_synthesize"])
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_protocol_tools_call_success_returns_text_and_structured_content(self):
        # Arrange
        fake = lambda name, args: {"voices": [{"name": "Linh"}]}

        # Act
        result = handle(request("tools/call", {"name": "speech_voices", "arguments": {}}), call=fake)["result"]

        # Assert
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"voices": [{"name": "Linh"}]})
        self.assertEqual(json.loads(result["content"][0]["text"]), {"voices": [{"name": "Linh"}]})

    def test_protocol_tools_call_bad_input_is_tool_error_not_rpc_error(self):
        def refuse(name, args):
            raise PathError("outside the folders this server may write")

        response = handle(request("tools/call", {"name": "speech_synthesize", "arguments": {}}), call=refuse)

        self.assertTrue(response["result"]["isError"])
        self.assertIn("outside", response["result"]["content"][0]["text"])

    def test_protocol_tools_call_missing_argument_names_it(self):
        def needs_file(name, args):
            return args["file"]

        result = handle(request("tools/call", {"name": "speech_transcribe", "arguments": {}}), call=needs_file)["result"]

        self.assertTrue(result["isError"])
        self.assertIn("file", result["content"][0]["text"])

    def test_protocol_tools_call_unknown_tool_is_invalid_params(self):
        response = handle(request("tools/call", {"name": "nope"}))

        self.assertEqual(response["error"]["code"], -32602)

    def test_protocol_unknown_method_is_method_not_found(self):
        self.assertEqual(handle(request("resources/list"))["error"]["code"], -32601)


class ServeLoopTest(unittest.TestCase):
    def test_serve_bad_json_line_answers_parse_error_and_keeps_going(self):
        # Arrange
        stdin = io.StringIO("not json\n\n" + json.dumps(request("ping", request_id=7)) + "\n")
        stdout = io.StringIO()

        # Act
        serve(stdin, stdout)

        # Assert
        lines = [json.loads(x) for x in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1], {"jsonrpc": "2.0", "id": 7, "result": {}})

    def test_serve_malformed_params_do_not_kill_the_server(self):
        # Regression (review M1): a list as params, or as a tool name, raised out of serve().
        # Arrange
        lines = [request("tools/call", request_id=1), request("ping", request_id=3)]
        lines[0]["params"] = [1]
        bad_name = request("tools/call", {"name": ["x"]}, request_id=2)
        stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in (lines[0], bad_name, lines[1])))
        stdout = io.StringIO()

        # Act
        serve(stdin, stdout)

        # Assert
        answers = [json.loads(x) for x in stdout.getvalue().splitlines()]
        self.assertEqual([a["error"]["code"] for a in answers[:2]], [-32602, -32602])
        self.assertEqual(answers[2]["result"], {})

    def test_serve_stdout_carries_only_json_rpc_lines(self):
        stdout = io.StringIO()

        serve(io.StringIO(json.dumps(request("tools/list")) + "\n"), stdout)

        for line in stdout.getvalue().splitlines():
            self.assertEqual(json.loads(line)["jsonrpc"], "2.0")

    def test_serve_non_object_message_is_invalid_request(self):
        stdout = io.StringIO()

        serve(io.StringIO("[1, 2]\n"), stdout)

        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main()
