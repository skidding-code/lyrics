"""Analyze the instrumental: BPM, downbeat offset, section energy map -> analysis.json"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from imageio_ffmpeg import get_ffmpeg_exe

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio" / "instrumental.mp3"
OUT = ROOT / "analysis.json"

SR = 22050


def decode_mono(path: Path, sr: int = SR) -> np.ndarray:
    cmd = [get_ffmpeg_exe(), "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-v", "error", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def onset_envelope(y: np.ndarray, hop: int = 256, win: int = 1024) -> np.ndarray:
    n = (len(y) - win) // hop
    frames = np.lib.stride_tricks.as_strided(
        y, shape=(n, win), strides=(y.strides[0] * hop, y.strides[0])
    )
    mag = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1))
    flux = np.diff(mag, axis=0)
    flux[flux < 0] = 0
    env = flux.sum(axis=1)
    env = env / (env.max() + 1e-9)
    return env


def estimate_bpm_coarse(env: np.ndarray, sr: int = SR, hop: int = 256) -> float:
    fps = sr / hop
    env = env - env.mean()
    ac = np.correlate(env, env, mode="full")[len(env) - 1 :]
    best_bpm, best_val = 0.0, -1.0
    for bpm10 in range(800, 1800):  # 80..180 BPM in 0.1 steps
        bpm = bpm10 / 10
        lag = fps * 60 / bpm
        # sum autocorrelation at lag and multiples for robustness
        val = sum(ac[int(round(lag * k))] for k in (1, 2, 3, 4)) / 4
        if val > best_val:
            best_val, best_bpm = val, bpm
    return best_bpm


def refine_grid(env: np.ndarray, bpm0: float, sr: int = SR, hop: int = 256) -> tuple:
    """Joint fine search over (bpm, offset) maximizing mean onset energy ON the beats.

    The autocorrelation estimate can land ~0.1 BPM off and knows nothing about phase;
    over a 4.5 min track that is an audible drift, so score the grid directly."""
    fps = sr / hop

    def score(bpm: float, off: float) -> float:
        period = fps * 60 / bpm
        idx = np.arange(off * fps, len(env), period).astype(int)
        return float(env[idx].mean())

    best = (bpm0, 0.0, -1.0)
    for bpm in np.arange(bpm0 - 0.7, bpm0 + 0.7, 0.01):
        period = 60 / bpm
        for off in np.arange(0, period, 0.005):
            s = score(bpm, off)
            if s > best[2]:
                best = (float(bpm), float(off), s)
    return best


def rms_profile(y: np.ndarray, sr: int = SR, step: float = 0.5) -> list:
    n = int(step * sr)
    m = len(y) // n
    rms = np.sqrt((y[: m * n].reshape(m, n) ** 2).mean(axis=1))
    return [round(float(v), 5) for v in rms]


def main() -> None:
    y = decode_mono(AUDIO)
    dur = len(y) / SR
    env = onset_envelope(y)
    bpm0 = estimate_bpm_coarse(env)
    bpm, off, grid_score = refine_grid(env, bpm0)
    print(f"grid refined: coarse {bpm0:.1f} -> {bpm:.2f} BPM, offset {off:.3f}s, score {grid_score:.3f}")
    data = {
        "duration_sec": round(dur, 3),
        "bpm": round(bpm, 2),
        "beat_offset_sec": round(off, 3),
        "sec_per_beat": round(60 / bpm, 5),
        "sec_per_bar": round(240 / bpm, 5),
        "rms_step_sec": 0.5,
        "rms": rms_profile(y),
    }
    OUT.write_text(json.dumps(data, indent=1))
    print(f"duration={dur:.2f}s bpm={bpm:.2f} offset={off:.3f}s bar={240/bpm:.3f}s")
    # quick section hints: where does energy jump/drop?
    rms = np.array(data["rms"])
    smooth = np.convolve(rms, np.ones(8) / 8, mode="same")
    thresh = smooth.mean()
    state = smooth[0] > thresh
    for i in range(1, len(smooth)):
        s = smooth[i] > thresh
        if s != state:
            print(f"  energy {'UP' if s else 'down'} at {i*0.5:.1f}s")
            state = s


if __name__ == "__main__":
    sys.exit(main())
