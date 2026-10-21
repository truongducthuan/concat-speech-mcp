"""A stand-in for `concat --mcp`, for the bridge tests: real process, real pipes, scripted answers.

Tools: `echo` (returns its arguments), `frame` (image content), `crash`
(exits the process), `stall` (never answers), `garbage` (a non-UTF-8 line,
then the answer), `ask` (pings the client first and answers with the reply),
`orphan` (exits, leaving a process that holds stdout open). A notification is
sent before every answer, as a real server may. Each start appends a line to
the file named by FAKE_CONCAT_STARTS, so tests can count restarts.
"""
import json
import os
import subprocess
import sys

NAMES = ("echo", "frame", "crash", "stall", "garbage", "ask", "orphan")
TOOLS = [{"name": n, "inputSchema": {"type": "object"}} for n in NAMES]

if os.environ.get("FAKE_CONCAT_STARTS"):
    with open(os.environ["FAKE_CONCAT_STARTS"], "a") as starts:
        starts.write("start\n")


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    request_id, method, params = message["id"], message["method"], message.get("params", {})
    send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "noise"}})
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-concat"}, "instructions": "FAKE CONCAT INSTRUCTIONS"}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params["name"]
        if name == "echo":
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": json.dumps(params["arguments"])}], "isError": False}})
        elif name == "frame":
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"}]}})
        elif name == "crash":
            sys.exit(3)
        elif name == "stall":
            pass
        elif name == "garbage":
            sys.stdout.buffer.write(b"\xff\xfe not utf-8\n")
            sys.stdout.buffer.flush()
            send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": "after"}]}})
        elif name == "ask":
            send({"jsonrpc": "2.0", "id": "srv-1", "method": "ping"})
            answer = json.loads(sys.stdin.readline())
            send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(answer)}]}})
        elif name == "orphan":
            subprocess.Popen(["sleep", "8"], stdout=sys.stdout, stderr=subprocess.DEVNULL)
            sys.exit(4)
        else:
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": f"Unknown tool: {name}"}})
