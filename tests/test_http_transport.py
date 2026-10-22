import http.client
import json
import threading
import time
import unittest
from unittest import mock

from concat_speech_mcp import http_transport
from concat_speech_mcp.http_transport import McpHttpServer

TOKEN = "test-token-0123456789abcdef"


class FakeBridge:
    """Stands in for Concat's MCP server: one tool, and records whether it was closed."""

    instructions = "Concat instructions"

    def __init__(self):
        self.closed = False

    def start(self, protocol_version=None):
        pass

    def tools(self):
        return [{"name": "project_list", "inputSchema": {"type": "object"}}]

    def call(self, name, arguments):
        return {"content": [{"type": "text", "text": f"{name} ok"}], "isError": False}

    def close(self):
        self.closed = True


def wait_until(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def initialize(request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}


class HttpServerCase(unittest.TestCase):
    """A real server on a free loopback port, with fake Concat bridges."""

    def setUp(self):
        self.bridges = []

        def factory():
            self.bridges.append(FakeBridge())
            return self.bridges[-1]

        self.server = McpHttpServer(("127.0.0.1", 0), TOKEN, factory, allowed_origins={"http://allowed.test"})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def post(self, message, token=TOKEN, session=None, origin=None, path="/mcp", raw=None):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if session:
            headers["Mcp-Session-Id"] = session
        if origin:
            headers["Origin"] = origin
        return self.send("POST", path, raw if raw is not None else json.dumps(message).encode(), headers)

    def send(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, dict(response.getheaders()), json.loads(data) if data else None


class HttpSessionTest(HttpServerCase):
    def test_http_initialize_then_tools_list_offers_speech_and_concat_tools(self):
        # Arrange / Act
        status, headers, body = self.post(initialize())
        session = headers["Mcp-Session-Id"]
        _, _, tools = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session=session)

        # Assert
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["serverInfo"]["name"], "concat-speech")
        names = [t["name"] for t in tools["result"]["tools"]]
        self.assertIn("speech_synthesize", names)
        self.assertIn("project_list", names)

    def test_http_each_client_gets_its_own_session_and_concat(self):
        _, first, _ = self.post(initialize())
        _, second, _ = self.post(initialize())

        self.assertNotEqual(first["Mcp-Session-Id"], second["Mcp-Session-Id"])
        self.assertEqual(len(self.bridges), 2)

    def test_http_call_without_session_is_refused_400(self):
        status, _, body = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        self.assertEqual(status, 400)
        self.assertIn("Mcp-Session-Id", body["error"]["message"])

    def test_http_call_with_unknown_session_is_refused_404(self):
        status, _, _ = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session="no-such-session")

        self.assertEqual(status, 404)

    def test_http_notification_is_accepted_202_without_body(self):
        _, headers, _ = self.post(initialize())

        status, _, body = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                                    session=headers["Mcp-Session-Id"])

        self.assertEqual((status, body), (202, None))

    def test_http_delete_ends_session_and_closes_its_concat(self):
        # Arrange
        _, headers, _ = self.post(initialize())
        session = headers["Mcp-Session-Id"]

        # Act
        status, _, _ = self.send("DELETE", "/mcp", headers={"Authorization": f"Bearer {TOKEN}", "Mcp-Session-Id": session})
        after, _, _ = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session=session)

        # Assert
        self.assertEqual(status, 204)
        self.assertTrue(wait_until(lambda: self.bridges[0].closed))
        self.assertEqual(after, 404)

    def test_http_session_cap_ends_least_recently_used_idle_session(self):
        # Arrange: a client that restarted without DELETE left its session behind
        with mock.patch.object(http_transport, "MAX_SESSIONS", 1):
            _, old, _ = self.post(initialize())

            # Act
            status, _, _ = self.post(initialize())
        after, _, _ = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session=old["Mcp-Session-Id"])

        # Assert
        self.assertEqual((status, after), (200, 404))
        self.assertTrue(wait_until(lambda: self.bridges[0].closed))

    def test_http_session_cap_refuses_503_when_every_session_is_busy(self):
        with mock.patch.object(http_transport, "MAX_SESSIONS", 1):
            _, busy, _ = self.post(initialize())
            with self.server.sessions[busy["Mcp-Session-Id"]].lock:  # a call in flight
                status, _, _ = self.post(initialize())

        self.assertEqual(status, 503)
        self.assertEqual(len(self.bridges), 1)

    def test_http_delete_waits_for_call_in_flight_then_refuses_queued_call(self):
        # Arrange: a call holds the session while DELETE arrives
        _, headers, _ = self.post(initialize())
        session_id = headers["Mcp-Session-Id"]
        session = self.server.sessions[session_id]
        session.lock.acquire()

        # Act
        status, _, _ = self.send("DELETE", "/mcp", headers={"Authorization": f"Bearer {TOKEN}", "Mcp-Session-Id": session_id})
        closed_during_call = self.bridges[0].closed
        session.lock.release()

        # Assert: Concat stopped only after the call, and the session refuses what queued behind it
        self.assertEqual(status, 204)
        self.assertFalse(closed_during_call)
        self.assertTrue(wait_until(lambda: self.bridges[0].closed))
        self.assertTrue(session.closed)

    def test_http_server_close_closes_every_session_concat(self):
        self.post(initialize())
        self.post(initialize())

        self.server.server_close()

        self.assertTrue(all(b.closed for b in self.bridges))


if __name__ == "__main__":
    unittest.main()
