"""music_fit, music_beats, audio_master and sfx_make: the sound side of an edit in Concat.

Concat places and mixes clips but has no ducking, beat detection or final
loudness pass over MCP; these fill that in with ffmpeg (and librosa for beats):

- music_fit: a music track made into a bed for the timeline: from `start` in
  the song, looped or cut to `duration`, levelled to `level` LUFS (−30 sits
  well under a voice), faded in and out, and lowered under the voice lines
  (sidechain ducking) when their files and timeline positions are given. The
  bed goes on its own lane at 0 s; the voice clips stay where they are.
- music_beats: beat and downbeat times, to cut scenes on the music.
- audio_master: an exported video's sound brought to the loudness the
  platforms expect (−14 LUFS, true peak −1.5 dB) in two passes, picture copied.
- sfx_make: short effects synthesised here (whoosh, riser, pop, click, tick,
  ding, impact): free, offline, no licence to credit.
"""
import json
import subprocess
from pathlib import Path

from . import local_python
from .paths import existing_file
from .process import EngineError, run_checked

SAMPLE_RATE = 48000
PLATFORM_LOUDNESS = -14.0
MAX_BED_SECONDS = 3600


class AudioError(ValueError):
    pass


def _duration(path, run):
    out = run_checked(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                      run=run, timeout=60).stdout.strip()
    return float(out or 0)


def music_fit(music, output, duration, start=0.0, level=-30.0, fade_in=1.0, fade_out=2.0, voices=(), duck=8.0,
              run=subprocess.run):
    """Writes the music bed `output` (.wav); returns what was made."""
    song = existing_file(music)
    duration, start = float(duration), float(start)
    if not 0 < duration <= MAX_BED_SECONDS:
        raise AudioError(f"duration must be more than 0 and at most {MAX_BED_SECONDS} s")
    if not -40 <= level <= -10:
        raise AudioError("level must be between -40 and -10 LUFS (-30 under a voice, -18 for music alone)")
    if fade_in < 0 or fade_out < 0 or fade_in + fade_out > duration:
        raise AudioError("fades must be 0 or more and fit in the duration together")
    if not 0 <= duck <= 24:
        raise AudioError("duck must be 0 (off) to 24 dB")
    length = _duration(song, run)
    if start >= length:
        raise AudioError(f"start {start:g} s is past the end of {song.name} ({length:.1f} s)")
    inputs = ["-ss", f"{start:.3f}", "-stream_loop", "-1", "-i", str(song)]
    graph = [f"[0:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
             f"loudnorm=I={level:g}:TP=-6:LRA=20,aresample={SAMPLE_RATE}"
             + (f",afade=t=in:d={fade_in:g}" if fade_in else "")
             + (f",afade=t=out:st={duration - fade_out:.3f}:d={fade_out:g}" if fade_out else "") + "[music]"]
    lines = []
    for index, voice in enumerate(voices or (), start=1):
        line = existing_file(voice["file"])
        at = float(voice.get("at", 0))
        if at < 0:
            raise AudioError("a voice's `at` must be 0 or more")
        inputs += ["-i", str(line)]
        graph.append(f"[{index}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
                     f"adelay={round(at * 1000)}:all=1[v{index}]")
        lines.append(f"[v{index}]")
    if lines and duck:
        # the voices only steer the compressor; they are not in the bed
        guide = (f"{''.join(lines)}amix=inputs={len(lines)}:duration=longest:normalize=0," if len(lines) > 1
                 else f"{lines[0]}anull,") + f"apad,atrim=0:{duration:.3f}[guide]"
        ratio = max(1.5, min(20.0, 10 ** (duck / 20) * 1.5))
        graph += [guide, f"[music][guide]sidechaincompress=threshold=0.02:ratio={ratio:.1f}:attack=30:release=500"
                         f":makeup=1[out]"]
    else:
        graph.append("[music]anull[out]")
    run_checked(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[out]",
                 "-t", f"{duration:.3f}", "-ar", str(SAMPLE_RATE), "-ac", "2", str(output)], run=run, timeout=600)
    return {"output": str(output), "duration": round(_duration(output, run), 3), "from": start, "level": level,
            "looped": duration > length - start, "ducked": bool(lines and duck), "voices": len(lines),
            "place": "own lane, at 0 s on the timeline, volume 1"}


