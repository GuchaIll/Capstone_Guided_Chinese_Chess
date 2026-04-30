#!/usr/bin/env python3
"""Train the Xiangqi LoRA model on Modal using the shared finetuning Volume.

Example:

    modal run finetunning/modal_train_lora.py --epochs 3 --batch-size 1

This runner executes `/vol/finetunning/train_lora.py` inside a GPU-backed
Modal function, writes adapters back into the same Volume, and commits the
result so the serving app can read it later.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import modal


APP_NAME = os.environ.get("MODAL_TRAIN_APP_NAME", "guided-chinese-chess-train")
FINETUNING_VOLUME_NAME = os.environ.get(
    "MODAL_FINETUNING_VOLUME_NAME", "guided-chinese-chess-finetuning"
)
HF_CACHE_VOLUME_NAME = os.environ.get(
    "MODAL_HF_CACHE_VOLUME_NAME", "guided-chinese-chess-hf-cache"
)

GPU_CONFIG = os.environ.get("MODAL_TRAIN_GPU", "A100-40GB")
TRAIN_TIMEOUT_SECONDS = int(os.environ.get("MODAL_TRAIN_TIMEOUT_SECONDS", str(6 * 60 * 60)))
DEFAULT_MODEL = os.environ.get("MODAL_TRAIN_BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct")

VOLUME_ROOT = Path("/vol")
FINETUNING_ROOT = VOLUME_ROOT / "finetunning"
DEFAULT_TRAIN_FILE = FINETUNING_ROOT / "data" / "dataset.train.clean.jsonl"
DEFAULT_VAL_FILE = FINETUNING_ROOT / "data" / "dataset.val.clean.jsonl"
DEFAULT_OUTPUT_DIR = FINETUNING_ROOT / "output" / "xiangqi-lora"
HF_CACHE_DIR = "/root/.cache/huggingface"

app = modal.App(APP_NAME)

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "torch",
    "transformers",
    "trl",
    "peft",
    "datasets",
    "accelerate",
    "sentencepiece",
)

finetuning_volume = modal.Volume.from_name(
    FINETUNING_VOLUME_NAME, create_if_missing=True
)
hf_cache_volume = modal.Volume.from_name(HF_CACHE_VOLUME_NAME, create_if_missing=True)


def _train_script() -> Path:
    return FINETUNING_ROOT / "train_lora.py"


def _build_command(
    *,
    train_file: str,
    val_file: str,
    output_dir: str,
    model: str,
    epochs: int,
    lr: float,
    batch_size: int,
    grad_accum: int,
    max_seq_len: int,
    lora_r: int,
    lora_alpha: int,
    max_steps: int,
    no_fp16: bool,
) -> list[str]:
    cmd = [
        "python3",
        str(_train_script()),
        "--train-file",
        train_file,
        "--val-file",
        val_file,
        "--output-dir",
        output_dir,
        "--model",
        model,
        "--epochs",
        str(epochs),
        "--lr",
        str(lr),
        "--batch-size",
        str(batch_size),
        "--grad-accum",
        str(grad_accum),
        "--max-seq-len",
        str(max_seq_len),
        "--lora-r",
        str(lora_r),
        "--lora-alpha",
        str(lora_alpha),
        "--max-steps",
        str(max_steps),
    ]
    if no_fp16:
        cmd.append("--no-fp16")
    return cmd


@app.function(
    image=image,
    gpu=GPU_CONFIG,
    timeout=TRAIN_TIMEOUT_SECONDS,
    volumes={
        str(VOLUME_ROOT): finetuning_volume,
        HF_CACHE_DIR: hf_cache_volume,
    },
)
def train_remote(
    *,
    train_file: str = str(DEFAULT_TRAIN_FILE),
    val_file: str = str(DEFAULT_VAL_FILE),
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
    model: str = DEFAULT_MODEL,
    epochs: int = 5,
    lr: float = 5e-5,
    batch_size: int = 2,
    grad_accum: int = 4,
    max_seq_len: int = 2048,
    lora_r: int = 64,
    lora_alpha: int = 16,
    max_steps: int = -1,
    no_fp16: bool = False,
) -> dict[str, object]:
    finetuning_volume.reload()

    script_path = _train_script()
    if not script_path.exists():
        raise FileNotFoundError(
            f"Missing training script in Volume: {script_path}. "
            "Run ./finetunning/sync_modal_volume.sh first."
        )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("HF_HOME", HF_CACHE_DIR)
    env.setdefault("TRANSFORMERS_CACHE", HF_CACHE_DIR)

    cmd = _build_command(
        train_file=train_file,
        val_file=val_file,
        output_dir=output_dir,
        model=model,
        epochs=epochs,
        lr=lr,
        batch_size=batch_size,
        grad_accum=grad_accum,
        max_seq_len=max_seq_len,
        lora_r=lora_r,
        lora_alpha=lora_alpha,
        max_steps=max_steps,
        no_fp16=no_fp16,
    )

    print("Running training command:")
    print(" ".join(cmd))
    completed = subprocess.run(
        cmd,
        env=env,
        cwd=str(FINETUNING_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    print(completed.stdout)
    stdout_tail = completed.stdout.splitlines()[-40:]
    stderr_tail = completed.stderr.splitlines()[-40:]
    log_path = output_path / "modal_train_last_run.log"
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("=== COMMAND ===\n")
        log_file.write(" ".join(cmd) + "\n\n")
        log_file.write("=== STDOUT ===\n")
        log_file.write(completed.stdout)
        log_file.write("\n\n=== STDERR ===\n")
        log_file.write(completed.stderr)

    if completed.returncode != 0:
        print(completed.stderr)
        finetuning_volume.commit()
        details = [
            f"Modal LoRA training failed with exit code {completed.returncode}",
            f"log file: {log_path}",
        ]
        if stderr_tail:
            details.append("stderr tail:\n" + "\n".join(stderr_tail))
        elif stdout_tail:
            details.append("stdout tail:\n" + "\n".join(stdout_tail))
        raise RuntimeError("\n\n".join(details))

    finetuning_volume.commit()

    output_files = []
    if output_path.exists():
        output_files = sorted(
            str(path.relative_to(VOLUME_ROOT)) for path in output_path.rglob("*") if path.is_file()
        )

    result = {
        "status": "ok",
        "model": model,
        "train_file": train_file,
        "val_file": val_file,
        "output_dir": output_dir,
        "output_files": output_files,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "log_path": str(log_path),
    }
    print(json.dumps(result, indent=2))
    return result


@app.local_entrypoint()
def main(
    train_file: str = str(DEFAULT_TRAIN_FILE),
    val_file: str = str(DEFAULT_VAL_FILE),
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
    model: str = DEFAULT_MODEL,
    epochs: int = 5,
    lr: float = 5e-5,
    batch_size: int = 2,
    grad_accum: int = 4,
    max_seq_len: int = 2048,
    lora_r: int = 64,
    lora_alpha: int = 16,
    max_steps: int = -1,
    no_fp16: bool = False,
) -> None:
    result = train_remote.remote(
        train_file=train_file,
        val_file=val_file,
        output_dir=output_dir,
        model=model,
        epochs=epochs,
        lr=lr,
        batch_size=batch_size,
        grad_accum=grad_accum,
        max_seq_len=max_seq_len,
        lora_r=lora_r,
        lora_alpha=lora_alpha,
        max_steps=max_steps,
        no_fp16=no_fp16,
    )
    print(json.dumps(result, indent=2))
