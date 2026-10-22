#!/usr/bin/env python3
"""Entry point: `python3 server.py` speaks MCP on stdin/stdout.

Register with Claude Code, Concat's tools included (one server for the whole edit):
    claude mcp add -s user concat -e CONCAT_BIN=/abs/path/concat -- python3 /abs/path/server.py
Without CONCAT_BIN it offers the speech tools only.

`--http` serves other machines instead (Streamable HTTP, bearer token in
CONCAT_MCP_TOKEN): see the README.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from concat_speech_mcp.protocol import bridge_from_env, serve  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="concat-speech MCP server")
    parser.add_argument("--http", action="store_true", help="serve MCP over HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (0.0.0.0 for the local network)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not args.http:
        return serve(bridge=bridge_from_env())
    from concat_speech_mcp.http_transport import serve_http

    origins = [o.strip() for o in os.environ.get("CONCAT_MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    try:
        serve_http(args.host, args.port, os.environ.get("CONCAT_MCP_TOKEN", ""), bridge_from_env, origins)
    except ValueError as problem:
        sys.exit(f"concat-speech: {problem}. Make one: export CONCAT_MCP_TOKEN=$(python3 -c "
                 "'import secrets; print(secrets.token_urlsafe(32))')")
    except OSError as problem:
        sys.exit(f"concat-speech: cannot listen on {args.host}:{args.port}: {problem}")


if __name__ == "__main__":
    main()
