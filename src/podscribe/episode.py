"""Everything derived from an episode directory's cached files.

whisper.json        raw Swedish transcript (whisper.cpp)
diarization.json    speaker turns (optional)
speakers.json       {"names": [...]} display names in order of first appearance (optional)
translation.en.json English text per segment (optional)
"""
import json
from dataclasses import replace
from pathlib import Path

from . import diarize, speakers, transcribe
from .srt import Segment, to_srt, to_text


def _names(directory: Path) -> list[str] | None:
    names_file = directory / "speakers.json"
    return json.loads(names_file.read_text())["names"] if names_file.exists() else None


def load_segments(directory: Path) -> list[Segment]:
    segments = transcribe.load_whisper_json(directory / "whisper.json")
    turns_file = directory / "diarization.json"
    if turns_file.exists():
        segments = speakers.assign_speakers(segments, diarize.load_turns(turns_file))
        segments = speakers.display_names(segments, _names(directory))
    return segments



def save_translation(directory: Path, texts: list[str]) -> None:
    (directory / "translation.en.json").write_text(json.dumps(texts, ensure_ascii=False, indent=1))


def load_english_segments(directory: Path) -> list[Segment] | None:
    """Segments with English text and speaker names, or None if not translated yet."""
    translation = directory / "translation.en.json"
    if not translation.exists():
        return None
    texts = json.loads(translation.read_text())
    return [replace(s, text=t) for s, t in zip(load_segments(directory), texts, strict=True)]


def write_outputs(directory: Path) -> None:
    """(Re)write all transcript files from the cached data. Never calls a model or an API."""
    outputs = {"sv": load_segments(directory)}
    english = load_english_segments(directory)
    if english:
        outputs["en"] = english
    for lang, segs in outputs.items():
        (directory / f"transcript.{lang}.srt").write_text(to_srt(segs))
        (directory / f"transcript.{lang}.txt").write_text(to_text(segs))
        print(f"Wrote {directory}/transcript.{lang}.srt and .txt")
