"""ElevenLabs backend: dub with stock voices from ElevenLabs' own voice library."""
import os

import numpy as np

from .config import ELEVEN_MODEL, TTS_SAMPLE_RATE
from .dub import Synth


def client():
    from elevenlabs.client import ElevenLabs

    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise SystemExit(
            "ELEVENLABS_API_KEY is not set. Create a key at elevenlabs.io (Developers > API Keys), then add\n"
            "ELEVENLABS_API_KEY=... to .env in the project root (it is gitignored)."
        )
    return ElevenLabs(api_key=key)


def credits_used(c) -> int:
    return c.user.subscription.get().character_count


def credits_left(c) -> int:
    sub = c.user.subscription.get()
    return sub.character_limit - sub.character_count


def _all_voices(c, **filters) -> list:
    voices, token = [], None
    while True:
        page = c.voices.search(page_size=100, next_page_token=token, **filters)
        voices += page.voices
        token = page.next_page_token
        if not page.has_more or not token:
            return voices


def find_voices(c, accent: str | None = "british", gender: str | None = None, category: str | None = "premade") -> list:
    """Voices available to the account, filtered on their labels (accent, gender)."""
    voices = _all_voices(c, **({"category": category} if category else {}))

    def matches(v) -> bool:
        labels = v.labels or {}
        return (not accent or accent.lower() in (labels.get("accent") or "").lower()) and (
            not gender or gender.lower() == (labels.get("gender") or "").lower()
        )

    return sorted((v for v in voices if matches(v)), key=lambda v: (v.labels or {}).get("gender") or "")


def resolve_voices(c, refs: list[str]) -> list[str]:
    """Turn voice names (e.g. "Alice") or ids into ids. A name may omit the " - description" suffix."""
    by_name = {}
    for v in _all_voices(c):
        by_name[v.name.lower()] = v.voice_id
        by_name.setdefault(v.name.split(" - ")[0].strip().lower(), v.voice_id)
    return [by_name.get(ref.lower(), ref) for ref in refs]


def eleven_synth(c) -> tuple[Synth, str]:
    def synth(text: str, voice_id: str) -> np.ndarray:
        pcm = b"".join(c.text_to_speech.convert(voice_id, text=text, model_id=ELEVEN_MODEL, output_format=f"pcm_{TTS_SAMPLE_RATE}"))
        return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768

    return synth, f"eleven|{ELEVEN_MODEL}"
