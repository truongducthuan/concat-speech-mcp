"""The MCP server loop: JSON-RPC 2.0, one message per line on stdin/stdout.

Only what a tools-only server needs: initialize, ping, tools/list and
tools/call. stdout carries protocol messages and nothing else; diagnostics go
to stderr. A tool that fails answers with isError and the reason, as MCP
asks, so the agent can read it and correct itself; malformed requests get
JSON-RPC errors.
"""
import json
import sys
import traceback

from . import __version__
from .paths import PathError
from .synthesize import SynthesizeError
from .tools import TOOLS, call_tool
from .transcribe import TranscribeError

EXPECTED_ERRORS = (PathError, SynthesizeError, TranscribeError, ValueError)

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Speech tools to use beside Concat's own MCP server (concat): speech_transcribe turns a video's speech into "
    "timed utterances for captions and cut decisions; speech_voices and speech_synthesize make voice-over .wav "
    "files to import and place with Concat's media_import and clip_add."
)
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def negotiate(requested):
    """The client's protocol version when we speak it, else our newest."""
    return requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]


def tool_result(payload, is_error=False):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if not is_error and isinstance(payload, dict):
        result["structuredContent"] = payload
    return result


def handle(message, call=call_tool):
    """The response to one message, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "invalid request")
    if "id" not in message:
        return None  # notifications (initialized, cancelled...) need no answer
    request_id, method, params = message["id"], message["method"], message.get("params") or {}
    if method == "initialize":
        return reply(request_id, {
            "protocolVersion": negotiate(params.get("protocolVersion")),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "concat-speech", "version": __version__},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return reply(request_id, {})
    if method == "tools/list":
        return reply(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if name not in {t["name"] for t in TOOLS}:
            return error(request_id, INVALID_PARAMS, f"unknown tool: {name}")
        try:
            return reply(request_id, tool_result(call(name, params.get("arguments") or {})))
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


def serve(stdin=sys.stdin, stdout=sys.stdout):
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = error(None, PARSE_ERROR, "parse error")
        else:
            response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
