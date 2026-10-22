import socket
from unittest import mock

from concat_speech_mcp import http_transport
from concat_speech_mcp.http_transport import McpHttpServer
from tests.test_http_transport import TOKEN, FakeBridge, HttpServerCase, initialize


class HttpAuthTest(HttpServerCase):
    def test_http_post_without_token_is_refused_401(self):
        status, headers, _ = self.post(initialize(), token=None)

        self.assertEqual(status, 401)
        self.assertIn("Bearer", headers["WWW-Authenticate"])
        self.assertEqual(self.bridges, [])

    def test_http_post_with_wrong_token_is_refused_401(self):
        status, _, _ = self.post(initialize(), token="wrong-token-0123456789")

        self.assertEqual(status, 401)

    def test_http_foreign_origin_is_refused_403_even_with_token(self):
        status, _, _ = self.post(initialize(), origin="http://evil.test")

        self.assertEqual(status, 403)
        self.assertEqual(self.bridges, [])

    def test_http_allowed_origin_is_served(self):
        status, _, _ = self.post(initialize(), origin="http://allowed.test")

        self.assertEqual(status, 200)

    def test_http_short_token_is_refused_at_start(self):
        with self.assertRaisesRegex(ValueError, "at least 16 characters"):
            McpHttpServer(("127.0.0.1", 0), "short", FakeBridge)


class HttpRequestShapeTest(HttpServerCase):
    def test_http_oversized_body_is_refused_413(self):
        with mock.patch.object(http_transport, "MAX_BODY", 10):
            status, _, _ = self.post(initialize())

        self.assertEqual(status, 413)

    def test_http_malformed_json_gets_parse_error_400(self):
        status, _, body = self.post(None, raw=b"{not json")

        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], -32700)

    def test_http_batch_array_is_refused_400(self):
        status, _, _ = self.post([initialize()])

        self.assertEqual(status, 400)

    def test_http_get_is_refused_405(self):
        status, headers, _ = self.send("GET", "/mcp", headers={"Authorization": f"Bearer {TOKEN}"})

        self.assertEqual(status, 405)
        self.assertIn("POST", headers["Allow"])

    def test_http_other_path_is_404(self):
        status, _, _ = self.post(initialize(), path="/other")

        self.assertEqual(status, 404)

    def test_http_post_without_a_plain_content_length_is_refused_411(self):
        word, _, _ = self.send("POST", "/mcp", headers={"Authorization": f"Bearer {TOKEN}", "Content-Length": "ten"})
        superscript, _, _ = self.send("POST", "/mcp", headers={"Authorization": f"Bearer {TOKEN}", "Content-Length": "\u00b2"})

        self.assertEqual((word, superscript), (411, 411))

    def test_http_delete_and_get_without_token_are_refused_401(self):
        deleted, _, _ = self.send("DELETE", "/mcp", headers={"Mcp-Session-Id": "x"})
        got, _, _ = self.send("GET", "/mcp")

        self.assertEqual((deleted, got), (401, 401))

    def test_http_peer_that_sends_nothing_is_dropped_after_timeout(self):
        with mock.patch.object(http_transport.McpRequestHandler, "timeout", 0.2):
            with socket.create_connection(self.server.server_address, timeout=5) as peer:
                dropped = peer.recv(1)  # the server closes the connection: b""

        self.assertEqual(dropped, b"")


if __name__ == "__main__":
    import unittest

    unittest.main()
