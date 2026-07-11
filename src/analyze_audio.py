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


def clap_onsets(y: np.ndarray, sr: int = SR) -> np.ndarray:
    """Onset envelope of the 1.5-6 kHz band (claps/snares sit ON beats 2&4),
    5 ms resolution. Much more trustworthy for phase than broadband flux,
    which happily locks onto eighth-note hats half a beat off."""
    spec = np.fft.rfft(y)
    freqs = np.fft.rfftfreq(len(y), 1 / sr)
    band = np.fft.irfft(spec * ((freqs >= 1500) & (freqs <= 6000)), len(y)).astype(np.float32)
    env = np.abs(band)
    hop = int(0.005 * sr)
    m = len(env) // hop
    e = env[: m * hop].reshape(m, hop).max(axis=1)
    on = np.diff(e)
    on[on < 0] = 0
    return on


def refine_grid(on: np.ndarray, bpm0: float, dur: float) -> tuple:
    """Tempo by DRIFT MINIMIZATION, phase from the full-track clap sweep.

    A wrong tempo shows up as clap phase sliding across the song (a global
    best-fit hides it: right in the middle, up to half a beat off at the
    ends — audibly 'early'). The true tempo is the one where the locally
    measured phase is constant in every window."""
    fps = 200.0
    windows = [(a, min(a + 40, dur - 5)) for a in range(20, int(dur) - 45, 40)]

    def local_phase(period: float, a: float, b: float) -> float:
        best = (0.0, -1.0)
        for off in np.arange(0, period, 0.005):
            start = a + (off - (a % period)) % period
            idx = (np.arange(start, b, period) * fps).astype(int)
            idx = idx[(idx >= a * fps) & (idx < min(b * fps, len(on)))]
            if not len(idx):
                continue
            s = float(on[idx].mean())
            if s > best[1]:
                best = (off, s)
        return best[0]

    best = (bpm0, 1e9)
    for bpm in np.arange(bpm0 - 0.5, bpm0 + 0.5, 0.01):
        period = 2 * 60 / bpm  # claps repeat every 2 beats
        phases = [local_phase(period, a, b) for a, b in windows]
        rel = [(p - phases[0] + period / 2) % period - period / 2 for p in phases]
        spread = max(rel) - min(rel)
        if spread < best[1]:
            best = (float(bpm), float(spread))
    bpm = best[0]

    # global clap phase at the drift-free tempo -> beat offset (claps sit ON beats)
    beat = 60 / bpm
    off_best = (0.0, -1.0)
    for off in np.arange(0, beat, 0.0025):
        idx = (np.arange(off, dur, beat) * fps).astype(int)
        idx = idx[idx < len(on)]
        s = float(on[idx].mean())
        if s > off_best[1]:
            off_best = (float(off), s)
    return bpm, off_best[0], best[1]


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
    on = clap_onsets(y)
    bpm, off, spread = refine_grid(on, bpm0, dur)
    print(f"grid refined: coarse {bpm0:.1f} -> {bpm:.2f} BPM, offset {off:.3f}s, phase spread {spread*1000:.0f}ms")
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
