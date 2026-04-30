#!/usr/bin/env python3
"""train_lora.py — LoRA fine-tuning for the Xiangqi chess coach model.

Fine-tunes Qwen/Qwen2.5-7B-Instruct with LoRA adapters on the combined
commentary + tactical-pattern dataset produced by build_dataset.py.
Uses completion-only label masking so loss is computed only on assistant
response tokens.

Usage
-----
    # Standard training run
    python finetunning/train_lora.py

    # Quick validation run (20 steps only, no full training)
    python finetunning/train_lora.py --max-steps 20

    # Custom paths / hyperparameters
    python finetunning/train_lora.py \\
        --train-file finetunning/data/dataset.train.jsonl \\
        --val-file   finetunning/data/dataset.val.jsonl \\
        --output-dir finetunning/output/xiangqi-lora \\
        --epochs 5 \\
        --lr 5e-5

Prerequisites
-------------
    pip install transformers trl peft torch datasets accelerate
"""

from __future__ import annotations

import argparse
import inspect
import os
import sys
from pathlib import Path
from typing import Any

import warnings
warnings.filterwarnings("ignore")

# ========================
#   ARGUMENT PARSING
# ========================

def parse_args() -> argparse.Namespace:
    _repo = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="LoRA fine-tuning for Xiangqi chess coach (TinyLlama-1.1B)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--train-file",
        default=str(_repo / "finetunning/data/dataset.train.jsonl"),
        help="Training JSONL file (each line: {\"text\": \"...\"})",
    )
    parser.add_argument(
        "--val-file",
        default=str(_repo / "finetunning/data/dataset.val.jsonl"),
        help="Validation JSONL file",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_repo / "finetunning/output/xiangqi-lora"),
        help="Directory to save LoRA adapter checkpoints",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen2.5-7B-Instruct",
        help="Base model name on HuggingFace Hub",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=5,
        help="Number of training epochs (default: 5)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=5e-5,
        help="Learning rate (default: 5e-5)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="Per-device train batch size (default: 2)",
    )
    parser.add_argument(
        "--grad-accum",
        type=int,
        default=4,
        help="Gradient accumulation steps (default: 4)",
    )
    parser.add_argument(
        "--max-seq-len",
        type=int,
        default=2048,
        help="Maximum token sequence length (default: 2048)",
    )
    parser.add_argument(
        "--lora-r",
        type=int,
        default=64,
        help="LoRA rank r (default: 64)",
    )
    parser.add_argument(
        "--lora-alpha",
        type=int,
        default=16,
        help="LoRA scaling alpha (default: 16)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=-1,
        help="Override epochs with a fixed step count (-1 = use epochs)",
    )
    parser.add_argument(
        "--no-fp16",
        action="store_true",
        help="Disable FP16 training (use full precision)",
    )
    return parser.parse_args()


# ========================
#   DATA LOADING
# ========================

def load_jsonl(path: str) -> list[dict]:
    """Load a JSONL file into a list of dicts. Skips blank and unparseable lines."""
    import json
    records: list[dict] = []
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] File not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


# ========================
#   TRAINING
# ========================

