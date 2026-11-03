# podscribe

Record a Spotify podcast on macOS, transcribe the Swedish audio with KB-Whisper, and translate to English with Claude.

## Setup (once)

```sh
brew install whisper-cpp            # whisper-cli, Metal-accelerated
./swift/build.sh                    # builds bin/spotifytap (needs Xcode CLT)
```

Put your keys in a `.env` file in the project root (gitignored; the tool loads it automatically):

```
ANTHROPIC_API_KEY=sk-ant-...   # translation
HF_TOKEN=hf_...                # speaker labels (needed for the first model download)
ELEVENLABS_API_KEY=sk_...      # optional, ElevenLabs voices
```

The KB-Whisper model (~1 GB) downloads to `models/` on first transcription.

## Usage

```sh
uv run podscribe run --name my-episode      # record -> transcribe -> translate
# or step by step:
uv run podscribe record --name my-episode   # start playback in Spotify, Ctrl-C when done
uv run podscribe transcribe episodes/my-episode
uv run podscribe translate episodes/my-episode
```

## Speaker labels

One-off: create a Hugging Face token (read access), accept the terms at
https://huggingface.co/pyannote/speaker-diarization-community-1, then put `HF_TOKEN=hf_...` in `.env`
(or run `uv run hf auth login`).

```sh
uv run podscribe diarize episodes/my-episode        # --num-speakers defaults to 3
uv run podscribe speakers episodes/my-episode --names "Host,Anna,Erik"
```

`diarize` prints sample lines per speaker so you can tell who is who. Names are assigned in order of
first appearance. `speakers` only rewrites the transcript files from cached data, so renaming is
instant and never re-runs the model or calls the API again.

## English audio

```sh
uv run podscribe dub episodes/my-episode                # full episode -> dub.en.mp3
uv run podscribe dub episodes/my-episode --minutes 2    # quick 2-minute test
uv run podscribe dub episodes/my-episode --voices bf_alice,bm_daniel,bm_george --speed 0.95
```

Runs locally with Kokoro (via mlx-audio): free, British voices, one per speaker in order of first
appearance (default: `bf_emma`, `bm_george`, `bm_daniel`). Other British voices: `bf_alice` (female), `bm_daniel`, `bm_george` (male); Kokoro may have more, see its VOICES.md. Synthesised chunks are cached in `dub_cache/`, so reruns only redo what changed.

### ElevenLabs (stock voices)

Put `ELEVENLABS_API_KEY=...` in `.env` (gitignored). Then pick one stock voice per speaker:

```sh
uv run podscribe voices --gender female                 # list British stock voices (names, ids, preview links)
uv run podscribe voices --gender male
uv run podscribe dub episodes/my-episode --backend elevenlabs --voices "Alice,Daniel,George" --minutes 2   # cheap test
uv run podscribe dub episodes/my-episode --backend elevenlabs --voices "Alice,Daniel,George" --yes         # full episode
```

Voices are assigned in order of first appearance (so the host first). `dub` prints the estimated cost beforehand and the credits
actually used afterwards; a full episode is blocked unless you pass `--yes`. The tool deliberately does not clone anyone's voice.

Output in `episodes/<name>/`: `audio.wav`, `whisper.json`, `diarization.json`, `translation.en.json`, `transcript.sv.{srt,txt}`, `transcript.en.{srt,txt}`, `dub.en.mp3`.

The first recording makes macOS ask for audio-recording permission for your terminal app
(System Settings > Privacy & Security > Screen & System Audio Recording). Recording is real time,
and it stops on Ctrl-C or after 30 s of silence once audio has started (`--silence-timeout`).
