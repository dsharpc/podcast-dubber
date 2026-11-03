import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from . import audio, diarize as diarizer, dub as dubber, eleven, episode, speakers, record as recorder
from . import transcribe as transcriber, translate as translator
from .config import DEFAULT_NUM_SPEAKERS, EPISODES_DIR


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "episode"


def _episode_dir(name: str | None) -> Path:
    name = _slug(name) if name else datetime.now().strftime("%Y%m%d-%H%M%S")
    path = EPISODES_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _existing_episode(arg: str) -> Path:
    path = Path(arg)
    if not path.is_dir():
        raise SystemExit(f"{path} is not an episode directory")
    return path


def cmd_record(args) -> Path:
    directory = _episode_dir(args.name)
    raw = directory / "recording.caf"
    print("Start playback in Spotify now. Press Ctrl-C when the episode ends.")
    recorder.record(raw, args.silence_timeout, args.max_minutes)
    wav = audio.to_whisper_wav(raw, directory / "audio.wav")
    print(f"Saved {wav}")
    return directory


def cmd_transcribe(args) -> Path:
    directory = _existing_episode(args.episode)
    wav = directory / "audio.wav"
    if not wav.exists():
        raise SystemExit(f"{wav} not found")
    transcriber.transcribe(wav, directory / "whisper")
    episode.write_outputs(directory)
    return directory


def cmd_diarize(args) -> Path:
    directory = _existing_episode(args.episode)
    wav = directory / "audio.wav"
    if not wav.exists():
        raise SystemExit(f"{wav} not found")
    turns = diarizer.diarize(wav, args.num_speakers)
    diarizer.save_turns(turns, directory / "diarization.json")
    episode.write_outputs(directory)
    print("\nWho is who? First lines per speaker (in order of first appearance):\n")
    print(speakers.preview(episode.load_segments(directory)))
    print('\nName them with: podscribe speakers', directory, '--names "Host,Anna,Erik"')
    return directory


def cmd_speakers(args) -> Path:
    directory = _existing_episode(args.episode)
    if not (directory / "diarization.json").exists():
        raise SystemExit("No diarization yet. Run `podscribe diarize` first.")
    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
        (directory / "speakers.json").write_text(json.dumps({"names": names}, ensure_ascii=False))
    episode.write_outputs(directory)
    print("\n" + speakers.preview(episode.load_segments(directory)))
    return directory


def cmd_translate(args) -> Path:
    directory = _existing_episode(args.episode)
    segments = transcriber.load_whisper_json(directory / "whisper.json")
    episode.save_translation(directory, translator.translate(segments))
    episode.write_outputs(directory)
    return directory


def cmd_voices(args) -> None:
    """List ElevenLabs stock voices, to choose one per speaker."""
    c = eleven.client()
    found = eleven.find_voices(c, args.accent, args.gender, None if args.all_categories else "premade")
    if not found:
        raise SystemExit("No matching voices. Try --all-categories, or a different --accent.")
    for v in found:
        labels = v.labels or {}
        print(f"{v.name}\n  id: {v.voice_id}   {labels.get('gender', '?')}, {labels.get('accent', '?')}, {labels.get('age', '?')}"
              f"{', ' + labels['descriptive'] if labels.get('descriptive') else ''}")
        if v.preview_url:
            print(f"  preview: {v.preview_url}")
    print('\nPick one per speaker, in order of first appearance, e.g.: podscribe dub EPISODE --backend elevenlabs --voices "Alice,Daniel,George" --minutes 2')


def cmd_dub(args) -> Path:
    directory = _existing_episode(args.episode)
    segments = episode.load_english_segments(directory)
    if segments is None:
        raise SystemExit("No translation yet. Run `podscribe translate` first.")
    name = "dub.en"
    if args.minutes:
        segments = [s for s in segments if s.start < args.minutes * 60]
        name += f".first-{args.minutes:g}min"
    cache, max_chunk, client = directory / "dub_cache", dubber.MAX_CHUNK_CHARS, None
    if args.backend == "elevenlabs":
        name += ".eleven"
        client = eleven.client()
        speakers_in_order = list(dict.fromkeys(seg.speaker for seg in segments))
        refs = [v.strip() for v in args.voices.split(",") if v.strip()] if args.voices else []
        if len(refs) < len(speakers_in_order):
            raise SystemExit(f"Choose {len(speakers_in_order)} voices (one per speaker, in order of first appearance) with --voices. "
                             "Run `podscribe voices` to list British stock voices.")
        voice_for = dubber.assign_voices(segments, eleven.resolve_voices(client, refs))
        chars = sum(len(s.text) for s in segments)
        left = eleven.credits_left(client)
        print(f"{chars} characters to synthesise (about ${chars / 1000 * 0.08:.2f} at the list API rate); {left} plan credits left")
        if not args.minutes and not args.yes:
            raise SystemExit("This spends credits. Test with --minutes 1 first and check the usage it reports, then re-run with --yes.")
        synth, tag = eleven.eleven_synth(client)
        max_chunk = 1500
        before = eleven.credits_used(client)
    else:
        voices = [v.strip() for v in args.voices.split(",")] if args.voices else None
        voice_for = dubber.assign_voices(segments, voices or dubber.DUB_VOICES)
        synth, tag = dubber.kokoro_synth(args.speed)
    dubber.dub(segments, directory / f"{name}.mp3", cache, voice_for, synth, tag, max_chunk)
    if client:
        spent = eleven.credits_used(client) - before
        if spent > 0:
            print(f"Used {spent} ElevenLabs credits for {chars} characters ({spent / max(chars, 1):.2f} per character); {eleven.credits_left(client)} left")
        else:
            print(f"Your plan's credit counter did not change for {chars} characters. API usage may be billed in dollars "
                  "against a pay-as-you-go balance instead. Check Usage in the ElevenLabs dashboard before running a full episode.")
    return directory


