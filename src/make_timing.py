"""Build timing.json: parse lyrics.md sections, snap lines to the beat grid from analysis.json.

Section placement is driven by the energy map of THIS instrumental (see analyze_audio.py
output): hook/bridge/verse transitions sit on measured energy boundaries, snapped to beats.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
analysis = json.loads((ROOT / "analysis.json").read_text())

BEAT = analysis["sec_per_beat"]  # ~0.5946
OFF = analysis["beat_offset_sec"]  # ~0.404
BAR = 4 * BEAT
DUR = analysis["duration_sec"]


def snap_beat(t: float) -> float:
    n = round((t - OFF) / BEAT)
    return OFF + n * BEAT


# section -> (target start sec from energy map, bars per line, style)
PLAN = {
    "Intro": dict(start=9.9, bars_per_line=None, style="intro"),  # handcrafted spacing
    "Verse 1": dict(start=30.73, bars_per_line=1, style="verse"),
    "Hook": dict(start=92.5, bars_per_line=1, style="hook"),
    "Bridge": dict(start=111.5, bars_per_line=1, style="bridge"),
    "Verse 2": dict(start=130.6, bars_per_line=1, style="verse"),
    "Hook 2": dict(start=163.9, bars_per_line=1, style="hook"),
    "Verse 3": dict(start=182.95, bars_per_line=1, style="verse"),
    "Outro": dict(start=244.8, bars_per_line=None, style="outro"),  # handcrafted spacing
}

# sparse spacing (in bars) for intro/outro lines
INTRO_BARS = [2, 2, 1.5, 1.5, 1, 1]
OUTRO_BARS = [1, 1, 1, 1, 2, 1, 1, 2]


def parse_lyrics() -> dict:
    sections: dict[str, list[str]] = {}
    current = None
    for raw in (ROOT / "lyrics.md").read_text().splitlines():
        line = raw.strip()
        if line.startswith("## "):
            name = line[3:].strip()
            if name in PLAN:
                current = name
                sections[current] = []
            else:
                current = None
        elif line == "---":
            current = None
        elif current and line and not line.startswith("#") and not line.startswith("*"):
            sections[current].append(line)
    return sections


def main() -> None:
    sections = parse_lyrics()
    events = []
    for name, cfg in PLAN.items():
        lines = sections[name]
        t = snap_beat(cfg["start"])
        spacing = (
            INTRO_BARS if name == "Intro" else OUTRO_BARS if name == "Outro" else [cfg["bars_per_line"]] * len(lines)
        )
        assert len(spacing) >= len(lines), f"{name}: {len(lines)} lines > {len(spacing)} slots"
        for text, bars in zip(lines, spacing):
            dur = bars * BAR
            events.append(
                {
                    "section": name,
                    "style": cfg["style"],
                    "start": round(t, 3),
                    "end": round(min(t + dur, DUR), 3),
                    "text": text,
                    "tts": re.sub(r"\([^)]*\)", "", text).replace("—", ", ").strip(" ,-"),
                }
            )
            t += dur
    # sanity: no overlaps across section boundaries
    for a, b in zip(events, events[1:]):
        if b["start"] < a["end"] - 1e-6:
            a["end"] = b["start"]
    (ROOT / "timing.json").write_text(json.dumps({"bpm": analysis["bpm"], "events": events}, indent=1))
    print(f"{len(events)} events, first={events[0]['start']}s last_end={events[-1]['end']}s (audio {DUR}s)")
    for name in PLAN:
        sec = [e for e in events if e["section"] == name]
        print(f"  {name:8s} {sec[0]['start']:7.2f} -> {sec[-1]['end']:7.2f}  ({len(sec)} lines)")


if __name__ == "__main__":
    main()
