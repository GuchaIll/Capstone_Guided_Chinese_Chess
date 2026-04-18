"""
Training Data Generator
=======================

Processes expert-commentated Xiangqi games through the engine's analysis
pipeline to produce structured JSONL training data for LLM fine-tuning.

Input Format (game record file, .jsonl):
  Each line is: {"fen": "...", "move": "e3e4", "commentary": "..."}
  OR a full game: {"moves": [{"fen": "...", "move": "...", "commentary": "..."}, ...]}

Output Format (.jsonl):
  Each line is a complete MoveFeatureVector + expert_commentary,
  including position analysis, search metrics, relational mappings,
  and move classification.

Usage (run from server/ directory):
  python -m agent_orchestration.tools.generate_training_data \\
    --input web_scraper/data/raw/games/xqinenglish_games.jsonl \\
    --output training_data/features.jsonl \\
    --depth 4

  OR run the script directly from any directory:
  python server/agent_orchestration/tools/generate_training_data.py \\
    --input server/web_scraper/data/raw/games/xqinenglish_games.jsonl \\
    --output training_data/features.jsonl

Prerequisites:
  - Engine running at ws://localhost:8080/ws
  - pip install websockets
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Add parent dirs to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    import websockets
except ImportError:
    print("ERROR: 'websockets' package required. Install with: pip install websockets")
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("training_data_generator")


# ========================
#     DATA MODELS
# ========================

class GameRecord:
    """A single game as a list of position-move-commentary triples."""

    def __init__(self, game_id: str = "unknown"):
        self.game_id = game_id
        self.moves: list[dict[str, Any]] = []

    def add_move(self, fen: str, move_str: str, commentary: Optional[str] = None):
        self.moves.append({
            "fen": fen,
            "move_str": move_str,
            "expert_commentary": commentary,
        })


# ========================
#     FILE PARSERS
# ========================

def parse_jsonl_game(filepath: str) -> list[GameRecord]:
    """Parse a JSONL file where each line is a move entry or a full game.

    Handles multiple formats:
    - Full game:  ``{"moves": [...]}``
    - Per-move:   ``{"fen": "...", "move_str": "...", "expert_commentary": "..."}``
    - New game:   ``{"new_game": true}`` or ``{"game_id": "..."}``
    - Meta:       ``{"_meta": true, ...}``  (header line — skipped)

    Game boundaries in per-move format are detected by:
    - ``game_title`` field changing between entries
    - ``move_index`` resetting to 0
    - ``new_game`` / ``game_id`` marker lines
    """
    records: list[GameRecord] = []
    current_game = GameRecord(game_id=Path(filepath).stem)
    current_game_title: Optional[str] = None

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping line {line_num}: {e}")
                continue

            # Skip metadata header lines
            if entry.get("_meta"):
                continue

            # Full game format: {"moves": [...]}
            if "moves" in entry:
                if current_game.moves:
                    records.append(current_game)
                    current_game = GameRecord(game_id=Path(filepath).stem)
                    current_game_title = None
                game = GameRecord(game_id=f"{Path(filepath).stem}_game{len(records)+1}")
                for mv in entry["moves"]:
                    game.add_move(
                        fen=mv.get("fen", ""),
                        move_str=mv.get("move", mv.get("move_str", "")),
                        commentary=mv.get("commentary", mv.get("expert_commentary")),
                    )
                records.append(game)
            # Per-move format: {"fen": "...", "move_str": "..."}
            elif "fen" in entry and ("move" in entry or "move_str" in entry):
                # Detect game boundary: game_title changed or move_index reset
                entry_title = entry.get("game_title")
                entry_move_idx = entry.get("move_index")
                is_new_game = False

                if entry_title and current_game_title and entry_title != current_game_title:
                    is_new_game = True
                elif entry_move_idx == 0 and current_game.moves:
                    is_new_game = True

                if is_new_game and current_game.moves:
                    records.append(current_game)
                    current_game = GameRecord(
                        game_id=entry_title or f"{Path(filepath).stem}_game{len(records)+1}"
                    )

                current_game_title = entry_title
                if not current_game.game_id or current_game.game_id == Path(filepath).stem:
                    if entry_title:
                        current_game.game_id = entry_title

                move_str = entry.get("move", entry.get("move_str", ""))
                current_game.add_move(
                    fen=entry["fen"],
                    move_str=move_str,
                    commentary=entry.get("commentary", entry.get("expert_commentary")),
                )
            # New game marker
            elif "new_game" in entry or "game_id" in entry:
                if current_game.moves:
                    records.append(current_game)
                current_game = GameRecord(
                    game_id=entry.get("game_id", f"{Path(filepath).stem}_game{len(records)+1}")
                )
                current_game_title = None

    # Don't forget the last game
    if current_game.moves:
        records.append(current_game)

    return records


def parse_move_list(filepath: str) -> list[GameRecord]:
    """Parse a simple move list file (one move per line, FEN tab-separated)."""
    game = GameRecord(game_id=Path(filepath).stem)

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                game.add_move(
                    fen=parts[0],
                    move_str=parts[1],
                    commentary=parts[2] if len(parts) > 2 else None,
                )

    return [game] if game.moves else []


# ========================
#     ENGINE MANAGEMENT
# ========================

import subprocess as _subprocess
import signal
import urllib.request
import urllib.error

# Known locations of the engine binary (relative to project root)
_ENGINE_BINARY_CANDIDATES = [
    "target/release/Chinese_Chess_Engine.exe",
    "target/release/Chinese_Chess_Engine",
    "target/debug/Chinese_Chess_Engine.exe",
    "target/debug/Chinese_Chess_Engine",
]


def _find_project_root() -> Optional[Path]:
    """Walk up from this file to find the Cargo.toml project root."""
    d = Path(__file__).resolve().parent
    for _ in range(10):
        if (d / "Cargo.toml").exists():
            return d
        d = d.parent
    return None


def _find_engine_binary() -> Optional[Path]:
    """Locate the compiled engine binary."""
    root = _find_project_root()
    if not root:
        return None
    for candidate in _ENGINE_BINARY_CANDIDATES:
        p = root / candidate
        if p.exists():
            return p
    return None


def _engine_health_ok(port: int = 8080) -> bool:
    """Quick health-check against the engine HTTP endpoint."""
    try:
        r = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=3)
        return r.status == 200
    except Exception:
        return False


class EngineProcess:
    """Manages an engine subprocess for standalone training runs."""

    def __init__(self):
        self.proc: Optional[_subprocess.Popen] = None

    def start(self, port: int = 8080) -> bool:
        """Start the engine binary if not already running."""
        if _engine_health_ok(port):
            logger.info("Engine already running — reusing existing instance")
            return True

        binary = _find_engine_binary()
        if not binary:
            logger.error(
                "Engine binary not found. Build it first:\n"
                "  cargo build --release --manifest-path Engine/Cargo.toml\n"
                "Or start the engine manually / via Docker."
            )
            return False

        logger.info(f"Starting engine from {binary}")
        root = _find_project_root()
        log_dir = root / "Engine" / "logs" if root else None
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)

        self.proc = _subprocess.Popen(
            [str(binary)],
            cwd=str(root) if root else None,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.STDOUT,
            creationflags=_subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )

        # Wait for the health endpoint to become available
        for attempt in range(30):
            if self.proc.poll() is not None:
                logger.error(f"Engine exited immediately with code {self.proc.returncode}")
                return False
            if _engine_health_ok(port):
                logger.info(f"Engine ready (took ~{attempt}s)")
                return True
            time.sleep(1)

        logger.error("Engine did not become healthy within 30 seconds")
        self.stop()
        return False

    def stop(self):
        """Terminate the engine subprocess."""
        if self.proc and self.proc.poll() is None:
            logger.info("Stopping engine subprocess")
            if sys.platform == "win32":
                self.proc.terminate()
            else:
                self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=5)
            except _subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


# ========================
#     ENGINE INTERFACE
# ========================

class AnalysisClient:
    """WebSocket client for the engine's batch_analyze endpoint."""

    def __init__(self, url: str = "ws://localhost:8080/ws", timeout: float = 120.0):
        self.url = url
        self.timeout = timeout
        self.ws = None

    async def connect(self):
        """Connect to the engine WebSocket."""
        logger.info(f"Connecting to engine at {self.url}")
        try:
            self.ws = await websockets.connect(
                self.url,
                max_size=50 * 1024 * 1024,
                open_timeout=30,
                ping_timeout=60,
                close_timeout=10,
            )
        except TypeError:
            # Older websockets versions don't support open_timeout
            self.ws = await asyncio.wait_for(
                websockets.connect(self.url, max_size=50 * 1024 * 1024),
                timeout=30,
            )
        # Read initial state message (engine sends state on connect)
        try:
            init_msg = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            init_data = json.loads(init_msg)
            logger.info(f"Connected. Initial state: side={init_data.get('side_to_move', '?')}")
        except asyncio.TimeoutError:
            logger.warning("No initial state message received (engine may be busy). Continuing...")
        except Exception as e:
            logger.warning(f"Could not parse initial message: {e}. Continuing...")

    async def disconnect(self):
        """Close the connection."""
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def analyze_position(self, fen: str, difficulty: int = 4) -> dict[str, Any]:
        """Analyze a single position."""
        msg = {
            "type": "analyze_position",
            "fen": fen,
            "difficulty": difficulty,
        }
        await self.ws.send(json.dumps(msg))
        response = await asyncio.wait_for(self.ws.recv(), timeout=self.timeout)
        return json.loads(response)

    async def batch_analyze(
        self,
        moves: list[dict[str, Any]],
        difficulty: int = 4,
    ) -> dict[str, Any]:
        """Send a batch of FEN+move pairs for analysis."""
        msg = {
            "type": "batch_analyze",
            "moves": moves,
            "difficulty": difficulty,
        }
        await self.ws.send(json.dumps(msg))
        response = await asyncio.wait_for(self.ws.recv(), timeout=self.timeout)
        return json.loads(response)


