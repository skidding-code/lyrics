#!/usr/bin/env bash
# Color grade the rendered frames + mux a mix -> final MP4.
# Warm-shadow curves, contrast/sat lift, vignette, film grain, light sharpen.
# Usage: grade_mux.sh [mix.wav] [out.mp4]
set -euo pipefail
cd "$(dirname "$0")/.."
MIX="${1:-build/mix.wav}"
OUT="${2:-build/not-like-claude.mp4}"
ffmpeg -y -v error -i build/video_noaudio.mp4 -i "$MIX" -filter_complex \
  "[0:v]curves=r='0/0.02 0.5/0.53 1/0.985':g='0/0.015 0.5/0.5 1/0.965':b='0/0.05 0.5/0.47 1/0.92',\
eq=contrast=1.06:saturation=1.14:brightness=0.012,\
vignette=angle=PI/4.6,noise=alls=3:allf=t,unsharp=5:5:0.35[v]" \
  -map "[v]" -map 1:a -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p \
  -c:a aac -b:a 192k "$OUT"
echo "graded + muxed -> $OUT"
