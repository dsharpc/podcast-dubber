import os
import re

import anthropic

from .config import TRANSLATION_MODEL
from .srt import Segment

CHUNK_SIZE = 60
CONTEXT_LINES = 5

SYSTEM = """You translate Swedish podcast transcripts into natural, fluent English.
You receive numbered subtitle lines, one per line, formatted as `N| text`.
Reply with exactly one line per input line, in the same `N| text` format and the same numbering,
with nothing else. Never merge, split, skip or reorder lines; if a line is a sentence fragment,
translate the fragment. Keep names, places and brand names as in the original. Preserve the
speakers' tone and register. Lines marked as context are for reference only: do not translate them."""

_LINE = re.compile(r"^\s*(\d+)\|\s?(.*)$")


def _translate_chunk(client, numbered: list[tuple[int, str]], context: list[tuple[int, str]]) -> dict[int, str]:
    prompt = ""
    if context:
        prompt += "Context (already translated, do not output):\n"
        prompt += "\n".join(f"{n}| {t}" for n, t in context) + "\n\n"
    prompt += "Translate these lines:\n" + "\n".join(f"{n}| {t}" for n, t in numbered)

    expected = {n for n, _ in numbered}
    for attempt in range(3):
        resp = client.messages.create(
            model=TRANSLATION_MODEL, max_tokens=8000, system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        result = {}
        for line in text.splitlines():
            m = _LINE.match(line)
            if m and int(m.group(1)) in expected:
                result[int(m.group(1))] = m.group(2).strip()
        if result.keys() == expected:
            return result
        print(f"  chunk returned {len(result)}/{len(expected)} lines, retrying ({attempt + 1}/3)")
    raise RuntimeError("Translation kept returning mismatched line counts")


def translate(segments: list[Segment]) -> list[str]:
    """Translate segments sv -> en; returns one English string per input segment."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Add ANTHROPIC_API_KEY=... to .env in the project root (it is gitignored)."
        )
    client = anthropic.Anthropic()
    translated: dict[int, str] = {}
    lines = [(i + 1, s.text) for i, s in enumerate(segments)]
    for start in range(0, len(lines), CHUNK_SIZE):
        chunk = lines[start : start + CHUNK_SIZE]
        context = [(n, translated[n]) for n, _ in lines[max(0, start - CONTEXT_LINES) : start]]
        print(f"Translating lines {chunk[0][0]}-{chunk[-1][0]} of {len(lines)} ...")
        translated.update(_translate_chunk(client, chunk, context))
    return [translated[i + 1] for i in range(len(segments))]
