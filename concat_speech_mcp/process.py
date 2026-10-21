"""Running the engines (ffmpeg, whisper-cli, say) with a reason on failure.

A bare `check=True` failure says only "returned non-zero exit status 1";
the agent needs ffmpeg's own words ("does not contain any stream") to fix
its call. stdin is closed unless text is passed, so a child never reads the
MCP stream, and every call has a time limit: the server answers one request
at a time, and a hung engine must not hang it.
"""
import subprocess


class EngineError(RuntimeError):
    pass


def run_checked(cmd, run=subprocess.run, timeout=600, input=None):
    """Runs `cmd`; returns the CompletedProcess, or raises EngineError with stderr."""
    kwargs = {"capture_output": True, "text": True, "timeout": timeout}
    if input is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input
    try:
        result = run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        raise EngineError(f"{cmd[0]} took longer than {timeout}s and was stopped") from None
    except FileNotFoundError:
        raise EngineError(f"{cmd[0]} is not installed or not on PATH") from None
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[-500:] or f"exit status {result.returncode}"
        raise EngineError(f"{cmd[0]} failed: {detail}")
    return result
