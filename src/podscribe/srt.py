from dataclasses import dataclass


@dataclass
class Segment:
    start: float  # seconds
    end: float
    text: str
    speaker: str | None = None


def _timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(segments: list[Segment]) -> str:
    """SRT cues; the speaker name is prefixed whenever the speaker changes."""
    blocks = []
    previous = None
    for i, seg in enumerate(segments, 1):
        text = seg.text
        if seg.speaker and seg.speaker != previous:
            text = f"{seg.speaker}: {text}"
        previous = seg.speaker
        blocks.append(f"{i}\n{_timestamp(seg.start)} --> {_timestamp(seg.end)}\n{text}\n")
    return "\n".join(blocks)


def to_text(segments: list[Segment]) -> str:
    """Plain text; consecutive segments by one speaker become a single paragraph."""
    if not any(seg.speaker for seg in segments):
        return "\n".join(seg.text for seg in segments) + "\n"
    paragraphs: list[tuple[str | None, list[str]]] = []
    for seg in segments:
        if paragraphs and paragraphs[-1][0] == seg.speaker:
            paragraphs[-1][1].append(seg.text)
        else:
            paragraphs.append((seg.speaker, [seg.text]))
    return "\n\n".join(
        f"{speaker}: {' '.join(texts)}" if speaker else " ".join(texts)
        for speaker, texts in paragraphs
    ) + "\n"
