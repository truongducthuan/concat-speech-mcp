#!/usr/bin/env python3
"""Entry point: `python3 server.py` speaks MCP on stdin/stdout.

Register with Claude Code, Concat's tools included (one server for the whole edit):
    claude mcp add -s user concat -e CONCAT_BIN=/abs/path/concat -- python3 /abs/path/server.py
Without CONCAT_BIN it offers the speech tools only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from concat_speech_mcp.protocol import bridge_from_env, serve  # noqa: E402

if __name__ == "__main__":
    serve(bridge=bridge_from_env())