def train(args: argparse.Namespace) -> None:
    # Disable W&B
    os.environ["WANDB_DISABLED"] = "true"

    # --- Imports (deferred so arg-parse errors surface before heavy imports) ---
    import torch
    from datasets import Dataset
    from peft import LoraConfig, TaskType
    from transformers import DataCollatorForLanguageModeling
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
        logging as hf_logging,
    )
    from trl import SFTTrainer

    hf_logging.set_verbosity_error()

    try:
        from trl import DataCollatorForCompletionOnlyLM  # type: ignore
    except ImportError:
        DataCollatorForCompletionOnlyLM = None

    # --- Load dataset ---
    print(f"Loading training data from: {args.train_file}")
    train_records = load_jsonl(args.train_file)
    print(f"  {len(train_records)} training examples")

    print(f"Loading validation data from: {args.val_file}")
    val_records = load_jsonl(args.val_file)
    print(f"  {len(val_records)} validation examples")

    # --- Tokenizer ---
    print(f"\nLoading tokenizer: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(
        args.model, trust_remote_code=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # --- Apply Qwen chat template to produce text field ---
    def _to_text(record: dict) -> dict:
        messages = record["messages"]
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
        return {"text": text, "messages": messages}

    train_dataset = Dataset.from_list(
        [_to_text(r) for r in train_records]
    )
    val_dataset = Dataset.from_list(
        [_to_text(r) for r in val_records]
    )

    # --- Base model ---
    print(f"Loading base model: {args.model}")
    dtype = torch.float16 if not args.no_fp16 and torch.cuda.is_available() else torch.float32
    base_model = AutoModelForCausalLM.from_pretrained(
        args.model,
        device_map="auto",
        torch_dtype=dtype,
        trust_remote_code=True,
    )
    base_model.config.use_cache = False
    base_model.config.pretraining_tp = 1

    # --- LoRA config ---
    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.1,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )

    # --- Completion-only data collator (loss only on assistant tokens) ---
    response_template = "<|im_start|>assistant\n"
    if DataCollatorForCompletionOnlyLM is not None:
        data_collator = DataCollatorForCompletionOnlyLM(
            response_template=response_template,
            tokenizer=tokenizer,
        )
    else:
        print(
            "trl.DataCollatorForCompletionOnlyLM is unavailable; "
            "using built-in completion-only masking fallback."
        )
        data_collator = _CompletionOnlyFallbackCollator(
            tokenizer=tokenizer,
            response_template=response_template,
            max_length=args.max_seq_len,
            torch_module=torch,
            lm_collator_cls=DataCollatorForLanguageModeling,
        )

    # --- Training arguments ---
    use_fp16 = not args.no_fp16 and torch.cuda.is_available()
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs if args.max_steps == -1 else 1,
        max_steps=args.max_steps,
        learning_rate=args.lr,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        fp16=use_fp16,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
    )

    # --- Trainer ---
    trainer_kwargs: dict[str, Any] = {
        "model": base_model,
        "train_dataset": train_dataset,
        "eval_dataset": val_dataset,
        "peft_config": lora_config,
        "data_collator": data_collator,
        "args": training_args,
    }
    trainer_signature = inspect.signature(SFTTrainer.__init__)
    trainer_params = trainer_signature.parameters

    if "formatting_func" in trainer_params:
        trainer_kwargs["formatting_func"] = lambda sample: sample["text"]
    elif "dataset_text_field" in trainer_params:
        trainer_kwargs["dataset_text_field"] = "text"

    if "tokenizer" in trainer_params:
        trainer_kwargs["tokenizer"] = tokenizer
    elif "processing_class" in trainer_params:
        trainer_kwargs["processing_class"] = tokenizer

    if "max_seq_length" in trainer_params:
        trainer_kwargs["max_seq_length"] = args.max_seq_len
    elif "max_length" in trainer_params:
        trainer_kwargs["max_length"] = args.max_seq_len

    trainer = SFTTrainer(**trainer_kwargs)

    # --- Train ---
    print(
        f"\nStarting training — {len(train_records)} train / "
        f"{len(val_records)} val examples"
    )
    if args.max_steps > 0:
        print(f"  (quick-validation mode: max_steps={args.max_steps})")
    print(
        f"  LoRA r={args.lora_r}, alpha={args.lora_alpha}, "
        f"epochs={args.epochs}, lr={args.lr}, fp16={use_fp16}"
    )
    print()

    trainer.train()

    # --- Save LoRA adapter ---
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    print(f"\nLoRA adapter saved to: {output_dir}")
    print(
        "\nTo run inference with the fine-tuned adapter:\n"
        f"  from peft import PeftModel\n"
        f"  from transformers import AutoModelForCausalLM, AutoTokenizer\n"
        f"  model = AutoModelForCausalLM.from_pretrained('{args.model}')\n"
        f"  model = PeftModel.from_pretrained(model, '{output_dir}')\n"
        f"  tokenizer = AutoTokenizer.from_pretrained('{output_dir}')"
    )


class _CompletionOnlyFallbackCollator:
    """Compatibility fallback when TRL doesn't export completion-only collator."""

    def __init__(
        self,
        *,
        tokenizer: Any,
        response_template: str,
        max_length: int,
        torch_module: Any,
        lm_collator_cls: Any,
    ) -> None:
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.torch = torch_module
        self.template_ids = tokenizer.encode(
            response_template,
            add_special_tokens=False,
        )
        self.lm_collator = lm_collator_cls(
            tokenizer=tokenizer,
            mlm=False,
            return_tensors="pt",
        )

    def __call__(self, features: list[dict[str, Any]]) -> dict[str, Any]:
        encoded_features: list[dict[str, Any]] = []
        for feature in features:
            if "text" in feature:
                encoded = self.tokenizer(
                    feature["text"],
                    truncation=True,
                    max_length=self.max_length,
                    add_special_tokens=False,
                )
                input_ids = encoded["input_ids"]
                attention_mask = encoded["attention_mask"]
            elif "input_ids" in feature:
                input_ids = self._to_int_list(feature["input_ids"])
                if len(input_ids) > self.max_length:
                    input_ids = input_ids[: self.max_length]
                if "attention_mask" in feature:
                    attention_mask = self._to_int_list(feature["attention_mask"])[: len(input_ids)]
                else:
                    attention_mask = [1] * len(input_ids)
            else:
                raise KeyError(
                    f"Expected feature to contain 'text' or 'input_ids', got keys: {sorted(feature.keys())}"
                )

            labels = list(input_ids)
            start = self._find_last_subsequence(input_ids, self.template_ids)
            if start == -1:
                labels = [-100] * len(labels)
            else:
                assistant_start = start + len(self.template_ids)
                labels[:assistant_start] = [-100] * assistant_start
            encoded_features.append(
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "labels": labels,
                }
            )

        batch = self.lm_collator(encoded_features)
        labels = batch["labels"]
        pad_token_id = self.tokenizer.pad_token_id
        if pad_token_id is not None:
            labels = self.torch.where(
                batch["input_ids"] == pad_token_id,
                self.torch.full_like(labels, -100),
                labels,
            )
        batch["labels"] = labels
        return batch

    @staticmethod
    def _find_last_subsequence(haystack: list[int], needle: list[int]) -> int:
        if not needle or len(needle) > len(haystack):
            return -1
        for start in range(len(haystack) - len(needle), -1, -1):
            if haystack[start : start + len(needle)] == needle:
                return start
        return -1

    @staticmethod
    def _to_int_list(values: Any) -> list[int]:
        if hasattr(values, "tolist"):
            values = values.tolist()
        return [int(value) for value in values]


# ========================
#   ENTRY POINT
# ========================

if __name__ == "__main__":
    args = parse_args()
    train(args)
