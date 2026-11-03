import json
import os
import wave
from pathlib import Path

from .config import DIARIZATION_MODEL
from .speakers import Turn

_HELP = f"""Could not load {DIARIZATION_MODEL}. You need to:
  1. create a free Hugging Face account and a read token (huggingface.co/settings/tokens)
  2. open huggingface.co/{DIARIZATION_MODEL} and accept the terms
  3. make the token available: `export HF_TOKEN=hf_...` (or run `uv run hf auth login`)"""


def _load_waveform(wav: Path):
    import numpy as np
    import torch

    with wave.open(str(wav)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"{wav} must be 16 kHz mono 16-bit WAV (record/convert it with podscribe)")
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    waveform = torch.from_numpy(samples.astype("float32") / 32768).unsqueeze(0)
    return {"waveform": waveform, "sample_rate": 16000}


def diarize(wav: Path, num_speakers: int | None) -> list[Turn]:
    """Work out who spoke when. Returns non-overlapping speaker turns."""
    import torch
    from pyannote.audio import Pipeline
    from pyannote.audio.pipelines.utils.hook import ProgressHook

    try:
        pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=os.environ.get("HF_TOKEN"))
    except Exception as e:  # gated repo, missing/invalid token, offline ...
        raise SystemExit(f"{_HELP}\n\nOriginal error: {type(e).__name__}: {e}")
    if pipeline is None:
        raise SystemExit(_HELP)

    audio = _load_waveform(wav)
    wanted = os.environ.get("PODSCRIBE_DEVICE") or ("mps" if torch.backends.mps.is_available() else "cpu")
    for device in dict.fromkeys([wanted, "cpu"]):  # fall back to CPU if the GPU path fails
        try:
            pipeline.to(torch.device(device))
            print(f"Diarizing on {device} ...")
            with ProgressHook() as hook:
                output = pipeline(audio, num_speakers=num_speakers, hook=hook)
            break
        except Exception as e:
            if device == "cpu":
                raise
            print(f"{device} failed ({type(e).__name__}: {e}); retrying on cpu")

    # The "exclusive" variant has no overlapping turns, which is what we want for transcripts.
    annotation = getattr(output, "exclusive_speaker_diarization", output)
    return [Turn(t.start, t.end, speaker) for t, _, speaker in annotation.itertracks(yield_label=True)]


def save_turns(turns: list[Turn], path: Path) -> None:
    path.write_text(json.dumps([vars(t) for t in turns], indent=1))


def load_turns(path: Path) -> list[Turn]:
    return [Turn(**t) for t in json.loads(path.read_text())]
