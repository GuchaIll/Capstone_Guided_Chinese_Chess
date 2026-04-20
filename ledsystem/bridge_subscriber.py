"""Bridge subscriber — connects the LED system to the State Bridge via SSE.

Listens to the bridge's /state/events SSE stream and drives the physical
LEDs by calling the LED server HTTP API (led_server.py on port 5000).

Usage on Raspberry Pi:
    python bridge_subscriber.py                           # bridge mode (default)
    python bridge_subscriber.py --bridge-url http://192.168.1.50:5003
    python bridge_subscriber.py --led-url http://localhost:5000
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

# ── LED server URL (led_server.py Flask app) ─────────────────────────
LED_URL = "http://localhost:5000"


def _led_post(path: str, body: dict | None = None) -> bool:
    """POST to the LED server. Returns True on success."""
    url = f"{LED_URL}{path}"
    data = json.dumps(body).encode() if body else b"{}"
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=5) as resp:  # noqa: S310
            return resp.status == 200
    except (URLError, OSError) as exc:
        logger.warning("LED server call failed: %s %s — %s", path, body, exc)
        return False


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


# ── Event handlers (call LED server HTTP API) ────────────────────────

_last_fen: str = ""


def handle_fen_update(data: dict) -> None:
    """FEN changed — store in LED server so subsequent move queries work."""
    global _last_fen
    fen = data.get("fen", "")
    if not fen:
        return
    _last_fen = fen
    _led_post("/fen", {"fen": fen})
    logger.info("Board updated from %s: %s", data.get("source", "?"), fen[:40])


def handle_piece_selected(data: dict) -> None:
    """Engine replied with legal moves for a square — show on LEDs."""
    square = data.get("square", "")
    rc = _sq_to_rc(square)
    if rc is None:
        return
    r, c = rc
    _led_post("/move", {"row": r, "col": c})
    logger.info("Piece selected at %s — moves shown", square)


def handle_move_made(data: dict) -> None:
    """A move was made — highlight from/to squares for opponent moves."""
    from_sq = data.get("from", "")
    to_sq = data.get("to", "")
    source = data.get("source", "")

    # Update FEN first if present
    fen = data.get("fen", "")
    if fen:
        handle_fen_update({"fen": fen, "source": source})

    # If the opponent (AI or remote) moved, highlight in blue/purple
    if source in ("ai", "opponent"):
        from_rc = _sq_to_rc(from_sq)
        to_rc = _sq_to_rc(to_sq)
        if from_rc and to_rc:
            _led_post("/opponent", {
                "from_r": from_rc[0], "from_c": from_rc[1],
                "to_r": to_rc[0], "to_c": to_rc[1],
            })
            logger.info("Opponent move %s→%s highlighted", from_sq, to_sq)


def handle_best_move(data: dict) -> None:
    """Coaching agent recommended a best move — show moves from that square."""
    from_sq = data.get("from", "")
    from_rc = _sq_to_rc(from_sq)
    if from_rc:
        _led_post("/move", {"row": from_rc[0], "col": from_rc[1]})
        logger.info("Best move highlighted from %s", from_sq)


def handle_led_command(data: dict) -> None:
    """CV system requests LED off (camera capture) or on."""
    cmd = data.get("command", "")
    if cmd == "off" or cmd == "clear":
        _led_post("/cv_pause", {})
        logger.info("LEDs paused (command: %s)", cmd)
    elif cmd == "on":
        _led_post("/cv_resume", {})
        logger.info("LEDs resumed")


def handle_game_reset(_data: dict) -> None:
    """Game reset — store starting FEN."""
    _led_post("/fen", {"fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"})
    _led_post("/cv_pause", {})  # clear LEDs
    _led_post("/cv_resume", {})
    logger.info("Game reset")


EVENT_HANDLERS = {
    "fen_update": handle_fen_update,
    "cv_capture": handle_fen_update,
    "piece_selected": handle_piece_selected,
    "move_made": handle_move_made,
    "best_move": handle_best_move,
    "led_command": handle_led_command,
    "game_reset": handle_game_reset,
}


# ── Main ─────────────────────────────────────────────────────────────

def run_bridge_mode(bridge_url: str, led_url: str) -> None:
    global LED_URL
    LED_URL = led_url
    url = f"{bridge_url.rstrip('/')}/state/events"
    logger.info("Starting bridge subscriber — LED server: %s", led_url)

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
    parser.add_argument(
        "--led-url", default="http://localhost:5000",
        help="LED server base URL (default: http://localhost:5000)",
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
        run_bridge_mode(args.bridge_url, args.led_url)


if __name__ == "__main__":
    main()
