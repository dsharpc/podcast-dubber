import signal
import subprocess
from pathlib import Path

from .config import TAP_BIN


def record(out: Path, silence_timeout: float = 30, max_minutes: float = 0) -> Path:
    """Record Spotify's audio to `out` until Ctrl-C, silence, or the time limit."""
    if not TAP_BIN.exists():
        raise SystemExit(f"{TAP_BIN} not found. Run ./swift/build.sh first.")
    cmd = [str(TAP_BIN), str(out), "--silence-timeout", str(silence_timeout)]
    if max_minutes:
        cmd += ["--max-minutes", str(max_minutes)]
    proc = subprocess.Popen(cmd)
    try:
        proc.wait()
    except KeyboardInterrupt:
        # The helper handles SIGINT itself and finalises the file; just wait for it.
        proc.send_signal(signal.SIGINT)
        proc.wait()
    if proc.returncode != 0:
        raise SystemExit(f"spotifytap exited with code {proc.returncode}")
    return out
