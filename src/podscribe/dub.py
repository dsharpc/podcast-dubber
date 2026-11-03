"""Turn the English transcript into speech, one voice per speaker. The voice backend is pluggable."""
import hashlib
import re
import subprocess
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .config import DUB_VOICES, TTS_LANG_CODE, TTS_MODEL, TTS_SAMPLE_RATE
from .srt import Segment

PAUSE_BETWEEN_TURNS = 0.45  # seconds
PAUSE_BETWEEN_CHUNKS = 0.12
MAX_CHUNK_CHARS = 300

# (text, voice) -> mono float32 audio at TTS_SAMPLE_RATE
Synth = Callable[[str, str], np.ndarray]


def build_turns(segments: list[Segment]) -> list[tuple[str | None, str]]:
    """Merge consecutive segments by one speaker into (speaker, text) turns."""
    turns: list[tuple[str | None, list[str]]] = []
    for seg in segments:
        if turns and turns[-1][0] == seg.speaker:
            turns[-1][1].append(seg.text)
        else:
            turns.append((seg.speaker, [seg.text]))
    return [(speaker, " ".join(texts)) for speaker, texts in turns]


def split_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on sentence ends, packing sentences into chunks of at most `max_chars`."""
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if chunks and len(chunks[-1]) + 1 + len(sentence) <= max_chars:
            chunks[-1] += " " + sentence
        else:
            chunks.append(sentence)
    return [c for c in chunks if c]


def assign_voices(segments: list[Segment], voices: list[str]) -> dict[str | None, str]:
    """Voices go to speakers in order of first appearance (cycling if there are more speakers)."""
    order: list[str | None] = []
    for seg in segments:
        if seg.speaker not in order:
            order.append(seg.speaker)
    return {speaker: voices[i % len(voices)] for i, speaker in enumerate(order)}


def kokoro_synth(speed: float = 1.0) -> tuple[Synth, str]:
    """Local Kokoro backend (British English). Returns (synth, cache tag)."""
    from mlx_audio.tts.utils import load_model

    model = None

    def synth(text: str, voice: str) -> np.ndarray:
        nonlocal model
        if model is None:
            model = load_model(TTS_MODEL)
        parts = [np.array(r.audio, dtype=np.float32).reshape(-1)
                 for r in model.generate(text, voice=voice, speed=speed, lang_code=TTS_LANG_CODE)]
        return np.concatenate(parts) if parts else _silence(0.2)

    return synth, f"kokoro|{TTS_MODEL}|{speed}"


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * TTS_SAMPLE_RATE), dtype=np.float32)


def _write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TTS_SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def dub(
    segments: list[Segment],
    out_mp3: Path,
    cache_dir: Path,
    voice_for: dict[str | None, str],
    synth: Synth,
    tag: str,
    max_chunk_chars: int = MAX_CHUNK_CHARS,
) -> Path:
    """Synthesise `segments` to `out_mp3`. Finished chunks are cached by (tag, voice, text)."""
    turns = build_turns(segments)
    cache_dir.mkdir(exist_ok=True)
    print("Voices: " + ", ".join(f"{s or 'Speaker'} = {v}" for s, v in voice_for.items()))

    def speak(text: str, voice: str) -> np.ndarray:
        key = hashlib.sha1(f"{tag}|{voice}|{text}".encode()).hexdigest()[:20]
        cached = cache_dir / f"{key}.npy"
        if cached.exists():
            return np.load(cached)
        audio = synth(text, voice)
        np.save(cached, audio)
        return audio

    pieces: list[np.ndarray] = []
    for i, (speaker, text) in enumerate(turns, 1):
        voice = voice_for[speaker]
        print(f"  turn {i}/{len(turns)}  {speaker or 'Speaker'}  {len(text)} chars", flush=True)
        for j, chunk in enumerate(split_chunks(text, max_chunk_chars)):
            if j:
                pieces.append(_silence(PAUSE_BETWEEN_CHUNKS))
            pieces.append(speak(chunk, voice))
        pieces.append(_silence(PAUSE_BETWEEN_TURNS))

    audio = np.concatenate(pieces)
    peak = float(np.abs(audio).max())
    if peak > 0.95:
        audio = audio * (0.95 / peak)
    wav = out_mp3.with_suffix(".wav")
    _write_wav(wav, audio)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3", str(out_mp3)], check=True)
    wav.unlink()
    print(f"Wrote {out_mp3} ({len(audio) / TTS_SAMPLE_RATE / 60:.1f} min)")
    return out_mp3
