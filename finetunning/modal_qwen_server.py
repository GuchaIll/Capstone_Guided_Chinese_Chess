#!/usr/bin/env python3
"""Serve Qwen through Modal + vLLM as an OpenAI-compatible HTTP endpoint.

This app is designed to be a drop-in backend for the Go coaching service.
It serves `/v1/chat/completions` through vLLM's built-in OpenAI-compatible
API and reads model artifacts from a Modal Volume.

Typical deployment:

    modal deploy finetunning/modal_qwen_server.py

Typical coach env:

    LLM_PROVIDER=modal
    MODAL_LLM_BASE_URL=https://<workspace>--guided-chinese-chess-qwen-serve.modal.run/v1
    MODAL_LLM_MODEL=xiangqi-coach-qwen
    MODAL_LLM_API_KEY=<optional if you set MODAL_QWEN_API_KEY here>
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import modal


APP_NAME = os.environ.get("MODAL_APP_NAME", "guided-chinese-chess-qwen")
FINETUNING_VOLUME_NAME = os.environ.get(
    "MODAL_FINETUNING_VOLUME_NAME", "guided-chinese-chess-finetuning"
)
HF_CACHE_VOLUME_NAME = os.environ.get(
    "MODAL_HF_CACHE_VOLUME_NAME", "guided-chinese-chess-hf-cache"
)
VLLM_CACHE_VOLUME_NAME = os.environ.get(
    "MODAL_VLLM_CACHE_VOLUME_NAME", "guided-chinese-chess-vllm-cache"
)

GPU_CONFIG = os.environ.get("MODAL_QWEN_GPU", "A100-40GB")
BASE_MODEL = os.environ.get("MODAL_QWEN_BASE_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
SERVED_MODEL_NAME = os.environ.get("MODAL_QWEN_SERVED_MODEL", "xiangqi-coach-qwen")
MODEL_DIR = Path(os.environ.get("MODAL_QWEN_MODEL_DIR", "/models/qwen-xiangqi"))
LORA_DIR_RAW = os.environ.get("MODAL_QWEN_LORA_DIR", "").strip()
LORA_DIR = Path(LORA_DIR_RAW) if LORA_DIR_RAW else None
API_KEY = os.environ.get("MODAL_QWEN_API_KEY", "").strip()
VLLM_PORT = int(os.environ.get("MODAL_QWEN_PORT", "8000"))
TENSOR_PARALLEL = int(os.environ.get("MODAL_QWEN_TENSOR_PARALLEL", "1"))
MAX_MODEL_LEN = int(os.environ.get("MODAL_QWEN_MAX_MODEL_LEN", "8192"))
GPU_MEMORY_UTILIZATION = os.environ.get("MODAL_QWEN_GPU_MEMORY_UTILIZATION", "0.90")
FAST_BOOT = os.environ.get("MODAL_QWEN_FAST_BOOT", "true").lower() in {
    "1",
    "true",
    "yes",
}

HF_CACHE_DIR = "/root/.cache/huggingface"
VLLM_CACHE_DIR = "/root/.cache/vllm"

app = modal.App(APP_NAME)

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "vllm>=0.8.5,<1",
    "huggingface_hub>=0.30,<1",
)

finetuning_volume = modal.Volume.from_name(
    FINETUNING_VOLUME_NAME, create_if_missing=True
)
hf_cache_volume = modal.Volume.from_name(HF_CACHE_VOLUME_NAME, create_if_missing=True)
vllm_cache_volume = modal.Volume.from_name(
    VLLM_CACHE_VOLUME_NAME, create_if_missing=True
)


def _model_source() -> str:
    if MODEL_DIR.exists():
        return str(MODEL_DIR)
    return BASE_MODEL


def _build_vllm_command() -> list[str]:
    model_source = _model_source()
    cmd = [
        "vllm",
        "serve",
        model_source,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--served-model-name",
        SERVED_MODEL_NAME,
        "--download-dir",
        HF_CACHE_DIR,
        "--tensor-parallel-size",
        str(TENSOR_PARALLEL),
        "--max-model-len",
        str(MAX_MODEL_LEN),
        "--gpu-memory-utilization",
        GPU_MEMORY_UTILIZATION,
    ]
    cmd.append("--enforce-eager" if FAST_BOOT else "--no-enforce-eager")

    if API_KEY:
        cmd.extend(["--api-key", API_KEY])

    if LORA_DIR is not None and LORA_DIR.exists():
        cmd.extend(
            [
                "--enable-lora",
                "--lora-modules",
                f"{SERVED_MODEL_NAME}={LORA_DIR}",
            ]
        )

    return cmd


@app.function(
    image=image,
    gpu=GPU_CONFIG,
    scaledown_window=15 * 60,
    timeout=20 * 60,
    volumes={
        "/vol": finetuning_volume,
        HF_CACHE_DIR: hf_cache_volume,
        VLLM_CACHE_DIR: vllm_cache_volume,
    },
)
@modal.web_server(
    port=VLLM_PORT,
    startup_timeout=20 * 60,
    label="guided-chinese-chess-qwen-serve",
)
def serve() -> None:
    # Pick up any newly uploaded or newly trained checkpoints before boot.
    finetuning_volume.reload()

    cmd = _build_vllm_command()
    print("Starting vLLM:", shlex.join(cmd))
    subprocess.Popen(cmd)


@app.function(
    image=image,
    volumes={"/vol": finetuning_volume},
)
def inspect_volume() -> dict[str, object]:
    finetuning_volume.reload()
    model_exists = MODEL_DIR.exists()
    lora_exists = LORA_DIR is not None and LORA_DIR.exists()
    return {
        "volume": FINETUNING_VOLUME_NAME,
        "model_dir": str(MODEL_DIR),
        "model_exists": model_exists,
        "lora_dir": str(LORA_DIR) if LORA_DIR is not None else "",
        "lora_exists": lora_exists,
        "base_model_fallback": BASE_MODEL,
        "served_model_name": SERVED_MODEL_NAME,
    }
