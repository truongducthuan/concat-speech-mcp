"""The `macos` speech engine: the system voices of macOS (`say`).

Always available, offline and free, and it includes Japanese (Kyoko, ...) and
Vietnamese (Linh); the voices sound dated. Lines are read at `rate` words per
minute (`say -r`).
"""
import re
import subprocess

from .process import run_checked

VOICE_LINE = re.compile(r"^(?P<name>.+?)\s+(?P<locale>[a-z]{2,3}_[A-Z0-9]{2,3})\s+#\s?(?P<sample>.*)$")
DESCRIPTION = "macOS system voices: offline and free, dated sound"
KEY_VARIABLE = None
RAW_SUFFIX = ".aiff"
CHECKS_VOICE_FIRST = True  # listing is local and cheap; `say` alone would fall back to another voice
# Words per minute when no `rate` is given, by voice language. Measured: Linh
# reads ~175 on its own and sounds sluggish, 200 is brisker with tones still
# clear; Kyoko's own ~175 is left alone, as pushing it to 200 makes whisper
# mishear 京都.
DEFAULT_RATES = {"vi": 200}


def parse_voices(say_listing):
    """Voices from `say -v ?`: [{name, locale, language, sample}]."""
    voices = []
    for line in say_listing.splitlines():
        match = VOICE_LINE.match(line.rstrip())
        if match:
            locale = match["locale"]
            voices.append({"name": match["name"].strip(), "locale": locale,
                           "language": locale.split("_")[0], "sample": match["sample"].strip()})
    return voices


def list_voices(run=subprocess.run, fetch=None):
    return parse_voices(run_checked(["say", "-v", "?"], run=run, timeout=60).stdout)


def render(text, voice, raw, rate, run=subprocess.run, fetch=None):
    """Reads `text` in `voice` into the audio file `raw`."""
    rate_args = ["-r", str(rate)] if rate is not None else []
    # Text on stdin, so a line starting with "-" is never read as an option.
    run_checked(["say", "-v", voice, *rate_args, "-o", str(raw)], run=run, timeout=120, input=text)
