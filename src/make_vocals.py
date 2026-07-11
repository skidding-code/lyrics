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


def trim_silence(y: np.ndarray, thr: float = 0.012) -> np.ndarray:
    idx = np.where(np.abs(y) > thr)[0]
    return y[idx[0]: idx[-1] + 1] if len(idx) else y


def detect_root_hz(inst: np.ndarray, sr: int = SR) -> float:
    """Strongest pitch class of the instrumental -> root of the autotune scale."""
    seg = inst[60 * sr: 120 * sr]
    mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    chroma = np.zeros(12)
    band = (freqs > 55) & (freqs < 1000)
    pc = (np.round(12 * np.log2(freqs[band] / 55.0)) % 12).astype(int)
    np.add.at(chroma, pc, mag[band] ** 2)
    k = int(chroma.argmax())
    return 55.0 * 2 ** (k / 12)  # root in the A1=55Hz octave


def scale_freqs_for(root: float) -> np.ndarray:
    """Minor pentatonic on the root, spread over the espeak vocal range (~70-300 Hz)."""
    semis = [0, 3, 5, 7, 10]
    notes = []
    for octave in (-1, 0, 1, 2):
        for s in semis:
            f = root * 2 ** (octave + s / 12)
            if 70 <= f <= 300:
                notes.append(f)
    return np.array(sorted(notes))


def autotune(y: np.ndarray, scale: np.ndarray, sr: int = SR) -> np.ndarray:
    """Hard frame-wise pitch quantization to the scale + vibrato.

    Resampling each frame (formants shift too) then overlap-adding at the
    original hop is exactly the cheap 'robot got autotuned' sound we want."""
    N, H = 2048, 512
    win = np.hanning(N).astype(np.float32)
    out = np.zeros(len(y) + N, dtype=np.float32)
    norm = np.zeros(len(y) + N, dtype=np.float32)
    lo, hi = int(sr / 300), int(sr / 70)
    for i in range(0, max(len(y) - N, 1), H):
        fr = y[i: i + N]
        if len(fr) < N:
            fr = np.pad(fr, (0, N - len(fr)))
        f = fr * win
        ac = np.correlate(f, f, "full")[N - 1:]
        seg = ac[lo:hi]
        voiced = ac[0] > 1e-6 and seg.max() > 0.22 * ac[0]
        if voiced:
            f0 = sr / (lo + int(seg.argmax()))
            target = scale[np.argmin(np.abs(np.log(scale / f0)))]
            vib = 1.0 + 0.014 * np.sin(2 * np.pi * 5.5 * i / sr)
            r = float(target * vib / f0)
            idx = np.arange(int(N * min(r, 2.5))) / r
            idx = idx[idx < N - 1]
            shifted = np.interp(idx, np.arange(N), fr).astype(np.float32)
            shifted = shifted[:N] if len(shifted) >= N else np.pad(shifted, (0, N - len(shifted)))
        else:
            shifted = fr
        out[i: i + N] += shifted * win
        norm[i: i + N] += win ** 2
    # floor the window-sum: dividing by the near-zero edges makes huge spikes,
    # and a single spike later crushes the whole track's peak normalization
    out /= np.maximum(norm, 0.25)
    out = out[: len(y)]
    rms_in = float(np.sqrt((y ** 2).mean())) or 1e-6
    rms_out = float(np.sqrt((out ** 2).mean())) or 1e-6
    out *= rms_in / rms_out
    return np.clip(out, -1.0, 1.0)


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

    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(ROOT / "audio" / "instrumental.mp3"),
         "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True, check=True,
    ).stdout
    inst_full = np.frombuffer(raw, dtype=np.float32)
    root = detect_root_hz(inst_full)
    scale = scale_freqs_for(root)
    print(f"autotune root {root:.1f} Hz, scale: {[round(f) for f in scale]}")

    import re as _re

    def countable_words(text: str) -> list:
        """Same tokenization the video's karaoke uses: split on spaces, skip
        adlibs '(...)' and punctuation-only tokens."""
        out = []
        for w in text.split(" "):
            if _re.match(r"^\(.*\)[,.!?…]*$", w):
                continue
            if not _re.search(r"[A-Za-z0-9]", w):
                continue
            out.append(w)
        return out

    for ev in timing["events"]:
        wpm, pitch, amp, gain = VOICES[ev["style"]]
        text = speakable(ev["tts"])
        if not text:
            continue
        y = trim_silence(espeak_line(text, wpm, pitch, amp))
        slot = (ev["end"] - ev["start"]) * 0.96
        pre_len = len(y)
        y = tempo_fit(y, slot)
        y = autotune(y, scale)
        start = int(ev["start"] * SR)
        end = min(start + len(y), total)
        track[start:end] += y[: end - start] * gain

        # word-level karaoke timing: synthesize each display word alone and use its
        # trimmed length as its share of the line. "Transcription" with zero guessing.
        words = countable_words(ev["text"])
        if words and pre_len:
            lens = []
            for w in words:
                clean = speakable(_re.sub(r"^[^\w]+|[^\w]+$", "", w) or w)
                wy = trim_silence(espeak_line(clean, wpm, pitch, amp))
                lens.append(max(len(wy), 1))
            cum = np.cumsum(lens) / sum(lens)
            ev["wf"] = [round(float(f), 4) for f in cum]
        ev["vdur"] = round(len(y) / SR, 3)

    # write word fractions + true vocal durations back for the renderer
    (ROOT / "timing.json").write_text(json.dumps(timing, indent=1))

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
