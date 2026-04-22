#!/usr/bin/env python3
"""
Commentary Anchor Preprocessor
===============================

Takes engine-analyzed JSONL (output of generate_training_data.py) and produces
clean, filtered training datasets for fine-tuning.

Outputs:
  1. commentary_anchor.jsonl       — v1 training set: only rows with expert commentary
  2. commentary_anchor_context.jsonl — v2 sidecar: anchors + surrounding move context
  3. stats.json                    — dataset statistics

Filters applied:
  - Rows without 'features' or empty 'expert_commentary' are dropped
  - Boilerplate / too-short commentary is dropped
  - Duplicate commentary across different positions is flagged
  - Game-level train/val/test split IDs are assigned (no same-game leakage)

Usage:
  python preprocess_commentary.py \\
    --input training_data/features_full.jsonl \\
    --output-dir training_data/ \\
    --test-fraction 0.1 \\
    --val-fraction 0.1 \\
    --min-commentary-length 10 \\
    --context-window 6
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("preprocess_commentary")


# ---------------------------------------------------------------------------
# Quality filters
# ---------------------------------------------------------------------------

# Patterns that indicate boilerplate, not real expert analysis
BOILERPLATE_PATTERNS = [
    re.compile(r"^\s*\.\.\.\s*$"),                    # just ellipsis
    re.compile(r"^\s*\?\s*$"),                        # just question marks
    re.compile(r"^\d+[\.\s]*$"),                      # just a move number
    re.compile(r"^(red|black)\s+(wins?|loses?)\s*$", re.I),  # trivial outcome
]

# Piece code → human name for synthetic commentary
PIECE_NAMES = {
    "k": "King", "a": "Advisor", "e": "Elephant", "b": "Elephant",
    "h": "Horse", "n": "Horse", "r": "Chariot", "c": "Cannon",
    "p": "Pawn",
}


def is_boilerplate(text: str) -> bool:
    """Check if commentary is boilerplate that should be filtered out."""
    return any(p.search(text) for p in BOILERPLATE_PATTERNS)


def classify_commentary(
    row: dict,
    total_moves: int,
) -> str:
    """
    Classify an anchor row into one of three buckets:
      - 'anchor_commentary'            — standard per-move expert comment
      - 'sequence_sensitive_commentary' — comment likely summarizes a run of moves
      - 'opening_commentary'            — comment about the opening setup
    """
    move_index = row.get("move_index", 0)
    commentary = row.get("expert_commentary", "")

    # Opening: first 6 half-moves
    if move_index < 6:
        return "opening_commentary"

    # Sequence-sensitive heuristic: commentary references multiple moves or "after"
    sequence_signals = [
        "after", "following", "sequence", "series of",
        "previous move", "last few moves", "in response to",
        "continues the plan", "building on",
    ]
    commentary_lower = commentary.lower()
    if any(signal in commentary_lower for signal in sequence_signals):
        return "sequence_sensitive_commentary"

    return "anchor_commentary"


# ---------------------------------------------------------------------------
# Synthetic commentary generation
# ---------------------------------------------------------------------------

def _score_description(score: float | int | None) -> str:
    """Human-readable evaluation description from centipawn score."""
    if score is None:
        return "unclear position"
    s = float(score)
    if abs(s) < 30:
        return "roughly equal position"
    elif abs(s) < 100:
        side = "Red" if s > 0 else "Black"
        return f"slight advantage for {side}"
    elif abs(s) < 300:
        side = "Red" if s > 0 else "Black"
        return f"clear advantage for {side}"
    elif abs(s) < 700:
        side = "Red" if s > 0 else "Black"
        return f"winning advantage for {side}"
    else:
        side = "Red" if s > 0 else "Black"
        return f"decisive advantage for {side}"


def _classify_move_description(classification: dict) -> str:
    """Describe the move's tactical/strategic nature from classification data."""
    cat = classification.get("category", "normal")
    is_check = classification.get("is_check", False)
    is_capture = classification.get("is_capture", False)

    parts = []
    if is_check:
        parts.append("delivers check")
    if is_capture:
        captured = classification.get("captured_piece", "")
        piece_name = PIECE_NAMES.get(captured.lower(), "piece") if captured else "piece"
        parts.append(f"captures a {piece_name}")

    if cat == "brilliant":
        parts.append("a brilliant move")
    elif cat == "best":
        parts.append("the engine's top choice")
    elif cat == "excellent":
        parts.append("an excellent move")
    elif cat == "good":
        parts.append("a solid move")
    elif cat == "inaccuracy":
        parts.append("a slight inaccuracy")
    elif cat == "mistake":
        parts.append("a mistake")
    elif cat == "blunder":
        parts.append("a serious blunder")

    return ", ".join(parts) if parts else "a normal developing move"