# ========================
#     TRAINING PIPELINE
# ========================

async def process_game(
    client: AnalysisClient,
    game: GameRecord,
    depth: int,
    output_file,
) -> int:
    """Process a single game through the engine and write features to output."""
    logger.info(f"Processing game '{game.game_id}' ({len(game.moves)} moves)")

    # Send as batch for efficiency
    batch_entries = game.moves

    try:
        result = await client.batch_analyze(batch_entries, difficulty=depth)
    except asyncio.TimeoutError:
        logger.error(f"Timeout processing game '{game.game_id}'. Falling back to per-move analysis.")
        # Fallback: process moves individually
        return await process_game_sequential(client, game, depth, output_file)
    except Exception as e:
        logger.error(f"Error processing game '{game.game_id}': {e}")
        return 0

    if result.get("type") == "error":
        logger.error(f"Engine error: {result.get('message')}")
        return 0

    results = result.get("results", [])
    written = 0

    for i, entry in enumerate(results):
        if "error" in entry:
            logger.warning(f"  Move {i+1}: {entry['error']}")
            continue

        # Add game metadata
        entry["game_id"] = game.game_id
        entry["move_index"] = i
        entry["total_moves"] = len(game.moves)

        # Write JSONL line
        line = json.dumps(entry, ensure_ascii=False)
        output_file.write(line + "\n")
        written += 1

    logger.info(f"  Written {written}/{len(game.moves)} move features")
    return written


