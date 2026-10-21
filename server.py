#!/usr/bin/env python3
"""Entry point: `python3 server.py` speaks MCP on stdin/stdout.

Register with Claude Code:
    claude mcp add -s user concat-speech -- python3 /abs/path/server.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from concat_speech_mcp.protocol import serve  # noqa: E402

if __name__ == "__main__":
    serve()
