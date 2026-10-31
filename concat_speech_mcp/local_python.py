"""The Python that runs the local engines (edge, vieneu) and the scene renderer.

The server itself is stdlib only; edge-tts and VieNeu-TTS need packages, so
they live in a venv of their own (.venv-tts at the repository root, or the
interpreter named by CONCAT_SPEECH_PYTHON) and run as child processes of it.
"""
import os
import subprocess
from pathlib import Path

PYTHON_VARIABLE = "CONCAT_SPEECH_PYTHON"
REPO = Path(__file__).resolve().parent.parent
DEFAULT_PYTHON = REPO / ".venv-tts" / "bin" / "python"
INSTALL_HINT = (f"python3 -m venv {DEFAULT_PYTHON.parent.parent} && "
                f"{DEFAULT_PYTHON.parent / 'pip'} install edge-tts vieneu playwright")
_installed = set()  # (python, package) found once stay found; a missing one is looked for again


def interpreter(env=None):
    env = os.environ if env is None else env
    return Path(env.get(PYTHON_VARIABLE, "").strip() or DEFAULT_PYTHON).expanduser()


def missing(package, env=None, run=subprocess.run):
    """Why `package` cannot be used yet (with how to fix it), or None when it can."""
    python = interpreter(env)
    if (str(python), package) in _installed:
        return None
    if not python.is_file():
        return f"{python} does not exist: {INSTALL_HINT} (or set {PYTHON_VARIABLE})"
    probe = f"import importlib.util, sys; sys.exit(importlib.util.find_spec({package!r}) is None)"
    try:
        found = run([str(python), "-I", "-c", probe], stdin=subprocess.DEVNULL, capture_output=True,
                    timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        found = False
    if not found:
        return f"{package} is not installed in {python}: {python.parent / 'pip'} install {package}"
    _installed.add((str(python), package))
    return None


def worker_script(name):
    """A worker script beside this module; run with -I, so it imports nothing of ours."""
    return Path(__file__).resolve().parent / name
