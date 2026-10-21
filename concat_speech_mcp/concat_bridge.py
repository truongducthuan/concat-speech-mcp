"""Concat's own MCP server (`concat --mcp`), run as a child and spoken to over stdio.

This is what makes one registration enough: the server below starts Concat's
MCP server itself, offers its tools next to the speech ones, and passes each
call on unchanged - results, images and isError included - so the agent sees
the same tools it would see registering Concat directly.

The child is started at initialize (to merge its instructions) or on first
need, and started again after it dies or stops answering, so a crash or hang
in Concat costs one failed call, not the session. Calls are handled one at a
time, as Claude Code makes them: a long export_wait holds the server meanwhile.
"""
import json
import queue
import subprocess
import threading
import time

from . import __version__

START_TIMEOUT = 60
# Long enough for export_wait on a long video; the agent gets an error, not a hang, past it.
CALL_TIMEOUT = 1800
STOP_TIMEOUT = 5


class BridgeError(RuntimeError):
    """Concat could not be reached: not started, died, or did not answer."""


class BridgeRpcError(RuntimeError):
    """Concat answered with a JSON-RPC error (unknown tool, bad params); passed on as is."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ConcatBridge:
    def __init__(self, command, popen=subprocess.Popen, call_timeout=CALL_TIMEOUT, start_timeout=START_TIMEOUT):
        self.command = list(command)
        self.popen = popen
        self.call_timeout = call_timeout
        self.start_timeout = start_timeout
        self.proc = None
        self.pump = None
        self.lines = None
        self.next_id = 0
        self.protocol_version = "2025-06-18"
        self.instructions = ""
        self.tool_list = []

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, protocol_version=None):
        """Starts the child (if not running) and reads its instructions and tools."""
        if protocol_version:
            self.protocol_version = protocol_version
        if self.running():
            return
        self.close()  # a child that died: release its pipes before starting another
        try:
            # stderr inherited: Concat's logs land in the client's MCP log, never on our stdout.
            # errors="replace": one bad byte must not kill the reader and leave every call hanging.
            self.proc = self.popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                                   text=True, encoding="utf-8", errors="replace")
        except OSError as failure:
            raise BridgeError(f"cannot start Concat ({' '.join(self.command)}): {failure}") from failure
        # A reader thread owns stdout so a line already buffered is never stranded behind a timeout.
        self.lines = queue.Queue()
        self.pump = threading.Thread(target=self._pump, args=(self.proc, self.lines), daemon=True)
        self.pump.start()
        try:
            result = self._request("initialize", {
                "protocolVersion": self.protocol_version, "capabilities": {},
                "clientInfo": {"name": "concat-speech", "version": __version__},
            }, self.start_timeout)
            self.instructions = result.get("instructions") or ""
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self.tool_list = self._request("tools/list", {}, self.start_timeout).get("tools", [])
        except (BridgeError, BridgeRpcError):
            self.close()  # a half-started child would look running yet never be initialized
            raise

    def tools(self):
        self.start()
        return self.tool_list

    def call(self, name, arguments):
        """Concat's result for one tool call, unchanged."""
        self.start()
        try:
            return self._request("tools/call", {"name": name, "arguments": arguments}, self.call_timeout)
        except BridgeError:
            self.close()  # hung or gone: the next call starts a fresh Concat
            raise

    def close(self):
        """Stops the child; bounded in time even if it ignores end of input."""
        if self.proc is None:
            return
        proc, self.proc = self.proc, None
        try:
            proc.stdin.close()
        except OSError:
            pass  # already gone
        try:
            proc.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=STOP_TIMEOUT)
        # Close stdout only once the reader is done with it: closing under a blocked read can
        # itself block, if something the child left behind still holds the pipe open.
        self.pump.join(timeout=1)
        if not self.pump.is_alive():
            proc.stdout.close()

    @staticmethod
    def _pump(proc, lines):
        try:
            for line in proc.stdout:
                lines.put(line)
        except (OSError, ValueError):
            pass  # pipe closed under us: same as end of stream
        finally:
            lines.put(None)

    def _send(self, message):
        try:
            self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as failure:  # broken pipe, or stdin already closed
            raise BridgeError(f"Concat is not running: {failure}") from failure

    def _answer_child_request(self, message):
        """Concat may ask us something (ping); an unanswered request would leave it waiting."""
        if message["method"] == "ping":
            self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        else:
            self._send({"jsonrpc": "2.0", "id": message["id"],
                        "error": {"code": -32601, "message": f"not supported: {message['method']}"}})

    def _request(self, method, params, timeout):
        self.next_id += 1
        want = self.next_id
        self._send({"jsonrpc": "2.0", "id": want, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise BridgeError(f"Concat did not answer {method} within {timeout:g} s")
            try:
                line = self.lines.get(timeout=min(1.0, left))
            except queue.Empty:
                # A child that exited while something it started keeps the pipe open never sends EOF.
                if self.proc.poll() is not None:
                    self.pump.join(timeout=0.5)  # its last lines may still be on their way to the queue
                    if self.lines.empty():
                        raise BridgeError(f"Concat exited during {method} (exit code {self.proc.poll()})")
                continue
            if line is None:
                raise BridgeError(f"Concat exited during {method} (exit code {self.proc.poll()})")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message:
                if "id" in message:
                    self._answer_child_request(message)
                continue  # notifications need nothing
            if message.get("id") != want:
                continue  # a late answer to a request that timed out
            if "error" in message:
                failure = message["error"] or {}
                raise BridgeRpcError(failure.get("code", -32603), failure.get("message", "error"))
            return message.get("result") or {}
