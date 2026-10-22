"""MCP over Streamable HTTP, so another machine's Claude Code can use this server.

One endpoint, /mcp: POST carries one JSON-RPC message and gets its answer as
application/json; DELETE ends a session; GET is refused (no server-initiated
stream is offered). Each client gets its own session, minted at initialize and
named by the Mcp-Session-Id header, with its own Concat behind it - as a stdio
client has - and its calls answered one at a time.

Every request must carry `Authorization: Bearer <CONCAT_MCP_TOKEN>`. A request
with an Origin header is refused unless that origin is allowed, so a web page
the user visits cannot drive the server. It listens on 127.0.0.1 unless told
otherwise.
"""
import hmac
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .protocol import INTERNAL_ERROR, INVALID_REQUEST, PARSE_ERROR, error, handle

ENDPOINT = "/mcp"
MAX_BODY = 1_000_000  # one tool call's arguments; media travels as file paths, not bytes
MAX_SESSIONS = 8  # each session may run its own Concat
SESSION_IDLE = 4 * 3600
MIN_TOKEN = 16


class Session:
    def __init__(self, bridge):
        self.bridge = bridge
        self.lock = threading.Lock()
        self.last_seen = time.monotonic()
        self.closed = False

    def close(self):
        if self.bridge is not None:
            self.bridge.close()

    def retire(self):
        """Ends the session without cutting a call in flight: Concat stops once that call is answered,
        and calls still queued behind it are refused (`closed`) rather than starting a new Concat."""
        self.closed = True

        def close_when_idle():
            with self.lock:
                self.close()

        threading.Thread(target=close_when_idle, daemon=True).start()


class McpHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token, bridge_factory, allowed_origins=()):
        if len(token or "") < MIN_TOKEN:
            raise ValueError(f"CONCAT_MCP_TOKEN must be at least {MIN_TOKEN} characters")
        super().__init__(address, McpRequestHandler)
        self.token = token.encode("utf-8")
        self.bridge_factory = bridge_factory
        self.allowed_origins = set(allowed_origins)
        self.sessions = {}
        self.sessions_lock = threading.Lock()

    def open_session(self):
        """A new session's id, or None when every slot is busy with a call.

        A client that restarts without DELETE leaves its session behind, so when
        every slot is taken the least recently used idle one makes room."""
        with self.sessions_lock:
            now = time.monotonic()
            for stale in [k for k, s in self.sessions.items() if now - s.last_seen > SESSION_IDLE]:
                self.sessions.pop(stale).retire()
            if len(self.sessions) >= MAX_SESSIONS:
                idle = [k for k, s in self.sessions.items() if not s.lock.locked()]
                if not idle:
                    return None
                self.sessions.pop(min(idle, key=lambda k: self.sessions[k].last_seen)).retire()
            session_id = secrets.token_urlsafe(24)
            self.sessions[session_id] = Session(self.bridge_factory())
            return session_id

    def close_session(self, session_id):
        with self.sessions_lock:
            session = self.sessions.pop(session_id, None)
        if session is not None:
            session.retire()
        return session is not None

    def server_close(self):
        super().server_close()
        with self.sessions_lock:
            sessions, self.sessions = list(self.sessions.values()), {}
        for session in sessions:
            session.close()


class McpRequestHandler(BaseHTTPRequestHandler):
    server_version = "concat-speech-mcp"
    timeout = 30  # a peer that connects and sends nothing does not hold a thread forever

    def log_message(self, fmt, *args):  # requests to stderr; headers (the token) never logged
        print(f"concat-speech http: {self.address_string()} {fmt % args}", file=sys.stderr)

    def do_GET(self):
        if self._admitted():
            self._send(405, headers={"Allow": "POST, DELETE"})

    def do_DELETE(self):
        if self._admitted():
            closed = self.server.close_session(self.headers.get("Mcp-Session-Id", ""))
            self._send(204 if closed else 404)

    def do_POST(self):
        if not self._admitted():
            return
        length = self.headers.get("Content-Length")
        if length is None or not (length.isascii() and length.isdigit()):
            return self._send(411)
        if int(length) > MAX_BODY:
            return self._send(413)
        try:
            message = json.loads(self.rfile.read(int(length)))
        except ValueError:
            return self._send_json(400, error(None, PARSE_ERROR, "parse error"))
        if not isinstance(message, dict):
            return self._send_json(400, error(None, INVALID_REQUEST, "send one JSON-RPC message per request"))
        headers = {}
        if message.get("method") == "initialize":
            session_id = self.server.open_session()
            if session_id is None:
                return self._send_json(503, error(message.get("id"), INTERNAL_ERROR, "too many sessions"))
            headers["Mcp-Session-Id"] = session_id
        else:
            session_id = self.headers.get("Mcp-Session-Id")
            if not session_id:
                return self._send_json(400, error(message.get("id"), INVALID_REQUEST, "missing Mcp-Session-Id"))
        session = self.server.sessions.get(session_id)
        if session is None:  # ended or expired: the client starts again with initialize
            return self._send_json(404, error(message.get("id"), INVALID_REQUEST, "unknown session"))
        with session.lock:
            if session.closed:  # ended while this call waited its turn
                return self._send_json(404, error(message.get("id"), INVALID_REQUEST, "unknown session"))
            session.last_seen = time.monotonic()
            try:
                response = handle(message, bridge=session.bridge)
            except Exception as failure:  # one bad message must never take the server down
                print(f"concat-speech http: internal error: {failure!r}", file=sys.stderr)
                response = error(message.get("id"), INTERNAL_ERROR, "internal error")
        if response is None:  # a notification or a response from the client
            return self._send(202, headers=headers)
        self._send_json(200, response, headers)

    def _admitted(self):
        """Checks path, origin and token; answers and returns False when one fails."""
        if self.path.split("?", 1)[0] != ENDPOINT:
            self._send(404)
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.allowed_origins:
            self._send(403)
            return False
        scheme, _, presented = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(presented.strip().encode("utf-8"), self.server.token):
            self._send(401, headers={"WWW-Authenticate": 'Bearer realm="concat-speech-mcp"'})
            return False
        return True

    def _send(self, status, body=b"", headers=None, content_type=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_json(self, status, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, headers, "application/json")


def serve_http(host, port, token, bridge_factory, allowed_origins=()):
    server = McpHttpServer((host, port), token, bridge_factory, allowed_origins)
    print(f"concat-speech: MCP over HTTP at http://{host}:{server.server_address[1]}{ENDPOINT}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()  # takes every session's Concat with it