async def process_game_sequential(
    client: AnalysisClient,
    game: GameRecord,
    depth: int,
    output_file,
) -> int:
    """Process moves one at a time (fallback for large games)."""
    written = 0
    for i, mv in enumerate(game.moves):
        try:
            result = await client.analyze_position(mv["fen"], difficulty=depth)
            if result.get("type") == "error":
                logger.warning(f"  Move {i+1}: {result.get('message')}")
                continue

            entry = {
                "features": result.get("features", {}),
                "expert_commentary": mv.get("expert_commentary"),
                "game_id": game.game_id,
                "move_index": i,
                "move_played": mv["move_str"],
                "total_moves": len(game.moves),
            }

            line = json.dumps(entry, ensure_ascii=False)
            output_file.write(line + "\n")
            written += 1

        except Exception as e:
            logger.warning(f"  Move {i+1} error: {e}")

    return written


async def run_pipeline(args):
    """Main pipeline: parse input, connect to engine, process games, write output."""
    # Parse input files
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    logger.info(f"Parsing input: {input_path}")

    if input_path.suffix == ".jsonl":
        games = parse_jsonl_game(str(input_path))
    elif input_path.suffix in (".tsv", ".txt"):
        games = parse_move_list(str(input_path))
    else:
        logger.error(f"Unsupported input format: {input_path.suffix}")
        return

    if not games:
        logger.error("No games found in input file")
        return

    total_moves = sum(len(g.moves) for g in games)
    logger.info(f"Found {len(games)} game(s), {total_moves} total moves")

    # Apply skip/limit filters
    if args.skip_games > 0:
        logger.info(f"Skipping first {args.skip_games} games")
        games = games[args.skip_games:]

    if args.max_games > 0:
        logger.info(f"Limiting to {args.max_games} games")
        games = games[:args.max_games]

    if not games:
        logger.error("No games remaining after filtering")
        return

    total_moves = sum(len(g.moves) for g in games)
    logger.info(f"Processing {len(games)} game(s), {total_moves} total moves")

    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Auto-start engine if needed
    engine_proc = EngineProcess()
    if not args.no_auto_start:
        if not engine_proc.start():
            logger.error("Could not start engine. Use --no-auto-start to skip auto-start.")
            return
    else:
        logger.info("Auto-start disabled — expecting engine at " + args.engine_url)

    # Connect to engine
    client = AnalysisClient(url=args.engine_url, timeout=args.timeout)
    try:
        await client.connect()
    except Exception as e:
        logger.error(f"Failed to connect to engine: {e}")
        logger.error("Make sure the engine is running at the specified URL")
        engine_proc.stop()
        return

    # Process games
    start_time = time.time()
    total_written = 0

    try:
        with open(output_path, "w", encoding="utf-8") as out_f:
            # Write metadata header as first line
            header = {
                "_meta": True,
                "generator": "xiangqi_training_data_pipeline",
                "engine_url": args.engine_url,
                "search_depth": args.depth,
                "input_file": str(input_path),
                "total_games": len(games),
                "total_moves": total_moves,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            out_f.write(json.dumps(header) + "\n")

            errors = 0
            for game_idx, game in enumerate(games, 1):
                try:
                    written = await process_game(client, game, args.depth, out_f)
                    total_written += written
                    if game_idx % 50 == 0:
                        elapsed = time.time() - start_time
                        logger.info(
                            f"Progress: {game_idx}/{len(games)} games, "
                            f"{total_written} features, {elapsed:.0f}s elapsed"
                        )
                except Exception as e:
                    errors += 1
                    logger.error(f"Game '{game.game_id}' failed: {e}")
                    if errors > 10:
                        logger.error("Too many consecutive errors, aborting.")
                        break
                    # Try to reconnect
                    try:
                        await client.disconnect()
                        await asyncio.sleep(1)
                        await client.connect()
                        logger.info("Reconnected to engine")
                    except Exception as re_err:
                        logger.error(f"Reconnect failed: {re_err}")
                        break

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await client.disconnect()
        engine_proc.stop()

    elapsed = time.time() - start_time
    logger.info(f"Pipeline complete: {total_written} features written in {elapsed:.1f}s")
    logger.info(f"Output: {output_path}")
    if total_written > 0:
        logger.info(f"Average: {elapsed/total_written:.2f}s per move")


# ========================
#     SAMPLE DATA GENERATOR
# ========================

def generate_sample_input(output_path: str):
    """Generate a sample input JSONL file for testing the pipeline."""
    # A simple opening sequence from starting position
    sample_moves = [
        {
            "fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
            "move_str": "h2e2",
            "expert_commentary": "Central cannon opening - the most popular first move in Xiangqi. Controls the central file and threatens the opponent's e6 pawn.",
        },
        {
            "fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C4/9/RNBAKABNR b - - 1 1",
            "move_str": "b9c7",
            "expert_commentary": "Screen horse defense - developing the knight to protect the central pawn. One of the most solid responses to the central cannon.",
        },
        {
            "fen": "r1bakabnr/9/1cn4c1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C4/9/RNBAKABNR w - - 2 2",
            "move_str": "b0c2",
            "expert_commentary": "Developing the knight. Both sides follow standard opening principles of piece development.",
        },
    ]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for mv in sample_moves:
            f.write(json.dumps(mv) + "\n")

    print(f"Sample input written to: {output_path}")


# ========================
#     CLI
# ========================

def main():
    parser = argparse.ArgumentParser(
        description="Generate LLM training data from expert-commentated Xiangqi games",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate sample input file
  python generate_training_data.py --generate-sample

  # Process a game file
  python generate_training_data.py \\
    --input games/expert_game.jsonl \\
    --output training_data/features.jsonl \\
    --depth 4

  # Custom engine URL
  python generate_training_data.py \\
    --input games/game.jsonl \\
    --output features.jsonl \\
    --engine-url ws://engine:8080/ws
        """,
    )
    parser.add_argument(
        "--input", "-i",
        help="Input game file (.jsonl or .tsv)",
    )
    parser.add_argument(
        "--output", "-o",
        default="training_data/features.jsonl",
        help="Output JSONL file (default: training_data/features.jsonl)",
    )
    parser.add_argument(
        "--depth", "-d",
        type=int,
        default=4,
        help="Engine search depth (default: 4)",
    )
    parser.add_argument(
        "--engine-url",
        default="ws://localhost:8080/ws",
        help="Engine WebSocket URL (default: ws://localhost:8080/ws)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Timeout per batch request in seconds (default: 120)",
    )
    parser.add_argument(
        "--generate-sample",
        action="store_true",
        help="Generate a sample input file for testing",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=0,
        help="Maximum number of games to process (0 = all, default: 0)",
    )
    parser.add_argument(
        "--skip-games",
        type=int,
        default=0,
        help="Number of games to skip from the start (default: 0)",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Don't auto-start the engine binary; expect it to be already running",
    )

    args = parser.parse_args()

    if args.generate_sample:
        sample_path = args.input or "training_data/sample_game.jsonl"
        generate_sample_input(sample_path)
        return

    if not args.input:
        parser.error("--input is required (or use --generate-sample)")

    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
