"""Inline timing.json, analysis.json, base64 images, and real CLI text into video_template.html
-> build/video.html (self-contained, rendered offline by chromium)."""
import base64
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)
REAL = ROOT / "assets" / "real"

MIME = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

IMAGES = {
    "og_claude": "og_claude.jpg",
    "og_anthropic": "og_anthropic.jpg",
    "og_docs": "og_claudecode_docs.png",
    "golden_gate": "golden_gate_claude.webp",
    "mapping": "mapping_mind.webp",
    "core_views": "core_views.webp",
}


def data_uri(p: Path) -> str:
    return f"data:{MIME[p.suffix]};base64," + base64.b64encode(p.read_bytes()).decode()


def main() -> None:
    timing = (ROOT / "timing.json").read_text()
    analysis = (ROOT / "analysis.json").read_text()
    # strip heavy rms array from page payload
    a = json.loads(analysis)
    a.pop("rms", None)
    imgs = {k: data_uri(REAL / v) for k, v in IMAGES.items()}
    help_txt = subprocess.run(["claude", "--help"], capture_output=True, text=True).stdout
    help_txt = "\n".join(help_txt.splitlines()[:18])

    html = (ROOT / "src" / "video_template.html").read_text()
    html = html.replace("__TIMING__", timing)
    html = html.replace("__ANALYSIS__", json.dumps(a))
    html = html.replace("__IMAGES__", json.dumps(imgs))
    html = html.replace("__HELP__", json.dumps(help_txt))
    out = BUILD / "video.html"
    out.write_text(html)
    print("wrote", out, f"({out.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
