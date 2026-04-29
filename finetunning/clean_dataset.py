#!/usr/bin/env python3
"""clean_dataset.py — Post-build dataset cleaning and optional LLM enrichment.

Reads the Qwen-format JSONL files produced by build_dataset.py and applies a
three-stage pipeline:

  Stage 1 — Filter
    Discard entries that are completely unrecoverable:
      • Assistant content shorter than MIN_KEEP_LEN after noise removal
      • Contains a noise phrase AND no coherent chess keywords

  Stage 2 — Normalise
    • Strip "||..." noise suffixes
    • Remove boilerplate phrases ("see the variation", "ancient manual ends here", etc.)
    • Collapse multiple spaces / blank lines

  Stage 3 — Enrich  (optional, requires --enrich and an LLM API key)
    For entries that still have sparse assistant content after normalisation,
    call an LLM to generate instructive commentary that:
      • Names the pattern (classical or descriptive)
      • Explains why the move works
      • Uses [RELATIONS] from the user block for support

Usage
-----
    # Dry-run: print stats and 5 sample cleaned entries, write nothing
    python finetunning/clean_dataset.py --dry-run

    # Clean only (no LLM calls)
    python finetunning/clean_dataset.py

    # Clean + enrich sparse entries via LLM
    python finetunning/clean_dataset.py --enrich --api-key sk-...

    # Custom paths
    python finetunning/clean_dataset.py \\
        --train finetunning/data/dataset.train.jsonl \\
        --val   finetunning/data/dataset.val.jsonl \\
        --output-suffix .clean
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


# ========================
#   CONFIG
# ========================

# Entries whose assistant content is shorter than this (after cleaning) are
# dropped unless they contain a Chinese pattern name.
MIN_KEEP_LEN = 30

# Entries shorter than this trigger an LLM enrichment call (with --enrich).
ENRICH_THRESHOLD = 80

# Regex patterns that indicate noise content
_NOISE_RE = re.compile(
    r"\|\|"                           # double-pipe separator (noise suffix marker)
    r"|please see the variation"
    r"|see the variation"
    r"|ancient manual"
    r"|following moves were made but they have been cancelled"
    r"|what happened if"
    r"|please see below"
    r"|see below",
    re.IGNORECASE,
)

# Regex to strip the noise suffix (everything from || onward OR boilerplate phrase)
_STRIP_RE = re.compile(
    r"\|\|.*$"
    r"|(?:please see the variation.*$)"
    r"|(?:[^.!?\n]*ancient manual[^.!?\n]*[.!?]?)"
    r"|(?:in the ancient manual.*$)"
    r"|(?:following moves were made but they have been cancelled.*$)",
    re.IGNORECASE | re.DOTALL,
)

# Chinese chess-related characters — presence signals substantive content
_CHESS_CHINESE_RE = re.compile(r"[马炮车兵象将士杀局谱阵炮胜负和进退平]")

# English chess keywords
_CHESS_ENGLISH_RE = re.compile(
    r"\b(check|checkmate|attack|threat|fork|pin|capture|sacrifice|"
    r"cannon|chariot|horse|general|pawn|advisor|elephant|"
    r"opening|endgame|middlegame|position|tempo|initiative)\b",
    re.IGNORECASE,
)

# Extraction helpers for the user block
_FEN_RE = re.compile(r"FEN:\s*(\S+)")
_RELATIONS_RE = re.compile(r"\[RELATIONS\]\n(.*?)(?:\n\[|\Z)", re.DOTALL)
_MOVE_RE = re.compile(r"Move played:\s*(\S+)")


# ========================
#   STAGE 1+2: FILTER + NORMALISE
# ========================

def _has_chess_content(text: str) -> bool:
    return bool(_CHESS_CHINESE_RE.search(text) or _CHESS_ENGLISH_RE.search(text))


def _normalise(text: str) -> str:
    """Strip noise and normalise whitespace."""
    text = _STRIP_RE.sub("", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def clean_entry(entry: dict) -> Optional[dict]:
    """Apply filter + normalise.  Returns None if entry should be discarded."""
    messages = entry.get("messages", [])
    asst = next((m for m in messages if m["role"] == "assistant"), None)
    if asst is None:
        return None

    raw = asst["content"]
    cleaned = _normalise(raw)

    # Drop if too short and no chess content
    if len(cleaned) < MIN_KEEP_LEN:
        if not _has_chess_content(cleaned):
            return None
        # Very short but has a Chinese pattern name — keep but flag for enrichment
    elif _NOISE_RE.search(cleaned):
        # Noise was stripped but some remains (shouldn't happen after _STRIP_RE,
        # but guard against edge cases)
        if not _has_chess_content(cleaned):
            return None

    # Commit cleaned content
    asst["content"] = cleaned
    return {"messages": messages}


# ========================
#   STAGE 3: LLM ENRICHMENT
# ========================

def _extract_user_parts(user_content: str) -> tuple[str, str, str]:
    fen_m = _FEN_RE.search(user_content)
    rel_m = _RELATIONS_RE.search(user_content)
    move_m = _MOVE_RE.search(user_content)
    fen = fen_m.group(1) if fen_m else ""
    relations = rel_m.group(1).strip() if rel_m else ""
    move = move_m.group(1) if move_m else ""
    return fen, relations, move


def _needs_enrichment(text: str) -> bool:
    """Return True if the assistant content is too sparse to be useful."""
    if len(text) < ENRICH_THRESHOLD:
        return True
    # Has a pattern label but no explanatory sentence?
    has_explanation = bool(
        re.search(r"[.!?。！？]", text)  # at least one sentence terminator
        and len(text) > ENRICH_THRESHOLD
    )
    return not has_explanation


def _build_enrichment_prompt(
    fen: str, relations: str, move: str, original: str
) -> str:
    return (
        "You are an expert Xiangqi (Chinese Chess) coach.\n"
        "Improve the assistant's response for the position below.\n\n"
        "Requirements:\n"
        "- Start with the pattern name (classical Chinese name preferred, "
        "e.g. '马后炮', '双车胁士', '五七炮对屏风马').\n"
        "- Explain in 2-3 sentences why the given move works.\n"
        "- Reference the provided relations where helpful.\n"
        "- Do NOT include meta-commentary like 'see variation' or 'ancient manual'.\n"
        "- Output ONLY the improved commentary — no extra text.\n\n"
        f"FEN: {fen}\n"
        f"Relations:\n{relations}\n"
        f"Move: {move}\n"
        f"Original assistant response: {original}\n\n"
        "Improved commentary:"
    )


def enrich_entry(entry: dict, client) -> dict:
    """Call the LLM to enrich a sparse assistant response in-place."""
    messages = entry["messages"]
    user = next((m for m in messages if m["role"] == "user"), None)
    asst = next((m for m in messages if m["role"] == "assistant"), None)
    if user is None or asst is None:
        return entry

    if not _needs_enrichment(asst["content"]):
        return entry

    fen, relations, move = _extract_user_parts(user["content"])
    if not fen:
        return entry

    prompt = _build_enrichment_prompt(fen, relations, move, asst["content"])

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )
        enriched = response.choices[0].message.content.strip()
        if enriched:
            asst["content"] = enriched
    except Exception as exc:  # noqa: BLE001
        print(f"[WARNING] LLM enrichment failed: {exc}", file=sys.stderr)

    return entry


# ========================
#   PIPELINE
# ========================

def process_file(
    src: Path,
    dst: Path,
    enrich: bool,
    client,
    dry_run: bool,
) -> dict:
    """Clean (and optionally enrich) one JSONL file.  Returns stats dict."""
    total = kept = dropped = enriched_count = 0
    samples: list[dict] = []

    cleaned_entries: list[dict] = []

    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            total += 1
            result = clean_entry(entry)
            if result is None:
                dropped += 1
                continue

            if enrich and client is not None:
                asst = next(
                    (m for m in result["messages"] if m["role"] == "assistant"), None
                )
                if asst and _needs_enrichment(asst["content"]):
                    result = enrich_entry(result, client)
                    enriched_count += 1

            kept += 1
            cleaned_entries.append(result)
            if len(samples) < 5:
                samples.append(result)

    stats = {
        "source": str(src),
        "total": total,
        "kept": kept,
        "dropped": dropped,
        "enriched": enriched_count,
        "drop_rate": f"{dropped / total * 100:.1f}%" if total else "N/A",
    }

    if dry_run:
        _print_dry_run(stats, samples)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            for ex in cleaned_entries:
                f.write(json.dumps({"messages": ex["messages"]}, ensure_ascii=False) + "\n")
        print(f"  Written {kept} examples → {dst}")

    return stats


def _print_dry_run(stats: dict, samples: list[dict]) -> None:
    print(f"\n[DRY RUN] {stats['source']}")
    print(f"  total={stats['total']}  kept={stats['kept']}  "
          f"dropped={stats['dropped']} ({stats['drop_rate']})")
    print(f"\n  --- {min(5, len(samples))} sample cleaned entries ---")
    for ex in samples:
        asst = next(
            (m["content"] for m in ex["messages"] if m["role"] == "assistant"), ""
        )
        print(f"  [{len(asst):4d} chars] {asst[:120]!r}")
    print()


# ========================
#   CLI
# ========================

def parse_args() -> argparse.Namespace:
    _repo = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Clean + optionally enrich the Qwen fine-tuning dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--train",
        default=str(_repo / "finetunning/data/dataset.train.jsonl"),
        help="Input training JSONL",
    )
    parser.add_argument(
        "--val",
        default=str(_repo / "finetunning/data/dataset.val.jsonl"),
        help="Input validation JSONL",
    )
    parser.add_argument(
        "--output-suffix",
        default=".clean",
        help="Suffix appended before .jsonl for output files (default: .clean)",
    )
    parser.add_argument(
        "--min-len",
        type=int,
        default=MIN_KEEP_LEN,
        help=f"Min assistant response length to keep (default: {MIN_KEEP_LEN})",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Call LLM to enrich sparse assistant responses",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (also reads OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--enrich-model",
        default="gpt-4o-mini",
        help="LLM model to use for enrichment (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats and samples without writing output files",
    )
    return parser.parse_args()


def _output_path(src: Path, suffix: str) -> Path:
    """Insert suffix before the final .jsonl extension."""
    name = src.name
    if name.endswith(".jsonl"):
        name = name[: -len(".jsonl")] + suffix + ".jsonl"
    else:
        name = name + suffix
    return src.parent / name


def main() -> None:
    global MIN_KEEP_LEN  # allow CLI override
    args = parse_args()
    MIN_KEEP_LEN = args.min_len

    client = None
    if args.enrich:
        try:
            from openai import OpenAI  # type: ignore
            import os
            api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                print(
                    "[ERROR] --enrich requires an API key via --api-key or "
                    "OPENAI_API_KEY env var.",
                    file=sys.stderr,
                )
                sys.exit(1)
            client = OpenAI(api_key=api_key)
            client._model = args.enrich_model  # stash for enrich_entry
        except ImportError:
            print(
                "[ERROR] openai package not installed. Run: pip install openai",
                file=sys.stderr,
            )
            sys.exit(1)

    train_src = Path(args.train)
    val_src = Path(args.val)
    train_dst = _output_path(train_src, args.output_suffix)
    val_dst = _output_path(val_src, args.output_suffix)

    mode = "DRY RUN — " if args.dry_run else ""
    enrich_note = " + LLM enrichment" if args.enrich else ""
    print(f"\n{mode}Cleaning dataset{enrich_note}...")

    train_stats = process_file(train_src, train_dst, args.enrich, client, args.dry_run)
    val_stats = process_file(val_src, val_dst, args.enrich, client, args.dry_run)

    print("\n" + "=" * 60)
    print("CLEANING SUMMARY")
    print("=" * 60)
    for stats in (train_stats, val_stats):
        label = "train" if "train" in stats["source"] else "val"
        print(
            f"  {label:5s}  total={stats['total']:5d}  "
            f"kept={stats['kept']:5d}  dropped={stats['dropped']:4d} "
            f"({stats['drop_rate']})  enriched={stats['enriched']}"
        )
    if not args.dry_run:
        print(f"\n  Train → {train_dst}")
        print(f"  Val   → {val_dst}")
    print("=" * 60)


if __name__ == "__main__":
    main()