def generate_synthetic_commentary(row: dict) -> str | None:
    """Generate template-based commentary from engine features.

    Returns a synthetic explanation string, or None if insufficient data.
    """
    features = row.get("features", {})
    if not features:
        return None

    search = features.get("search_metrics", {})
    classification = features.get("classification", {})
    position = features.get("position_analysis", {})
    move_meta = features.get("move_metadata", {})
    alternatives = features.get("alternatives", [])

    score = search.get("score")
    pv = search.get("principal_variation", [])
    move_str = move_meta.get("move_str", row.get("move_played", "?"))

    # Need at least a score to generate anything useful
    if score is None:
        return None

    parts = []

    # 1. Move description
    move_desc = _classify_move_description(classification)
    parts.append(f"This move ({move_str}) is {move_desc}.")

    # 2. Evaluation
    eval_desc = _score_description(score)
    parts.append(f"The engine evaluates this as {score:+d} centipawns ({eval_desc}).")

    # 3. Principal variation (what the engine expects next)
    if pv and len(pv) >= 2:
        pv_preview = " ".join(pv[:4])
        parts.append(f"The engine's expected continuation is: {pv_preview}.")

    # 4. Alternatives (if any are significantly different)
    if alternatives and len(alternatives) >= 1:
        alt = alternatives[0]
        alt_move = alt.get("move_str", alt.get("move", "?"))
        alt_score = alt.get("score")
        if alt_score is not None and score is not None:
            diff = abs(score - alt_score)
            if diff > 50:
                parts.append(
                    f"An alternative was {alt_move} (eval {alt_score:+d}), "
                    f"but the played move is {diff} centipawns better."
                )
            elif diff < 15:
                parts.append(
                    f"{alt_move} was also playable (eval {alt_score:+d}), "
                    f"nearly equal to the move played."
                )

    # 5. Material context
    material = position.get("material_balance")
    if material is not None and material != 0:
        side = "Red" if material > 0 else "Black"
        parts.append(f"Material balance: {side} is up {abs(material)} points.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Game-level splitting
# ---------------------------------------------------------------------------

def assign_splits(
    game_ids: list[str],
    test_fraction: float = 0.1,
    val_fraction: float = 0.1,
    seed: int = 42,
) -> dict[str, str]:
    """
    Assign each game_id to 'train', 'val', or 'test'.
    Returns {game_id: split_name}.
    """
    rng = random.Random(seed)
    ids = sorted(set(game_ids))
    rng.shuffle(ids)

    n_test = max(1, int(len(ids) * test_fraction))
    n_val = max(1, int(len(ids) * val_fraction))

    splits = {}
    for i, gid in enumerate(ids):
        if i < n_test:
            splits[gid] = "test"
        elif i < n_test + n_val:
            splits[gid] = "val"
        else:
            splits[gid] = "train"

    return splits


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def load_raw(input_path: str) -> list[dict]:
    """Load engine-analyzed JSONL, skipping metadata headers."""
    rows = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"Skipping malformed line {line_num}")
                continue
            if obj.get("_meta"):
                continue
            rows.append(obj)
    return rows


