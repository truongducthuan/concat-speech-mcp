"""The MCP server loop: JSON-RPC 2.0, one message per line on stdin/stdout.

Only what a tools-only server needs: initialize, ping, tools/list and
tools/call. stdout carries protocol messages and nothing else; diagnostics go
to stderr. A tool that fails answers with isError and the reason, as MCP
asks, so the agent can read it and correct itself; malformed requests get
JSON-RPC errors.

With CONCAT_BIN set, Concat's own MCP server runs behind this one
(concat_bridge) and its tools are offered here too: one registration for the
whole edit. Without it, only the speech tools.
"""
import json
import os
import sys
import traceback

from . import __version__
from .concat_bridge import BridgeError, BridgeRpcError, ConcatBridge
from .paths import PathError
from .process import EngineError
from .synthesize import SynthesizeError
from .tools import TOOLS, call_tool
from .transcribe import TranscribeError

EXPECTED_ERRORS = (PathError, SynthesizeError, TranscribeError, EngineError, ValueError)
# Past this, a result is sent as text only: structuredContent would double a
# payload that is already near what a client accepts from one tool call.
STRUCTURED_LIMIT = 20000

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Speech tools to use beside Concat's own MCP server (concat): speech_transcribe turns a video's speech into "
    "timed utterances for captions and cut decisions; speech_voices and speech_synthesize make voice-over .wav "
    "files to import and place with Concat's media_import and clip_add."
)
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


def negotiate(requested):
    """The client's protocol version when we speak it, else our newest."""
    return requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]


def tool_result(payload, is_error=False):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if not is_error and isinstance(payload, dict) and len(text) <= STRUCTURED_LIMIT:
        result["structuredContent"] = payload
    return result


def bridge_from_env(env=os.environ):
    """Concat's MCP server behind this one when CONCAT_BIN names its binary, else None."""
    binary = env.get("CONCAT_BIN")
    if not binary:
        return None
    mode = env.get("CONCAT_MCP_MODE")  # auto | window | headless; Concat's default when unset
    return ConcatBridge([binary, "--mcp"] + ([mode] if mode else []))


def concat_tools(bridge):
    """Concat's tools, or none (logged) when it cannot be reached: the speech tools still work."""
    if bridge is None:
        return []
    try:
        return bridge.tools()
    except (BridgeError, BridgeRpcError) as failure:
        print(f"concat-speech: Concat tools unavailable: {failure}", file=sys.stderr)
        return []


def handle(message, call=call_tool, bridge=None):
    """The response to one message, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "invalid request")
    if "id" not in message:
        return None  # notifications (initialized, cancelled...) need no answer
    request_id, method, params = message["id"], message["method"], message.get("params") or {}
    if not isinstance(params, dict):
        return error(request_id, INVALID_PARAMS, "params must be an object")
    if method == "initialize":
        version = negotiate(params.get("protocolVersion"))
        instructions = INSTRUCTIONS
        if bridge is not None:
            try:
                bridge.start(version)
                instructions = bridge.instructions + "\n\n" + INSTRUCTIONS
            except (BridgeError, BridgeRpcError) as failure:
                print(f"concat-speech: Concat did not start: {failure}", file=sys.stderr)
        return reply(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "concat-speech", "version": __version__},
            "instructions": instructions,
        })
    if method == "ping":
        return reply(request_id, {})
    if method == "tools/list":
        return reply(request_id, {"tools": TOOLS + concat_tools(bridge)})
    if method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments") or {}
        if not isinstance(name, str):
            return error(request_id, INVALID_PARAMS, f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            return error(request_id, INVALID_PARAMS, "arguments must be an object")
        if name not in {t["name"] for t in TOOLS}:
            if bridge is None:
                return error(request_id, INVALID_PARAMS, f"unknown tool: {name}")
            try:
                return reply(request_id, bridge.call(name, arguments))
            except BridgeRpcError as failure:  # Concat's own verdict, e.g. unknown tool
                return error(request_id, failure.code, str(failure))
            except BridgeError as failure:  # Concat down or stuck: say so, it restarts on the next call
                return reply(request_id, tool_result(str(failure), is_error=True))
        try:
            return reply(request_id, tool_result(call(name, arguments)))
        except KeyError as missing:
            return reply(request_id, tool_result(f"missing argument: {missing}", is_error=True))
        except EXPECTED_ERRORS as failure:  # bad input: the reason is the whole story
            return reply(request_id, tool_result(str(failure), is_error=True))
        except Exception as failure:  # the agent reads the reason and can retry differently
            traceback.print_exc(file=sys.stderr)
            return reply(request_id, tool_result(str(failure) or type(failure).__name__, is_error=True))
    return error(request_id, METHOD_NOT_FOUND, f"method not found: {method}")


def reply(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id, code, text):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": text}}


def serve(stdin=sys.stdin, stdout=sys.stdout, bridge=None):
    try:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                response = error(None, PARSE_ERROR, "parse error")
            else:
                try:
                    response = handle(message, bridge=bridge)
                except Exception:  # one bad message must never take the server down
                    traceback.print_exc(file=sys.stderr)
                    request_id = message.get("id") if isinstance(message, dict) else None
                    response = error(request_id, INTERNAL_ERROR, "internal error")
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()
    finally:
        if bridge is not None:
            bridge.close()  # the client went away: take Concat with us
