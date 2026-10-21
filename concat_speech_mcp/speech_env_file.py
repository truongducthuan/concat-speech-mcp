"""The speech settings file: which engine to use and the API keys engines need.

The repository's .env (or CONCAT_SPEECH_ENV_FILE) holds KEY=VALUE lines, like a
web app's: copy .env.example, or run setup_speech.py. Git ignores it. It is
read again before every speech tool call, so choosing another engine or
adding a key takes effect without restarting the server. Only the variables the caller allows (the engine choice and the
engines' key names) are taken from it. A non-empty variable in the server's
real environment (the MCP registration's -e) wins over the file; a line
removed from the file is gone on the next call. A file that cannot be read
keeps the last good settings and says why on stderr, so a typo never blocks
transcription or the macos engine.
"""
import os
import stat
import sys
from pathlib import Path

PATH_VARIABLE = "CONCAT_SPEECH_ENV_FILE"
# Beside server.py, not the working directory: Claude Code starts the server from the workspace.
DEFAULT_PATH = Path(__file__).resolve().parent.parent / ".env"

_REAL_ENVIRONMENT = frozenset(k for k, v in os.environ.items() if v.strip())  # what the server was started with
_from_file = set()  # variables the last good read put into os.environ
_warned = set()  # (path, reason) already reported, so a problem is said once, not on every call


class SettingsError(OSError):
    pass


def settings_path(env=None):
    env = os.environ if env is None else env
    return Path(env.get(PATH_VARIABLE) or DEFAULT_PATH).expanduser()


def parse(text):
    """{KEY: VALUE} from KEY=VALUE lines; `#` comments, `export ` and quotes allowed."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def warn_once(path, reason):
    if (str(path), reason) not in _warned:
        _warned.add((str(path), reason))
        print(f"concat-speech: {path}: {reason}", file=sys.stderr)


def read(path):
    """The file's settings, {} when it does not exist. Raises SettingsError when it cannot be used."""
    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise SettingsError("other users can change this file, so it is ignored; run chmod 600 on it")
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except UnicodeDecodeError:
        raise SettingsError("not UTF-8 text; rewrite it with setup_speech.py") from None
    except SettingsError:
        raise
    except OSError as failure:
        raise SettingsError(f"cannot be read ({failure.strerror or failure}); check its permissions") from None
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        warn_once(path, "other users can read this file (it may hold API keys); run chmod 600 on it")
    return parse(text)


def apply(allowed, environ=None, real=None, path=None):
    """Brings the `allowed` variables of `environ` (os.environ) in line with the file."""
    environ = os.environ if environ is None else environ
    real = _REAL_ENVIRONMENT if real is None else real
    path = path or settings_path(environ)
    try:
        values = {k: v for k, v in read(path).items() if k in allowed}
    except SettingsError as problem:
        warn_once(path, f"{problem}; keeping the previous settings")
        return None
    for key in _from_file - set(values):
        environ.pop(key, None)
    _from_file.clear()
    for key, value in values.items():
        if key not in real:
            environ[key] = value
            _from_file.add(key)
    return values
