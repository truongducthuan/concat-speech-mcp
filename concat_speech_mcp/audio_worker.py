"""Beat tracking worker: runs in the TTS venv (python -I), where librosa is installed.

    audio_worker.py beats <file> <start> <duration|0>   -> JSON {tempo, beats, downbeats} on stdout

Times are seconds from <start> in the file, i.e. from where the music starts
on the timeline when it is placed from that point. Downbeats are every fourth
beat, from the phase whose beats are loudest: a good guess for 4/4 music.
"""
import json
import sys


def beats(path, start, duration):
    import librosa
    import numpy as np

    audio, rate = librosa.load(path, sr=22050, mono=True, offset=start, duration=duration or None)
    onset = librosa.onset.onset_strength(y=audio, sr=rate)
    tempo, frames = librosa.beat.beat_track(onset_envelope=onset, sr=rate)
    times = librosa.frames_to_time(frames, sr=rate)
    strength = onset[frames] if len(frames) else np.array([])
    phase = int(np.argmax([strength[p::4].mean() if len(strength[p::4]) else 0 for p in range(4)])) if len(frames) else 0
    tempo = float(np.atleast_1d(tempo)[0])
    return {"tempo": round(tempo, 1), "beats": [round(float(t), 3) for t in times],
            "downbeats": [round(float(t), 3) for t in times[phase::4]]}


def main():
    real_stdout, sys.stdout = sys.stdout, sys.stderr
    try:
        _, command, path, start, duration = sys.argv
        reply = beats(path, float(start), float(duration))
    except Exception as failure:
        reply = {"error": f"{type(failure).__name__}: {failure}"[:500]}
    real_stdout.write(json.dumps(reply) + "\n")


if __name__ == "__main__":
    main()
