"""Bridge subscriber — connects the LED system to the State Bridge via SSE.

Listens to the bridge's /state/events SSE stream and drives the physical
LEDs in response to game events.  Falls back to the existing CLI mode
with ``--mode cli``.

Usage on Raspberry Pi:
    python bridge_subscriber.py                           # bridge mode (default)
    python bridge_subscriber.py --bridge-url http://192.168.1.50:5003
    python bridge_subscriber.py --mode cli                # legacy interactive CLI
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s  %(message)s",
)
logger = logging.getLogger("bridge_subscriber")

# ── Import LED functions from the canonical ledsystem module ─────────
# These work only on Raspberry Pi with NeoPixel hardware.  When running
# off-Pi for testing we stub them out.
try:
    from ledsystem import (
        clear,
        set_square,
        show_position,
        parse_xiangqi_fen,
        get_moves,
        best_move_for_piece,
        highlight_opponent_move,
        pixels,
        BLUE,
        PURPLE,
        GREEN,
        RED,
    )

    HAS_LED = True
except ImportError:
    logger.warning("LED hardware not available — running in dry-run mode")
    HAS_LED = False

    def clear() -> None:  # type: ignore[misc]
        pass

    def set_square(r: int, c: int, color: tuple) -> None:  # type: ignore[misc]
        pass

    def show_position(board_state, selected=None, moves=None, best_move=None) -> None:  # type: ignore[misc]
        pass

    def parse_xiangqi_fen(fen_str: str):  # type: ignore[misc]
        rows = fen_str.split()[0].split("/")
        board = []
        for row in rows:
            expanded = []
            for ch in row:
                if ch.isdigit():
                    expanded.extend(["."] * int(ch))
                else:
                    expanded.append(ch)
            board.append(expanded)
        return board

    def get_moves(board_state, r, c):  # type: ignore[misc]
        return []

    def best_move_for_piece(board_state, r, c, moves):  # type: ignore[misc]
        return None

    BLUE = (0, 0, 255, 0)
    PURPLE = (180, 0, 255, 0)
    GREEN = (0, 255, 0, 0)
    RED = (255, 0, 0, 0)


# ── Algebraic square to (row, col) conversion ───────────────────────

def _sq_to_rc(sq: str) -> tuple[int, int] | None:
    """Convert algebraic square like 'e3' to (row, col).
    Column a=0..i=8, row is the digit (0-9)."""
    if len(sq) < 2:
        return None
    col = ord(sq[0]) - ord("a")
    try:
        row = int(sq[1:])
    except ValueError:
        return None
    if 0 <= row <= 9 and 0 <= col <= 8:
        return (row, col)
    return None


# ── SSE reader (stdlib only — no extra deps on Pi) ───────────────────

RECONNECT_DELAY = 2.0
MAX_RECONNECT_DELAY = 30.0


def sse_stream(url: str):
    """Yield parsed SSE data dicts from *url*.  Reconnects on failure."""
    delay = RECONNECT_DELAY
    while True:
        try:
            logger.info("Connecting to SSE stream at %s", url)
            req = Request(url, headers={"Accept": "text/event-stream"})
            resp = urlopen(req, timeout=None)  # noqa: S310 — trusted internal URL
            delay = RECONNECT_DELAY
            logger.info("SSE stream connected")
            buf = ""
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace")
                buf += line
                if buf.endswith("\n\n"):
                    for part in buf.strip().split("\n"):
                        if part.startswith("data: "):
                            payload = part[6:]
                            try:
                                yield json.loads(payload)
                            except json.JSONDecodeError:
                                logger.warning("Bad SSE payload: %s", payload[:120])
                    buf = ""
        except (URLError, OSError) as exc:
            logger.warning("SSE connection lost: %s — reconnecting in %.0fs", exc, delay)
        except Exception:
            logger.exception("Unexpected SSE error — reconnecting in %.0fs", delay)

        time.sleep(delay)
        delay = min(delay * 1.5, MAX_RECONNECT_DELAY)


# ── Event handlers ───────────────────────────────────────────────────

# Board state cache — updated on every FEN event
_board_state: list[list[str]] = []


def handle_fen_update(data: dict) -> None:
    """FEN changed (from engine or CV) — refresh LED board display."""
    global _board_state
    fen = data.get("fen", "")
    if not fen:
        return
    _board_state = parse_xiangqi_fen(fen)
    show_position(_board_state)
    logger.info("Board updated from %s: %s", data.get("source", "?"), fen[:40])


def handle_piece_selected(data: dict) -> None:
    """Engine replied with legal moves for a square — highlight them."""
    square = data.get("square", "")
    targets = data.get("targets", [])
    rc = _sq_to_rc(square)
    if rc is None or not _board_state:
        return
    r, c = rc
    # Convert target algebraic squares to (row, col)
    move_rcs = [_sq_to_rc(t) for t in targets]
    move_rcs = [m for m in move_rcs if m is not None]
    # Use local heuristic for best-move highlight
    best = best_move_for_piece(_board_state, r, c, move_rcs)
    show_position(_board_state, selected=(r, c), moves=move_rcs, best_move=best)
    logger.info("Piece selected at %s — %d legal moves", square, len(move_rcs))


def handle_move_made(data: dict) -> None:
    """A move was made — highlight from/to squares."""
    from_sq = data.get("from", "")
    to_sq = data.get("to", "")
    source = data.get("source", "")

    # If the opponent (AI or remote) moved, highlight in blue/purple
    if source in ("ai", "opponent"):
        from_rc = _sq_to_rc(from_sq)
        to_rc = _sq_to_rc(to_sq)
        if from_rc and to_rc:
            clear()
            set_square(from_rc[0], from_rc[1], BLUE)
            set_square(to_rc[0], to_rc[1], PURPLE)
            if HAS_LED:
                from ledsystem import pixels as px
                px.show()
            logger.info("Opponent move %s→%s highlighted", from_sq, to_sq)

    # Also update board from new FEN if present
    fen = data.get("fen", "")
    if fen:
        handle_fen_update({"fen": fen, "source": source})


def handle_best_move(data: dict) -> None:
    """Coaching agent recommended a best move — show green highlight."""
    from_sq = data.get("from", "")
    to_sq = data.get("to", "")
    to_rc = _sq_to_rc(to_sq)
    from_rc = _sq_to_rc(from_sq)
    if to_rc and _board_state:
        show_position(_board_state)  # redraw base
        set_square(to_rc[0], to_rc[1], GREEN)
        if from_rc:
            set_square(from_rc[0], from_rc[1], RED)
        if HAS_LED:
            from ledsystem import pixels as px
            px.show()
        logger.info("Best move highlighted: %s→%s", from_sq, to_sq)


def handle_led_command(data: dict) -> None:
    """CV system requests LED off (camera capture) or on."""
    cmd = data.get("command", "")
    if cmd == "off" or cmd == "clear":
        clear()
        logger.info("LEDs cleared (command: %s)", cmd)
    elif cmd == "on":
        # Restore current board
        if _board_state:
            show_position(_board_state)
            logger.info("LEDs restored")


EVENT_HANDLERS = {
    "fen_update": handle_fen_update,
    "cv_capture": handle_fen_update,
    "piece_selected": handle_piece_selected,
    "move_made": handle_move_made,
    "best_move": handle_best_move,
    "led_command": handle_led_command,
    "game_reset": lambda _: clear(),
}


# ── Main ─────────────────────────────────────────────────────────────

def run_bridge_mode(bridge_url: str) -> None:
    url = f"{bridge_url.rstrip('/')}/state/events"
    logger.info("Starting bridge subscriber — LED hardware: %s", HAS_LED)

    for event in sse_stream(url):
        event_type = event.get("type", "")
        event_data = event.get("data", {})
        handler = EVENT_HANDLERS.get(event_type)
        if handler:
            try:
                handler(event_data)
            except Exception:
                logger.exception("Error handling event %s", event_type)
        else:
            logger.debug("Unhandled event type: %s", event_type)


def main() -> None:
    parser = argparse.ArgumentParser(description="LED board bridge subscriber")
    parser.add_argument(
        "--mode", choices=["bridge", "cli"], default="bridge",
        help="bridge: listen to state bridge SSE; cli: interactive CLI (legacy)",
    )
    parser.add_argument(
        "--bridge-url", default="http://localhost:5003",
        help="State bridge base URL (default: http://localhost:5003)",
    )
    args = parser.parse_args()

    if args.mode == "cli":
        # Delegate to the existing CLI loop in ledsystem.py
        try:
            from ledsystem import main as cli_main  # type: ignore[attr-defined]
            cli_main()
        except ImportError:
            print("CLI mode requires ledsystem.py with NeoPixel hardware.", file=sys.stderr)
            sys.exit(1)
    else:
        run_bridge_mode(args.bridge_url)


if __name__ == "__main__":
    main()
