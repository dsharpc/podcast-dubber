import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .config import MODEL_NAME, MODEL_URL, MODELS_DIR, WHISPER_BIN
from .srt import Segment


def ensure_model() -> Path:
    path = MODELS_DIR / MODEL_NAME
    if path.exists():
        return path
    MODELS_DIR.mkdir(exist_ok=True)
    print(f"Downloading KB-Whisper model (~1 GB) to {path} ...")
    tmp = path.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    tmp.rename(path)
    return path


def transcribe(wav: Path, out_prefix: Path) -> list[Segment]:
    """Transcribe Swedish audio with whisper.cpp; returns timestamped segments."""
    if not shutil.which(WHISPER_BIN):
        raise SystemExit(f"{WHISPER_BIN} not found. Install it with: brew install whisper-cpp")
    model = ensure_model()
    subprocess.run(
        [
            WHISPER_BIN, "-m", str(model), "-f", str(wav), "-l", "sv",
            "--output-json", "--output-file", str(out_prefix),
            "--print-progress",
        ],
        check=True,
    )
    return load_whisper_json(out_prefix.with_suffix(".json"))


def load_whisper_json(path: Path) -> list[Segment]:
    data = json.loads(path.read_text())
    segments = []
    for item in data["transcription"]:
        text = item["text"].strip()
        if text:
            segments.append(
                Segment(item["offsets"]["from"] / 1000, item["offsets"]["to"] / 1000, text)
            )
    return segments
