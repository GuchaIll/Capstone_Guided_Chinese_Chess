#!/usr/bin/env python3
"""build_dataset.py — Assemble the LoRA fine-tuning dataset.

Merges two data sources into a unified JSONL file of decoder-only training
examples using the Qwen chat messages format:

  Source A — Expert-commentary moves (from the xqinenglish scraper)
    Input : finetunning/data/raw/games/xqinenglish_games.jsonl
    Filter: moves where expert_commentary is not None (delta filtering)
    Prompt: enriched FEN + move description → expert commentary

  Source B — Tactical pattern positions (JSON knowledge files)
    Input : server/web_scraper/knowledge/json/*.json
    Filter: valid FEN entries with a name/pattern label
    Prompt: enriched FEN + pattern name → pattern analysis

Usage
-----
    # Build and write dataset
    python finetunning/build_dataset.py

    # Dry-run: print 5 samples from each source, no file written
    python finetunning/build_dataset.py --dry-run

    # Custom paths
    python finetunning/build_dataset.py \\
        --games-jsonl finetunning/data/raw/games/xqinenglish_games.jsonl \\
        --knowledge-dir server/web_scraper/knowledge/json \\
        --output finetunning/data/dataset.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# Allow importing fen_features from the same finetunning/ directory
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from fen_features import enrich_fen, relations_to_text  # noqa: E402  (after sys.path tweak)


# ========================
#   PROMPT CONSTRUCTION
# ========================

_SYSTEM = (
    "You are an expert Xiangqi (Chinese Chess) coach. "
    "Analyze the position and provide clear, instructive commentary."
)


# ========================
#   SOURCE A — COMMENTARY
# ========================

def load_commentary_entries(jsonl_path: Path) -> list[dict]:
    """Load and delta-filter the commentary JSONL.

    Skips the metadata header line and moves with no expert commentary.
    Returns a list of raw entry dicts with 'expert_commentary' populated.
    """
    if not jsonl_path.exists():
        print(
            f"[WARNING] Commentary JSONL not found: {jsonl_path}\n"
            "  Run the scraper first:\n"
            "    cd server/web_scraper && python scrape_games.py "
            "--commentary-only --skip-uncommented "
            "--output ../../finetunning/data/raw/games/xqinenglish_games.jsonl",
            file=sys.stderr,
        )
        return []

    # Minimum commentary length to filter out trivial labels like "Draw", "Red won"
    _MIN_COMMENTARY_LEN = 20

    entries: list[dict] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Skip metadata header
            if obj.get("_meta"):
                continue
            # Delta filter: only moves with substantive expert commentary
            commentary = obj.get("expert_commentary") or ""
            if len(commentary) < _MIN_COMMENTARY_LEN:
                continue
            entries.append(obj)

    return entries


def commentary_entry_to_messages(entry: dict) -> list[dict]:
    """Build a Qwen-format messages list from a commentary entry."""
    fen = entry.get("fen", "")
    enriched = enrich_fen(fen) if fen else f"FEN: {fen}"
    rels = relations_to_text(fen) if fen else "(none)"

    move_str = entry.get("move_str", "?")
    side = entry.get("side", "?")
    game_title = entry.get("game_title") or "Unknown game"
    event = entry.get("event") or ""
    commentary = (entry.get("expert_commentary") or "").strip()

    event_suffix = f" | {event}" if event else ""

    user_content = (
        f"[POSITION]\n{enriched}\n"
        f"[RELATIONS]\n{rels}\n"
        f"Move played: {move_str} ({side} to move)\n"
        f"Game: {game_title}{event_suffix}\n"
        "Explain this move."
    )

    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": commentary},
    ]


# ========================
#   SOURCE B — TACTICS/PATTERNS
# ========================

# JSON knowledge files to include (relative to knowledge-dir)
_KNOWLEDGE_FILES = [
    "basic-checkmates.json",
    "advanced-checkmates.json",
    "endgames_all.json",
    "opening-repertoire.json",
    "meng-ru-shen-ji.json",
]


def load_knowledge_entries(knowledge_dir: Path) -> list[dict]:
    """Load entries from all JSON knowledge files.

    Deduplicates on FEN (first occurrence wins, keeping richest label).
    Skips entries with no FEN or no name.
    """
    seen_fens: set[str] = set()
    entries: list[dict] = []

    for filename in _KNOWLEDGE_FILES:
        fpath = knowledge_dir / filename
        if not fpath.exists():
            print(f"[WARNING] Knowledge file not found, skipping: {fpath}", file=sys.stderr)
            continue

        # Use utf-8-sig to transparently handle files with a UTF-8 BOM
        with open(fpath, encoding="utf-8-sig") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as exc:
                print(f"[WARNING] JSON parse error in {fpath}: {exc}", file=sys.stderr)
                continue

        if not isinstance(data, list):
            continue

        for item in data:
            fen = item.get("fen", "").strip()
            name = item.get("name", "").strip()
            if not fen or not name:
                continue
            # FEN dedup: normalise by stripping trailing metadata
            fen_key = fen.split()[0]  # board-only part
            if fen_key in seen_fens:
                continue
            seen_fens.add(fen_key)
            entries.append({
                "fen": fen,
                "name": name,
                "best_move": item.get("bestMove", "").strip(),
                "result": item.get("result", ""),
            })

    return entries


def knowledge_entry_to_messages(entry: dict) -> list[dict]:
    """Build a Qwen-format messages list from a knowledge/pattern entry."""
    fen = entry.get("fen", "")
    enriched = enrich_fen(fen) if fen else f"FEN: {fen}"
    rels = relations_to_text(fen) if fen else "(none)"

    pattern_name = entry.get("name", "Unknown pattern")
    best_move = entry.get("best_move", "")

    best_move_suffix = (
        f" The strongest continuation is {best_move}."
        if best_move
        else ""
    )

    user_content = (
        f"[POSITION]\n{enriched}\n"
        f"[RELATIONS]\n{rels}\n"
        "Identify the key pattern or kill technique in this position."
    )
    assistant_content = (
        f"This position demonstrates {pattern_name}.{best_move_suffix}"
    )

    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]


# ========================
#   DATASET ASSEMBLY
# ========================

def build_dataset(
    games_jsonl: Path,
    knowledge_dir: Path,
    output_path: Path,
    seed: int = 42,
    val_ratio: float = 0.1,
    dry_run: bool = False,
) -> dict:
    """Merge both sources, shuffle, split train/val, and write JSONL files.

    Returns summary stats dict.
    """
    print("Loading commentary entries (Source A)...")
    commentary_raw = load_commentary_entries(games_jsonl)
    print(f"  {len(commentary_raw)} commentary moves loaded")

    print("Loading knowledge/pattern entries (Source B)...")
    knowledge_raw = load_knowledge_entries(knowledge_dir)
    print(f"  {len(knowledge_raw)} tactical patterns loaded")

    # Build text examples
    all_examples: list[dict] = []

    for entry in commentary_raw:
        try:
            msgs = commentary_entry_to_messages(entry)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARNING] Skipping commentary entry: {exc}", file=sys.stderr)
            continue
        all_examples.append({"messages": msgs, "_source": "commentary"})

    for entry in knowledge_raw:
        try:
            msgs = knowledge_entry_to_messages(entry)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARNING] Skipping knowledge entry: {exc}", file=sys.stderr)
            continue
        all_examples.append({"messages": msgs, "_source": "pattern"})

    # Shuffle
    rng = random.Random(seed)
    rng.shuffle(all_examples)

    # Train / val split
    n_val = max(1, int(len(all_examples) * val_ratio))
    val_examples = all_examples[:n_val]
    train_examples = all_examples[n_val:]

    stats = {
        "total": len(all_examples),
        "commentary": sum(1 for e in all_examples if e["_source"] == "commentary"),
        "pattern": sum(1 for e in all_examples if e["_source"] == "pattern"),
        "train": len(train_examples),
        "val": len(val_examples),
    }

    if dry_run:
        _print_dry_run(commentary_raw, knowledge_raw, stats)
        return stats

    # Write train and val files
    output_path.parent.mkdir(parents=True, exist_ok=True)
    train_path = output_path.with_suffix(".train.jsonl")
    val_path = output_path.with_suffix(".val.jsonl")

    def _write(path: Path, examples: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for ex in examples:
                # Strip internal _source field before writing
                f.write(json.dumps({"messages": ex["messages"]}, ensure_ascii=False) + "\n")

    _write(train_path, train_examples)
    _write(val_path, val_examples)

    _print_summary(stats, train_path, val_path)
    return stats


def _print_dry_run(
    commentary_raw: list[dict],
    knowledge_raw: list[dict],
    stats: dict,
) -> None:
    print("\n" + "=" * 60)
    print("DRY RUN — 3 samples from each source")
    print("=" * 60)

    print("\n--- Commentary samples (Source A) ---")
    for entry in commentary_raw[:3]:
        for msg in commentary_entry_to_messages(entry):
            print(f"[{msg['role']}] {msg['content'][:200]}")
        print("-" * 40)

    print("\n--- Pattern samples (Source B) ---")
    for entry in knowledge_raw[:3]:
        for msg in knowledge_entry_to_messages(entry):
            print(f"[{msg['role']}] {msg['content'][:200]}")
        print("-" * 40)

    _print_summary(stats)


def _print_summary(
    stats: dict,
    train_path: Path | None = None,
    val_path: Path | None = None,
) -> None:
    print("\n" + "=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)
    print(f"  Total examples:   {stats['total']}")
    print(f"  Commentary moves: {stats['commentary']}")
    print(f"  Tactical patterns:{stats['pattern']}")
    print(f"  Train split:      {stats['train']}")
    print(f"  Val split:        {stats['val']}")
    if train_path:
        print(f"  Train file:       {train_path}")
    if val_path:
        print(f"  Val file:         {val_path}")
    print("=" * 60)


# ========================
#   CLI ENTRY POINT
# ========================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Xiangqi LoRA fine-tuning dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--games-jsonl",
        default="finetunning/data/raw/games/xqinenglish_games.jsonl",
        help="Commentary JSONL from scraper",
    )
    parser.add_argument(
        "--knowledge-dir",
        default="server/web_scraper/knowledge/json",
        help="Directory containing JSON knowledge files",
    )
    parser.add_argument(
        "--output",
        default="finetunning/data/dataset.jsonl",
        help="Output JSONL base path (.train.jsonl and .val.jsonl will be created)",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.1,
        help="Fraction of data to use for validation (default: 0.1)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for shuffle (default: 42)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print samples and stats without writing files",
    )
    args = parser.parse_args()

    # Resolve paths relative to repo root (script may be called from anywhere)
    repo_root = Path(__file__).resolve().parent.parent

    build_dataset(
        games_jsonl=repo_root / args.games_jsonl,
        knowledge_dir=repo_root / args.knowledge_dir,
        output_path=repo_root / args.output,
        seed=args.seed,
        val_ratio=args.val_ratio,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
