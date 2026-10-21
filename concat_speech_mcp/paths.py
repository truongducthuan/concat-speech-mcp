"""Where the server may read and write.

Like Concat's own MCP server, files are written only under the user's home
folder, plus any folders listed in CONCAT_SPEECH_ROOTS (os.pathsep-separated).
"""
import os
from pathlib import Path


class PathError(ValueError):
    pass


def allowed_roots(env=None):
    env = os.environ if env is None else env
    roots = [Path.home()]
    roots += [Path(p) for p in env.get("CONCAT_SPEECH_ROOTS", "").split(os.pathsep) if p]
    return [r.expanduser().resolve() for r in roots]


def existing_file(path):
    """An absolute path to a file that exists."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise PathError(f"give an absolute path, not {path!r}")
    if not p.is_file():
        raise PathError(f"no such file: {p}")
    return p.resolve()


def writable_file(path, suffixes, roots=None):
    """An absolute output path under an allowed root, with one of `suffixes`.

    Its folder is created when missing.
    """
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise PathError(f"give an absolute path, not {path!r}")
    resolved = p.resolve()
    if resolved.suffix.lower() not in suffixes:
        raise PathError(f"{p.name}: the output must end in one of {', '.join(suffixes)}")
    roots = allowed_roots() if roots is None else roots
    if not any(resolved == r or r in resolved.parents for r in roots):
        raise PathError(f"{resolved} is outside the folders this server may write: "
                        f"{', '.join(map(str, roots))} (add more with CONCAT_SPEECH_ROOTS)")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
