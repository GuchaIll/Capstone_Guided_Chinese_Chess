#!/usr/bin/env python3
"""
scrape_games.py — CLI for scraping annotated Xiangqi games
==========================================================

Crawls xqinenglish.com's *Games with English Commentaries* section,
extracts DhtmlXQ game data (moves + per-move expert commentary),
converts to FEN sequences, and writes JSONL training data.

Usage
-----
::

    # Full scrape — all annotated games
    python scrape_games.py --output data/raw/games/xqinenglish_games.jsonl

    # Quick test — first 5 games only
    python scrape_games.py --max-games 5 --output data/raw/games/test.jsonl

    # Only games with commentary, exclude uncommented moves
    python scrape_games.py --commentary-only --skip-uncommented

    # Custom rate limit & cache directory
    python scrape_games.py --rate-limit 2.0 --cache-dir data/cache/my_cache
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the pipeline package is importable
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from pipeline.loaders.game_scraper import GameScraper
from pipeline.loaders.dhtmlxq_parser import game_to_training_entries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scrape_games")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape annotated Xiangqi games from xqinenglish.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python scrape_games.py
  python scrape_games.py --max-games 10 --output test_games.jsonl
  python scrape_games.py --commentary-only --skip-uncommented
""",
    )
    parser.add_argument(
        "-o", "--output",
        default="data/raw/games/xqinenglish_games.jsonl",
        help="Output JSONL file path (default: data/raw/games/xqinenglish_games.jsonl)",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=None,
        help="Maximum number of games to scrape (default: unlimited)",
    )
    parser.add_argument(
        "--commentary-only",
        action="store_true",
        help="Skip games that have no expert commentary",
    )
    parser.add_argument(
        "--skip-uncommented",
        action="store_true",
        help="Exclude moves without commentary from output "
             "(only write moves that have expert text)",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/cache/xqinenglish_games",
        help="Directory for cached HTML (default: data/cache/xqinenglish_games)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.5,
        help="Seconds between HTTP requests (default: 1.5)",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Parse cached data and print stats without making network requests",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scraper = GameScraper(
        cache_dir=args.cache_dir,
        rate_limit=args.rate_limit,
        max_games=args.max_games,
        commentary_only=args.commentary_only,
    )

    if args.stats_only:
        _print_stats(scraper)
        return

    logger.info("Starting game scrape...")
    logger.info("  Output: %s", args.output)
    logger.info("  Max games: %s", args.max_games or "unlimited")
    logger.info("  Commentary only: %s", args.commentary_only)
    logger.info("  Skip uncommented moves: %s", args.skip_uncommented)

    stats = scraper.export_training_jsonl(
        output_path=args.output,
        include_uncommented=not args.skip_uncommented,
    )

    _print_summary(stats, args.output)


def _print_stats(scraper: GameScraper) -> None:
    """Quick stats from cached data (no network requests)."""
    total_games = 0
    total_moves = 0
    commented_moves = 0
    games_with_commentary = 0

    for game in scraper.scrape_all():
        total_games += 1
        total_moves += game.total_moves
        cm = game.commented_move_count
        commented_moves += cm
        if cm > 0:
            games_with_commentary += 1

    print(f"\n{'='*60}")
    print("GAME COLLECTION STATS")
    print(f"{'='*60}")
    print(f"  Total games:              {total_games}")
    print(f"  Total moves (plies):      {total_moves}")
    print(f"  Games with commentary:    {games_with_commentary}")
    print(f"  Moves with commentary:    {commented_moves}")
    if total_moves > 0:
        print(f"  Commentary coverage:      {commented_moves/total_moves*100:.1f}%")
    if total_games > 0:
        print(f"  Avg moves per game:       {total_moves/total_games:.1f}")
    print(f"{'='*60}\n")


def _print_summary(stats: dict, output_path: str) -> None:
    """Print final summary."""
    print(f"\n{'='*60}")
    print("SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"  Games scraped:            {stats['total_games']}")
    print(f"  Total moves:              {stats['total_moves']}")
    print(f"  Moves with commentary:    {stats['commented_moves']}")
    print(f"  Entries written:          {stats['written_entries']}")
    if stats["total_moves"] > 0:
        pct = stats["commented_moves"] / stats["total_moves"] * 100
        print(f"  Commentary coverage:      {pct:.1f}%")
    print(f"  Output file:              {output_path}")

    # File size
    p = Path(output_path)
    if p.exists():
        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"  File size:                {size_mb:.2f} MB")

    print(f"{'='*60}")
    print(
        "\nNext step: Feed this JSONL into the engine analysis pipeline:\n"
        "  python -m agent_orchestration.tools.generate_training_data \\\n"
        f"    --input {output_path} \\\n"
        "    --output training_data/features.jsonl \\\n"
        "    --depth 4\n"
    )


if __name__ == "__main__":
    main()
