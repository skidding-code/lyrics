"""Robot vocals: espeak-ng per lyric line, tempo-fit to its beat slot, placed on the grid,
mixed over the instrumental -> build/mix.wav

Voice concept (user request): classic robotic TTS, deliberately not human.
"""
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)
SR = 44100

FFMPEG = "ffmpeg"

# how each style speaks: (espeak speed wpm, pitch 0-99, amplitude 0-200, gain)
VOICES = {
    "intro": (150, 35, 180, 1.0),
    "verse": (175, 40, 190, 1.0),
    "hook": (160, 62, 200, 1.15),
    "bridge": (170, 50, 190, 1.05),
    "outro": (140, 30, 180, 0.95),
}


def speakable(text: str) -> str:
    t = text
    subs = {
        "CLAUDE.md": "claude dot M D",
        ".md": " dot M D",
        "/exit": "slash exit",
        "10x": "ten ex",
        "o3": "oh three",
        "PRs": "P Rs",
        "QuitGPT": "quit G P T",
        "LGTM": "L G T M",
        "MCP": "M C P",
        "GPT": "G P T",
        "CI": "C I",
        "VP": "V P",
        "&": " and ",
        "—": ", ",
        "…": "...",
        "5-eleven": "five eleven",
        "10-14": "ten to fourteen",
        "14,000": "fourteen thousand",
    }
    for k, v in subs.items():
        t = t.replace(k, v)
    return t


def espeak_line(text: str, wpm: int, pitch: int, amp: int) -> np.ndarray:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    subprocess.run(
        ["espeak-ng", "-v", "en-us+m3", "-s", str(wpm), "-p", str(pitch), "-a", str(amp), "-w", wav_path, text],
        check=True,
        capture_output=True,
    )
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", wav_path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True,
        check=True,
    ).stdout
    Path(wav_path).unlink()
    return np.frombuffer(raw, dtype=np.float32)


def tempo_fit(y: np.ndarray, target_sec: float) -> np.ndarray:
    """Fit clip into target_sec using ffmpeg atempo (chained for >2x)."""
    cur = len(y) / SR
    if cur <= target_sec:
        return y
    speed = cur / target_sec
    stages = []
    while speed > 2.0:
        stages.append(2.0)
        speed /= 2.0
    stages.append(speed)
    flt = ",".join(f"atempo={s:.5f}" for s in stages)
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-af", flt, "-f", "f32le", "-"],
        input=y.tobytes(),
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def main() -> None:
    timing = json.loads((ROOT / "timing.json").read_text())
    analysis = json.loads((ROOT / "analysis.json").read_text())
    total = int((analysis["duration_sec"] + 1) * SR)
    track = np.zeros(total, dtype=np.float32)

    for ev in timing["events"]:
        wpm, pitch, amp, gain = VOICES[ev["style"]]
        text = speakable(ev["tts"])
        if not text:
            continue
        y = espeak_line(text, wpm, pitch, amp)
        slot = (ev["end"] - ev["start"]) * 0.96
        y = tempo_fit(y, slot)
        start = int(ev["start"] * SR)
        end = min(start + len(y), total)
        track[start:end] += y[: end - start] * gain

    peak = np.abs(track).max()
    if peak > 0:
        track = track / peak * 0.9
    pcm = (track * 32767).astype(np.int16)
    vocals = BUILD / "vocals.wav"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", str(vocals)],
        input=pcm.tobytes(),
        check=True,
    )
    # mix in numpy: soft-clipped loud vocals, instrumental ducked by an explicit
    # vocal-activity envelope. Deterministic and measurable.
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(ROOT / "audio" / "instrumental.mp3"),
         "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True, check=True,
    ).stdout
    inst = np.frombuffer(raw, dtype=np.float32).copy()
    n = min(len(inst), len(track))
    inst, voc = inst[:n], track[:n].copy()

    # vocal bus: drive into tanh soft clip -> high RMS, robot grit; slap echo
    voc = np.tanh(voc * 5.0) * 0.55
    echo = int(0.060 * SR)
    voc[echo:] += 0.22 * voc[:-echo]

    # duck envelope from vocal activity (attack/release smoothing ~80ms)
    act = np.abs(voc)
    win = int(0.080 * SR)
    kernel = np.ones(win, dtype=np.float32) / win
    env = np.convolve(act, kernel, mode="same")
    duck = 1.0 - 0.60 * np.clip(env / 0.06, 0, 1)

    mix = inst * 0.55 * duck + voc
    mix = np.tanh(mix * 1.1) * 0.92  # gentle master saturation/limit
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
         str(BUILD / "mix.wav")],
        input=pcm.tobytes(), check=True,
    )
    print("wrote", vocals, "and", BUILD / "mix.wav")


if __name__ == "__main__":
    main()
