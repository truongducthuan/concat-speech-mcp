"""HTTP for the media tools: JSON in and out, downloads, with reasons on failure.

Every call has a time limit (the server answers one request at a time) and
any API key given is scrubbed from the errors passed back to the agent.
"""
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .process import EngineError

USER_AGENT = "concat-speech-mcp/1.0 (local video tool; https://github.com/thuan-td)"
TIMEOUT = 60
MAX_DOWNLOAD = 500 * 1024 * 1024


def _open(request, what, secret, urlopen, timeout):
    try:
        return urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as failure:
        detail = _error_text(failure) or failure.reason
        if failure.headers.get("cf-mitigated") == "challenge" or "<title>Just a moment" in str(detail):
            raise EngineError(f"{what} is behind a Cloudflare bot check that blocks this network for now (not a key "
                              f"problem: the same request works in a browser). Try again later or from another "
                              f"network, and use the other sources meanwhile") from None
        raise EngineError(f"{what} refused the request ({failure.code}): {_scrub(detail, secret)}") from None
    except (urllib.error.URLError, socket.timeout, OSError) as failure:
        reason = getattr(failure, "reason", None) or failure
        raise EngineError(f"could not reach {what}: {_scrub(reason, secret)}") from None


def _error_text(failure):
    try:
        body = failure.read().decode("utf-8", "replace")
    except OSError:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return body[:300] or None
    error = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(error, dict):
        return error.get("message") or json.dumps(error)[:300]
    return str(error)[:300]


def _scrub(text, secret):
    text = str(text)
    return text.replace(secret, "***") if secret else text


def get_json(url, params=None, headers=None, what="the service", secret=None,
             urlopen=urllib.request.urlopen, timeout=TIMEOUT):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with _open(request, what, secret, urlopen, timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post(url, body, headers=None, what="the service", secret=None, urlopen=urllib.request.urlopen, timeout=180):
    """POSTs `body` (dict → JSON, or bytes as is); returns the parsed JSON reply."""
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    base = {"User-Agent": USER_AGENT} if isinstance(body, bytes) else {"User-Agent": USER_AGENT,
                                                                       "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, method="POST", headers={**base, **(headers or {})})
    with _open(request, what, secret, urlopen, timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url, target, what="the download", headers=None, urlopen=urllib.request.urlopen, timeout=300):
    """Streams `url` into the file `target` (written whole or not at all); returns its size in bytes."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.part")
    size = 0
    try:
        with _open(request, what, None, urlopen, timeout) as response, open(part, "wb") as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise EngineError(f"{what} is larger than {MAX_DOWNLOAD >> 20} MB; pick a smaller one")
                out.write(chunk)
        if not size:
            raise EngineError(f"{what} came back empty")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
    return size


def multipart(fields, files):
    """(body, content type) of a multipart/form-data request: fields {name: str}, files [(name, filename, bytes, mime)]."""
    boundary = f"concat-speech-{uuid.uuid4().hex}"
    lines = []
    for name, value in fields.items():
        lines += [f"--{boundary}".encode(), f'Content-Disposition: form-data; name="{name}"'.encode(), b"",
                  str(value).encode("utf-8")]
    for name, filename, content, mime in files:
        lines += [f"--{boundary}".encode(),
                  f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode(),
                  f"Content-Type: {mime}".encode(), b"", content]
    lines += [f"--{boundary}--".encode(), b""]
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"
