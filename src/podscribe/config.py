import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TAP_BIN = REPO_ROOT / "bin" / "spotifytap"
MODELS_DIR = REPO_ROOT / "models"
EPISODES_DIR = REPO_ROOT / "episodes"


def _load_dotenv() -> None:
    """Load KEY=value lines from <repo>/.env (gitignored) without overriding real environment variables."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv()

WHISPER_BIN = "whisper-cli"
# KBLab's Swedish fine-tune of Whisper large, 5-bit quantised GGML build.
MODEL_NAME = "ggml-kb-whisper-large-q5_0.bin"
MODEL_URL = "https://huggingface.co/KBLab/kb-whisper-large/resolve/main/ggml-model-q5_0.bin"

TRANSLATION_MODEL = "claude-sonnet-5-5"

DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
DEFAULT_NUM_SPEAKERS = 3

# English dubbing: Kokoro (local, via mlx-audio) with British voices.
TTS_MODEL = "mlx-community/Kokoro-82M-bf16"
TTS_LANG_CODE = "b"  # British English
TTS_SAMPLE_RATE = 24000
# Assigned to speakers in order of first appearance: Host (female), then two male guests.
DUB_VOICES = ["bf_emma", "bm_george", "bm_daniel"]

# ElevenLabs stock voices (needs ELEVENLABS_API_KEY).
ELEVEN_MODEL = "eleven_v4"
