#!/usr/bin/env python3
"""Choose the default speech engine and enter its API key: `python3 setup_speech.py`.

Writes the repository's .env (or CONCAT_SPEECH_ENV_FILE), readable by you
only; git ignores it. The server reads it before every call, so no restart is needed. Keys are
typed hidden and never printed; Enter at the key prompt keeps the saved one.
Run it again to switch engine or add another engine's key.
"""
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from concat_speech_mcp import speech_env_file  # noqa: E402
from concat_speech_mcp.synthesize import ENGINE_VARIABLE, ENGINES  # noqa: E402

HEADER = "# concat-speech settings, written by setup_speech.py. Keep it private (chmod 600).\n"


def choose_engine(saved, ask, say):
    names = list(ENGINES)
    say("Speech engine to use by default:")
    for number, name in enumerate(names, 1):
        module = ENGINES[name]
        marks = []
        if saved.get(ENGINE_VARIABLE) == name:
            marks.append("default")
        if module.KEY_VARIABLE and saved.get(module.KEY_VARIABLE):
            marks.append("key saved")
        say(f"  {number}) {name:<7} {module.DESCRIPTION}" + (f"  [{', '.join(marks)}]" if marks else ""))
    while True:
        answer = ask(f"Number (1-{len(names)}, Enter to cancel): ").strip()
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        say("  Not one of the numbers above.")


def write_settings(path, values):
    """Replaces the file in one step: a private temp file beside it, then a rename.

    The server reads the file before every call; it never sees it half written,
    and the key never sits in a file others can read. A symlink is kept: its
    target is what gets replaced.
    """
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(HEADER + "".join(f"{key}={value}\n" for key, value in values.items()))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def main(ask=input, ask_secret=getpass.getpass, say=print, path=None):
    path = path or speech_env_file.settings_path()
    try:
        saved = speech_env_file.read(path)
    except speech_env_file.SettingsError as problem:
        say(f"{path}: {problem}. Starting from empty settings; saving replaces the file.")
        saved = {}
    engine = choose_engine(saved, ask, say)
    if engine is None:
        say("Cancelled; nothing changed.")
        return 1
    variable = ENGINES[engine].KEY_VARIABLE
    if variable:
        hint = "Enter keeps the saved key" if saved.get(variable) else "required"
        key = ask_secret(f"{variable} ({hint}, typing is hidden): ").strip()
        if key:
            saved[variable] = key
        elif not saved.get(variable):
            say(f"No key given; {engine} needs {variable}. Nothing changed.")
            return 1
    saved[ENGINE_VARIABLE] = engine
    write_settings(path, saved)
    say(f"Saved {path} (only you can read it). Default engine: {engine}. No restart needed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; nothing changed.")
        sys.exit(1)