def music_beats(music, start=0.0, duration=None, run=subprocess.run):
    song = existing_file(music)
    problem = local_python.missing("librosa")
    if problem:
        raise EngineError(f"beat detection not ready: {problem}")
    out = run_checked([str(local_python.interpreter()), "-I", str(local_python.worker_script("audio_worker.py")),
                       "beats", str(song), f"{float(start):.3f}", f"{float(duration or 0):.3f}"],
                      run=run, timeout=300)
    reply = json.loads(out.stdout.strip().splitlines()[-1])
    if "error" in reply:
        raise EngineError(f"beat detection: {reply['error']}")
    reply.update(file=str(song), start=float(start))
    return reply


def _measure(video, target, run):
    out = run_checked(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-map", "0:a:0",
                       "-af", f"loudnorm=I={target:g}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                      run=run, timeout=900).stderr
    try:
        return json.loads(out[out.rindex("{"):out.rindex("}") + 1])
    except ValueError:
        raise EngineError("could not measure the loudness: is there an audio track?") from None


def audio_master(video, output, target=PLATFORM_LOUDNESS, run=subprocess.run):
    """Brings `video`'s sound to `target` LUFS into `output`, picture copied as is."""
    source = existing_file(video)
    if not -24 <= target <= -9:
        raise AudioError("target must be between -24 and -9 LUFS (-14 for YouTube, TikTok, Reels)")
    if Path(output).resolve() == source:
        raise AudioError("write the mastered video to a new file, not over its source")
    m = _measure(source, target, run)
    measured = (f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}")
    run_checked(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:v?", "-map", "0:a:0", "-c:v", "copy",
                 "-af", f"loudnorm=I={target:g}:TP=-1.5:LRA=11:{measured}:linear=true,aresample={SAMPLE_RATE}",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)], run=run, timeout=1800)
    after = _measure(output, target, run)
    return {"output": str(output), "before": {"lufs": float(m["input_i"]), "truePeak": float(m["input_tp"])},
            "after": {"lufs": float(after["input_i"]), "truePeak": float(after["input_tp"])}, "target": target}


# Each effect: default seconds and an aevalsrc expression of t (and D, its length); all end in silence.
SFX = {
    "whoosh": (0.7, "0.9*(random(0)*2-1)*pow(sin(PI*t/D),3)", "highpass=f=400,lowpass=f=5000,bandreject=f=900:w=600"),
    "riser": (2.0, "0.35*sin(2*PI*(220*t+700*t*t/D))*(t/D)+0.5*(random(0)*2-1)*pow(t/D,2)", "highpass=f=200"),
    "pop": (0.15, "0.9*sin(2*PI*(700*t-1800*t*t))*exp(-30*t)", "highpass=f=120"),
    "click": (0.05, "0.9*(random(0)*2-1)*exp(-350*t)", "highpass=f=1500"),
    "tick": (0.06, "0.7*sin(2*PI*2400*t)*exp(-120*t)", "anull"),
    "ding": (1.6, "0.45*sin(2*PI*1318.5*t)*exp(-3.5*t)+0.2*sin(2*PI*2637*t)*exp(-6*t)+0.08*sin(2*PI*3955.5*t)*exp(-9*t)",
             "anull"),
    "impact": (1.4, "0.95*sin(2*PI*(75*t-25*t*t))*exp(-4.5*t)+0.5*(random(0)*2-1)*exp(-35*t)", "lowpass=f=3000"),
}


def sfx_make(kind, output, duration=None, run=subprocess.run):
    if kind not in SFX:
        raise AudioError(f"kind must be one of {', '.join(SFX)}")
    seconds, expression, shaping = SFX[kind]
    seconds = float(duration or seconds)
    if not 0.02 <= seconds <= 10:
        raise AudioError("duration must be 0.02-10 s")
    source = f"aevalsrc=exprs='{expression.replace('D', f'{seconds:g}')}':s={SAMPLE_RATE}:d={seconds:g}"
    run_checked(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-af",
                 f"{shaping},afade=t=out:st={seconds * 0.85:.3f}:d={seconds * 0.15:.3f},"
                 "alimiter=limit=0.7:level=false,aformat=channel_layouts=stereo",
                 "-ar", str(SAMPLE_RATE), str(output)], run=run, timeout=60)
    return {"output": str(output), "kind": kind, "duration": round(seconds, 3),
            "credit": "synthesised here: no licence, no credit needed"}