def preprocess(args):
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Load ---
    logger.info(f"Loading: {input_path}")
    rows = load_raw(str(input_path))
    logger.info(f"Loaded {len(rows)} total rows")

    # --- Filter to anchors (rows with real commentary) ---
    anchors = []
    stats = {
        "total_rows": len(rows),
        "skipped_no_features": 0,
        "skipped_no_commentary": 0,
        "skipped_too_short": 0,
        "skipped_boilerplate": 0,
        "skipped_duplicate": 0,
    }

    seen_commentary: set[str] = set()

    for row in rows:
        features = row.get("features")
        commentary = row.get("expert_commentary")

        if not features:
            stats["skipped_no_features"] += 1
            continue

        if not commentary or not commentary.strip():
            stats["skipped_no_commentary"] += 1
            continue

        commentary = commentary.strip()

        if len(commentary) < args.min_commentary_length:
            stats["skipped_too_short"] += 1
            continue

        if is_boilerplate(commentary):
            stats["skipped_boilerplate"] += 1
            continue

        # Deduplicate exact commentary across positions
        if commentary in seen_commentary:
            stats["skipped_duplicate"] += 1
            continue
        seen_commentary.add(commentary)

        anchors.append(row)

    logger.info(f"Anchors after filtering: {len(anchors)}")
    stats["anchors"] = len(anchors)

    if not anchors:
        logger.error("No valid anchors found. Check input data.")
        sys.exit(1)

    # --- Classify buckets ---
    bucket_counts: Counter = Counter()
    for row in anchors:
        total_moves = row.get("total_moves", 100)
        bucket = classify_commentary(row, total_moves)
        row["commentary_type"] = bucket
        bucket_counts[bucket] += 1

    for bucket, count in bucket_counts.most_common():
        logger.info(f"  {bucket}: {count}")
    stats["buckets"] = dict(bucket_counts)

    # --- Game-level split ---
    game_ids = [row.get("game_id", "unknown") for row in anchors]
    splits = assign_splits(game_ids, args.test_fraction, args.val_fraction)

    split_counts: Counter = Counter()
    for row in anchors:
        gid = row.get("game_id", "unknown")
        row["split"] = splits.get(gid, "train")
        split_counts[row["split"]] += 1

    for split, count in split_counts.most_common():
        logger.info(f"  split={split}: {count} rows")
    stats["splits"] = dict(split_counts)

    # --- Build context sidecar ---
    # Index all rows by game_id + move_index for context lookups
    game_moves: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in rows:
        gid = row.get("game_id", "unknown")
        idx = row.get("move_index", 0)
        game_moves[gid][idx] = row

    # --- Write outputs ---

    # 1. commentary_anchor.jsonl — v1 training set
    anchor_path = output_dir / "commentary_anchor.jsonl"
    with open(anchor_path, "w", encoding="utf-8") as f:
        for row in anchors:
            entry = {
                "features": row["features"],
                "expert_commentary": row["expert_commentary"],
                "move_history": row.get("move_history", []),
                "game_id": row.get("game_id"),
                "move_index": row.get("move_index"),
                "total_moves": row.get("total_moves"),
                "commentary_type": row.get("commentary_type"),
                "split": row.get("split"),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"Written: {anchor_path} ({len(anchors)} rows)")

    # 2. commentary_anchor_context.jsonl — v2 sidecar with surrounding context
    context_path = output_dir / "commentary_anchor_context.jsonl"
    context_count = 0
    with open(context_path, "w", encoding="utf-8") as f:
        for row in anchors:
            gid = row.get("game_id", "unknown")
            idx = row.get("move_index", 0)
            window = args.context_window

            # Gather context: previous N moves' features + commentary
            context_moves = []
            for prev_idx in range(max(0, idx - window), idx):
                prev_row = game_moves[gid].get(prev_idx)
                if prev_row:
                    context_moves.append({
                        "move_index": prev_idx,
                        "move_str": prev_row.get("features", {}).get(
                            "move_metadata", {}
                        ).get("move_str", prev_row.get("move_played", "")),
                        "score": prev_row.get("features", {}).get(
                            "search_metrics", {}
                        ).get("score"),
                        "category": prev_row.get("features", {}).get(
                            "classification", {}
                        ).get("category"),
                        "expert_commentary": prev_row.get("expert_commentary"),
                    })

            entry = {
                "features": row["features"],
                "expert_commentary": row["expert_commentary"],
                "move_history": row.get("move_history", []),
                "context_moves": context_moves,
                "game_id": gid,
                "move_index": idx,
                "total_moves": row.get("total_moves"),
                "commentary_type": row.get("commentary_type"),
                "split": row.get("split"),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            context_count += 1
    logger.info(f"Written: {context_path} ({context_count} rows)")

    # 3. stats.json
    stats_path = output_dir / "preprocessing_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    logger.info(f"Written: {stats_path}")

    logger.info("Preprocessing complete")

    # --- Generate synthetic commentary if requested ---
    if getattr(args, "generate_synthetic", False):
        logger.info("Generating synthetic commentary for unlabelled moves...")
        synthetic_count = 0
        combined_path = output_dir / "commentary_combined.jsonl"

        # Re-split including ALL rows (human + synthetic)
        all_game_ids = [row.get("game_id", "unknown") for row in rows]
        all_splits = assign_splits(all_game_ids, args.test_fraction, args.val_fraction)

        with open(combined_path, "w", encoding="utf-8") as f:
            for row in rows:
                features = row.get("features")
                if not features:
                    continue

                gid = row.get("game_id", "unknown")
                split = all_splits.get(gid, "train")
                human_commentary = row.get("expert_commentary") or ""
                human_commentary = human_commentary.strip()

                # Determine source: human or synthetic
                is_human = (
                    len(human_commentary) >= args.min_commentary_length
                    and not is_boilerplate(human_commentary)
                )

                if is_human:
                    commentary = human_commentary
                    source = "human"
                else:
                    commentary = generate_synthetic_commentary(row)
                    if not commentary:
                        continue
                    source = "synthetic"
                    synthetic_count += 1

                entry = {
                    "features": features,
                    "expert_commentary": commentary,
                    "commentary_source": source,
                    "move_history": row.get("move_history", []),
                    "game_id": gid,
                    "move_index": row.get("move_index"),
                    "total_moves": row.get("total_moves"),
                    "split": split,
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        total_combined = len(anchors) + synthetic_count
        logger.info(
            f"Written: {combined_path} "
            f"({total_combined} rows: {len(anchors)} human, {synthetic_count} synthetic)"
        )
        stats["synthetic_count"] = synthetic_count
        stats["combined_total"] = total_combined

        # Re-write stats with synthetic info
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Preprocess engine-analyzed JSONL into fine-tuning datasets"
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to engine-analyzed JSONL (output of generate_training_data.py)",
    )
    parser.add_argument(
        "--output-dir", default="training_data",
        help="Directory for output files (default: training_data/)",
    )
    parser.add_argument(
        "--min-commentary-length", type=int, default=10,
        help="Minimum character length for commentary (default: 10)",
    )
    parser.add_argument(
        "--test-fraction", type=float, default=0.1,
        help="Fraction of games for test split (default: 0.1)",
    )
    parser.add_argument(
        "--val-fraction", type=float, default=0.1,
        help="Fraction of games for validation split (default: 0.1)",
    )
    parser.add_argument(
        "--context-window", type=int, default=6,
        help="Number of preceding moves to include in context sidecar (default: 6)",
    )
    parser.add_argument(
        "--generate-synthetic",
        action="store_true",
        help="Generate synthetic commentary for moves without human labels (writes commentary_combined.jsonl)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducible splits (default: 42)",
    )

    args = parser.parse_args()
    preprocess(args)


if __name__ == "__main__":
    main()