def cmd_run(args) -> None:
    directory = cmd_record(args)
    args.episode = str(directory)
    cmd_transcribe(args)
    if not args.skip_diarization:
        cmd_diarize(args)
    if not args.skip_translation:
        cmd_translate(args)
        if not args.skip_dub:
            args.minutes, args.voices, args.backend, args.yes = 0, None, "kokoro", False
            cmd_dub(args)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="podscribe",
        description="Record Spotify podcasts, transcribe (sv), label speakers and translate (en).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_record_opts(p):
        p.add_argument("--name", help="episode name (default: timestamp)")
        p.add_argument("--silence-timeout", type=float, default=30, help="stop after N seconds of silence once audio started (0 = off)")
        p.add_argument("--max-minutes", type=float, default=0, help="hard stop after N minutes (0 = off)")

    def add_speaker_opts(p):
        p.add_argument("--num-speakers", type=int, default=DEFAULT_NUM_SPEAKERS, help="number of speakers (default %(default)s)")

    p = sub.add_parser("record", help="record Spotify audio to episodes/<name>/audio.wav")
    add_record_opts(p)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("transcribe", help="transcribe an episode directory to Swedish text")
    p.add_argument("episode", help="path to episodes/<name>")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("diarize", help="label who is speaking (needs a Hugging Face token)")
    p.add_argument("episode", help="path to episodes/<name>")
    add_speaker_opts(p)
    p.set_defaults(func=cmd_diarize)

    p = sub.add_parser("speakers", help="rename speakers and rewrite the transcripts (no models or API calls)")
    p.add_argument("episode", help="path to episodes/<name>")
    p.add_argument("--names", help='comma-separated, in order of first appearance, e.g. "Host,Anna,Erik"')
    p.set_defaults(func=cmd_speakers)

    p = sub.add_parser("translate", help="translate a transcribed episode to English")
    p.add_argument("episode", help="path to episodes/<name>")
    p.set_defaults(func=cmd_translate)

    p = sub.add_parser("voices", help="list ElevenLabs stock voices (British by default)")
    p.add_argument("--accent", default="british", help="filter on accent label (default british; '' for any)")
    p.add_argument("--gender", choices=["female", "male"], help="filter on gender label")
    p.add_argument("--all-categories", action="store_true", help="include voices you added to your account, not just ElevenLabs' premade ones")
    p.set_defaults(func=cmd_voices)

    p = sub.add_parser("dub", help="generate English audio, one voice per speaker")
    p.add_argument("episode", help="path to episodes/<name>")
    p.add_argument("--backend", choices=["kokoro", "elevenlabs"], default="kokoro", help="kokoro: free, local, stock British voices (default)")
    p.add_argument("--yes", action="store_true", help="elevenlabs: confirm spending credits on a full episode")
    p.add_argument("--minutes", type=float, default=0, help="only dub the first N minutes (quick test)")
    p.add_argument("--voices", help="comma-separated voices in order of first appearance. kokoro: voice names (default: bf_emma,bm_george,bm_daniel); "
                                    "elevenlabs: voice names or ids from `podscribe voices` (required)")
    p.add_argument("--speed", type=float, default=1.0, help="speaking speed (default 1.0)")
    p.set_defaults(func=cmd_dub)

    p = sub.add_parser("run", help="record, transcribe, label speakers, translate and dub in one go")
    add_record_opts(p)
    add_speaker_opts(p)
    p.add_argument("--skip-diarization", action="store_true")
    p.add_argument("--skip-translation", action="store_true")
    p.add_argument("--skip-dub", action="store_true")
    p.add_argument("--speed", type=float, default=1.0, help="dubbing speed (default 1.0)")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
