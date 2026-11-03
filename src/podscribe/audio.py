import subprocess
from pathlib import Path

# Drop leading silence (recording starts before playback) and trailing silence.
_TRIM = (
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.3,"
    "areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.3,areverse"
)


def to_whisper_wav(src: Path, dst: Path, trim: bool = True) -> Path:
    """Convert any audio file to the 16 kHz mono WAV that whisper.cpp expects."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if trim:
        cmd += ["-af", _TRIM]
    cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True)
    if dst.stat().st_size < 1000:
        raise SystemExit(
            f"{src} contains no audible sound (output is empty). Make sure Spotify is playing and that "
            "your terminal has audio-recording permission, then record again."
        )
    return dst
