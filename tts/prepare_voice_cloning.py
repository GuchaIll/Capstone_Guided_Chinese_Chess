#!/usr/bin/env python3
"""Bootstrap and validate voice-cloning annotations for local reference audio."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
STYLE_TEMPLATE = """mood:
pace:
energy:
delivery:
notes:
"""


@dataclass
class ClipAnnotation:
    clip_id: str
    voice_id: str
    audio_path: Path
    transcript_path: Path
    style_path: Path
    transcript: str
    style: dict[str, str]

    @property
    def ready(self) -> bool:
        return bool(self.transcript.strip())

    def to_dict(self, root: Path) -> dict[str, object]:
        return {
            "clip_id": self.clip_id,
            "voice_id": self.voice_id,
            "audio_path": str(self.audio_path.relative_to(root)),
            "transcript_path": str(self.transcript_path.relative_to(root)),
            "style_path": str(self.style_path.relative_to(root)),
            "transcript": self.transcript,
            "style": self.style,
            "ready": self.ready,
        }


def discover_audio_files(data_dir: Path) -> list[Path]:
    files = [
        path for path in data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ]
    return sorted(files)


def infer_voice_id(stem: str) -> str:
    normalized = re.sub(r"_v\d+$", "", stem)
    return normalized or stem


def ensure_sidecars(audio_path: Path) -> tuple[Path, Path]:
    return audio_path.with_suffix(".lab"), audio_path.with_suffix(".style.txt")


def bootstrap_files(transcript_path: Path, style_path: Path) -> None:
    if not transcript_path.exists():
        transcript_path.write_text("", encoding="utf-8")
    if not style_path.exists():
        style_path.write_text(STYLE_TEMPLATE, encoding="utf-8")


def load_transcript(transcript_path: Path) -> str:
    if not transcript_path.exists():
        return ""
    return transcript_path.read_text(encoding="utf-8").strip()


def load_style(style_path: Path) -> dict[str, str]:
    if not style_path.exists():
        return {}

    style: dict[str, str] = {}
    notes: list[str] = []
    for raw_line in style_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if key and value:
                style[key] = value
            continue
        notes.append(line)

    if notes:
        style["notes"] = " ".join(notes)
    return style


def build_manifest(root: Path, data_dir: Path, bootstrap: bool) -> list[ClipAnnotation]:
    clips: list[ClipAnnotation] = []
    for audio_path in discover_audio_files(data_dir):
        transcript_path, style_path = ensure_sidecars(audio_path)
        if bootstrap:
            bootstrap_files(transcript_path, style_path)

        clip_id = audio_path.stem
        voice_id = infer_voice_id(clip_id)
        clips.append(
            ClipAnnotation(
                clip_id=clip_id,
                voice_id=voice_id,
                audio_path=audio_path,
                transcript_path=transcript_path,
                style_path=style_path,
                transcript=load_transcript(transcript_path),
                style=load_style(style_path),
            )
        )
    return clips


def write_manifest(root: Path, manifest_path: Path, clips: list[ClipAnnotation]) -> None:
    grouped: dict[str, list[dict[str, object]]] = {}
    for clip in clips:
        grouped.setdefault(clip.voice_id, []).append(clip.to_dict(root))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clip_count": len(clips),
        "ready_clip_count": sum(1 for clip in clips if clip.ready),
        "voices": grouped,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def print_summary(clips: list[ClipAnnotation], manifest_path: Path) -> None:
    by_voice: dict[str, list[ClipAnnotation]] = {}
    for clip in clips:
        by_voice.setdefault(clip.voice_id, []).append(clip)

    print(f"Wrote manifest: {manifest_path}")
    print(f"Found {len(clips)} audio clips across {len(by_voice)} voice(s)")
    for voice_id, voice_clips in sorted(by_voice.items()):
        ready_count = sum(1 for clip in voice_clips if clip.ready)
        print(f"- {voice_id}: {ready_count}/{len(voice_clips)} clips annotated")
        for clip in voice_clips:
            transcript_state = "ready" if clip.ready else "missing transcript"
            style_state = "style ok" if clip.style else "style optional"
            print(f"  - {clip.clip_id}: {transcript_state}, {style_state}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default="tts/data",
        help="Directory containing voice reference audio clips.",
    )
    parser.add_argument(
        "--manifest",
        default="tts/voice_clone_manifest.json",
        help="Where to write the generated manifest.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create missing .lab and .style.txt files next to each audio clip.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    data_dir = root / args.data_dir
    manifest_path = root / args.manifest

    if not data_dir.exists():
        raise SystemExit(f"Data directory does not exist: {data_dir}")

    clips = build_manifest(root=root, data_dir=data_dir, bootstrap=args.bootstrap)
    if not clips:
        raise SystemExit(f"No audio clips found under {data_dir}")

    write_manifest(root=root, manifest_path=manifest_path, clips=clips)
    print_summary(clips, manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
