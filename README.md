# NOT LIKE CLAUDE

A fully generated lyric video: an original parody song about Claude Code
(sequel to "Claude's Plan"). All lyrics are original. Vocals are a
deliberately robotic TTS voice (espeak-ng). Every animation is rendered
deterministically, frame by frame, from an HTML page driven by
`window.renderAt(t)`.

## Pipeline

```
audio/instrumental.mp3          (you supply this — gitignored)
        │
        ▼
src/analyze_audio.py    → analysis.json   (BPM, beat offset, energy map)
src/make_timing.py      → timing.json     (lyrics.md lines snapped to the beat grid)
src/make_vocals.py      → build/mix.wav   (espeak-ng robot vocals, tempo-fit per bar, mixed)
src/build_page.py       → build/video.html (timing + images + real `claude --help` inlined)
src/render_frames.js    → build/video_noaudio.mp4 (chromium screenshots piped to ffmpeg, 24fps)
        │
        ▼
ffmpeg mux              → build/not-like-claude.mp4
```

## Re-render from scratch

```bash
pip install -r requirements.txt
apt-get install espeak-ng ffmpeg fonts-inter fonts-jetbrains-mono
mkdir -p audio && cp <your-instrumental>.mp3 audio/instrumental.mp3

python3 src/analyze_audio.py
python3 src/make_timing.py
python3 src/make_vocals.py
python3 src/build_page.py
node src/render_frames.js                     # ~15 min
bash src/grade_mux.sh                         # color grade + mux
```

Note: `make_vocals.py` must run before `build_page.py` — it writes word-level
karaoke timings (`wf`/`vdur`, measured from per-word synthesis) back into
`timing.json`, which the page inlines.

Preview individual timestamps without a full render:

```bash
node src/render_frames.js --preview 15,95,215   # writes build/preview_*.png + assets/cover.png
```

## Swap in different audio (e.g., real sung vocals)

Re-run with any track of the same arrangement, or just remux:

```bash
ffmpeg -i build/video_noaudio.mp4 -i your_track.mp3 \
       -c:v copy -c:a aac -b:a 192k -shortest build/not-like-claude.mp4
```

If the new track's tempo/offset differs, re-run the whole pipeline —
timings, vocals, and animations all re-derive from `analysis.json`.

## Files

- `lyrics.md` — the original parody lyrics + suggested YouTube metadata
- `timing.json` — per-line start/end on the detected beat grid
- `analysis.json` — BPM 100.9, beat offset 0.404s, energy profile
- `assets/real/` — brand imagery fetched from claude.com / anthropic.com og cards
- `assets/cover.png` — generated thumbnail
- `src/video_template.html` — the whole animation system (scenes, widgets, karaoke, slams)

The instrumental and rendered videos are intentionally not committed.
