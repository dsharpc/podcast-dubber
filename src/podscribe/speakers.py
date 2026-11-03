from dataclasses import dataclass

from .srt import Segment


@dataclass
class Turn:
    start: float
    end: float
    speaker: str  # raw label from the diarization model, e.g. SPEAKER_00


def assign_speakers(segments: list[Segment], turns: list[Turn]) -> list[Segment]:
    """Give each segment the speaker whose turns overlap it most (nearest turn if none overlap)."""
    result = []
    for seg in segments:
        overlap: dict[str, float] = {}
        for turn in turns:
            amount = min(seg.end, turn.end) - max(seg.start, turn.start)
            if amount > 0:
                overlap[turn.speaker] = overlap.get(turn.speaker, 0) + amount
        if overlap:
            speaker = max(overlap, key=overlap.get)
        elif turns:
            mid = (seg.start + seg.end) / 2
            speaker = min(turns, key=lambda t: min(abs(t.start - mid), abs(t.end - mid))).speaker
        else:
            speaker = None
        result.append(Segment(seg.start, seg.end, seg.text, speaker))
    return result


def name_mapping(segments: list[Segment], names: list[str] | None) -> dict[str, str]:
    """Map raw labels to readable names, in order of first appearance in the transcript.

    Without `names` speakers are called "Speaker 1", "Speaker 2", ...
    """
    order: list[str] = []
    for seg in segments:
        if seg.speaker and seg.speaker not in order:
            order.append(seg.speaker)
    return {
        raw: names[i] if names and i < len(names) else f"Speaker {i + 1}"
        for i, raw in enumerate(order)
    }


def display_names(segments: list[Segment], names: list[str] | None) -> list[Segment]:
    """Replace raw labels with readable names (see `name_mapping`)."""
    mapping = name_mapping(segments, names)
    return [
        Segment(s.start, s.end, s.text, mapping.get(s.speaker) if s.speaker else None)
        for s in segments
    ]


def preview(segments: list[Segment], per_speaker: int = 2, max_chars: int = 110) -> str:
    """A few sample lines per speaker, to help work out who is who."""
    seen: dict[str, list[str]] = {}
    for seg in segments:
        if seg.speaker:
            lines = seen.setdefault(seg.speaker, [])
            if len(lines) < per_speaker and len(seg.text) > 25:
                lines.append(f"[{int(seg.start) // 60}:{int(seg.start) % 60:02}] {seg.text[:max_chars]}")
    return "\n".join(f"{speaker}\n  " + "\n  ".join(lines) for speaker, lines in seen.items())
