#!/usr/bin/env python3
"""Serve Fish Speech voice cloning on Modal using reference bundles from Kibo."""

from __future__ import annotations

import base64
import glob
import os
import subprocess
import tempfile
from pathlib import Path

import modal
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field


APP_NAME = os.environ.get("MODAL_FISH_APP_NAME", "guided-chinese-chess-fish")
SERVE_LABEL = os.environ.get("MODAL_FISH_LABEL", "guided-chinese-chess-fish-serve")
FISH_REPO_DIR = Path("/opt/fish-speech")
MODEL_REPO_ID = os.environ.get("MODAL_FISH_MODEL_REPO", "fishaudio/s2-pro")
MODEL_NAME = os.environ.get("MODAL_FISH_MODEL", "s2-pro")
GPU_CONFIG = os.environ.get("MODAL_FISH_GPU", "A100-40GB")
TIMEOUT_SECONDS = int(os.environ.get("MODAL_FISH_TIMEOUT_SECONDS", "900"))
CHECKPOINTS_VOLUME_NAME = os.environ.get(
    "MODAL_FISH_CHECKPOINTS_VOLUME_NAME",
    "guided-chinese-chess-fish-checkpoints",
)
HF_CACHE_VOLUME_NAME = os.environ.get(
    "MODAL_FISH_HF_CACHE_VOLUME_NAME",
    "guided-chinese-chess-fish-hf-cache",
)
CHECKPOINT_ROOT = Path("/models/checkpoints")
MODEL_DIR = CHECKPOINT_ROOT / MODEL_NAME
HF_CACHE_DIR = "/root/.cache/huggingface"
USE_HALF = os.environ.get("MODAL_FISH_USE_HALF", "false").lower() in {"1", "true", "yes"}

app = modal.App(APP_NAME)

image = modal.Image.from_registry("fishaudio/fish-speech:latest").pip_install(
    "fastapi[standard]>=0.115,<1",
    "huggingface_hub>=0.30,<1",
)

checkpoints_volume = modal.Volume.from_name(CHECKPOINTS_VOLUME_NAME, create_if_missing=True)
hf_cache_volume = modal.Volume.from_name(HF_CACHE_VOLUME_NAME, create_if_missing=True)


class TTSReference(BaseModel):
    filename: str
    audio_base64: str
    text: str
    style: dict[str, str] = Field(default_factory=dict)


class TTSRequest(BaseModel):
    text: str
    model: str = MODEL_NAME
    response_format: str = "wav"
    prompt_text: str = ""
    style_summary: str = ""
    references: list[TTSReference]


def _ensure_checkpoint_symlink() -> None:
    link_path = FISH_REPO_DIR / "checkpoints" / MODEL_NAME
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink() or link_path.exists():
        return
    link_path.symlink_to(MODEL_DIR)


def _ensure_model_downloaded() -> None:
    from huggingface_hub import snapshot_download

    checkpoints_volume.reload()
    if not MODEL_DIR.exists():
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not (MODEL_DIR / "codec.pth").exists():
        snapshot_download(
            repo_id=MODEL_REPO_ID,
            local_dir=str(MODEL_DIR),
            local_dir_use_symlinks=False,
        )
        checkpoints_volume.commit()
    _ensure_checkpoint_symlink()


def _convert_reference_audio(input_path: Path, work_dir: Path) -> Path:
    output_path = work_dir / "reference.wav"
    cmd = ["ffmpeg", "-y", "-i", str(input_path), str(output_path)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return output_path


def _pick_first(pattern: str, search_dir: Path) -> Path:
    matches = sorted(glob.glob(str(search_dir / pattern)))
    if not matches:
        raise FileNotFoundError(f"expected output matching {pattern}")
    return Path(matches[0])


def _run_fish_pipeline(request: TTSRequest) -> bytes:
    if not request.references:
        raise HTTPException(status_code=400, detail="at least one reference is required")

    reference = request.references[0]
    if not reference.text.strip():
        raise HTTPException(status_code=400, detail="reference transcript is required")

    with tempfile.TemporaryDirectory(prefix="fish-tts-") as tmp:
        work_dir = Path(tmp)
        input_path = work_dir / reference.filename
        input_path.write_bytes(base64.b64decode(reference.audio_base64))
        reference_wav = _convert_reference_audio(input_path, work_dir)

        codec_path = FISH_REPO_DIR / "checkpoints" / MODEL_NAME / "codec.pth"
        dac_cmd = [
            "python",
            str(FISH_REPO_DIR / "fish_speech/models/dac/inference.py"),
            "-i",
            str(reference_wav),
            "--checkpoint-path",
            str(codec_path),
        ]
        subprocess.run(dac_cmd, cwd=work_dir, check=True, capture_output=True, text=True)
        prompt_tokens = _pick_first("*.npy", work_dir)

        semantic_cmd = [
            "python",
            str(FISH_REPO_DIR / "fish_speech/models/text2semantic/inference.py"),
            "--text",
            request.text,
            "--prompt-text",
            reference.text,
            "--prompt-tokens",
            str(prompt_tokens),
        ]
        if USE_HALF:
            semantic_cmd.append("--half")
        subprocess.run(semantic_cmd, cwd=work_dir, check=True, capture_output=True, text=True)
        codes_path = _pick_first("codes_*.npy", work_dir)

        decode_cmd = [
            "python",
            str(FISH_REPO_DIR / "fish_speech/models/dac/inference.py"),
            "-i",
            str(codes_path),
            "--checkpoint-path",
            str(codec_path),
        ]
        subprocess.run(decode_cmd, cwd=work_dir, check=True, capture_output=True, text=True)
        wav_candidates = sorted(work_dir.glob("*.wav"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not wav_candidates:
            raise FileNotFoundError("fish pipeline did not produce a wav output")
        return wav_candidates[0].read_bytes()


@app.function(
    image=image,
    gpu=GPU_CONFIG,
    timeout=TIMEOUT_SECONDS,
    scaledown_window=15 * 60,
    volumes={
        str(CHECKPOINT_ROOT): checkpoints_volume,
        HF_CACHE_DIR: hf_cache_volume,
    },
)
@modal.asgi_app(label=SERVE_LABEL)
def serve() -> FastAPI:
    api = FastAPI(title="Guided Chinese Chess Fish TTS")

    @api.on_event("startup")
    async def startup() -> None:
        _ensure_model_downloaded()

    @api.get("/health")
    async def health() -> JSONResponse:
        _ensure_model_downloaded()
        return JSONResponse({"status": "ok", "model": MODEL_NAME, "repo": MODEL_REPO_ID})

    @api.post("/tts")
    async def tts(request: TTSRequest) -> Response:
        _ensure_model_downloaded()
        try:
            audio_bytes = _run_fish_pipeline(request)
        except HTTPException:
            raise
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise HTTPException(status_code=502, detail=detail) from exc
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(content=audio_bytes, media_type="audio/wav")

    return api
