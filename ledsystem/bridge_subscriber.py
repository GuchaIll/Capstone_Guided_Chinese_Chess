"""Bridge subscriber — connects the LED system to the State Bridge via SSE.

Listens to the bridge's /state/events SSE stream and drives the physical
LEDs by calling the LED server HTTP API (led_server.py on port 5000).

Usage on Raspberry Pi:
    python bridge_subscriber.py                           # bridge mode (default)
    export STATE_BRIDGE_TOKEN=integration-bridge-token
    python bridge_subscriber.py --bridge-url http://192.168.1.50:5003
    python bridge_subscriber.py --led-url http://localhost:5000
    python bridge_subscriber.py --mode cli                # legacy interactive CLI
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

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


def sse_stream(url: str, bridge_token: str | None = None):
    """Yield parsed SSE data dicts from *url*.  Reconnects on failure."""
    delay = RECONNECT_DELAY
    while True:
        try:
            logger.info("Connecting to SSE stream at %s", url)
            req = Request(url, headers={"Accept": "text/event-stream"})
            if bridge_token:
                req.add_header("Authorization", f"Bearer {bridge_token}")
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
        except HTTPError as exc:
            if exc.code == 401:
                logger.warning(
                    "SSE connection lost: HTTP 401 Unauthorized — set "
                    "STATE_BRIDGE_TOKEN or pass --bridge-token to match the "
                    "bridge's auth token. Reconnecting in %.0fs",
                    delay,
                )
            else:
                logger.warning("SSE connection lost: %s — reconnecting in %.0fs", exc, delay)
        except (URLError, OSError) as exc:
            logger.warning("SSE connection lost: %s — reconnecting in %.0fs", exc, delay)
        except Exception:
            logger.exception("Unexpected SSE error — reconnecting in %.0fs", delay)

        time.sleep(delay)
        delay = min(delay * 1.5, MAX_RECONNECT_DELAY)


# ── Event handlers (call LED server HTTP API) ────────────────────────

_last_fen: str = ""
_startup_completed = False

# Startup zones hold: /zones is rendered immediately, then this single-shot
# timer clears the LEDs after STARTUP_HOLD_SECONDS *unless* a real
# led_player_turn or led_engine_turn arrives first and cancels it.
STARTUP_HOLD_SECONDS = 20.0
_startup_timer: threading.Timer | None = None
_startup_timer_lock = threading.Lock()
_RESET_ZONE_REASONS = {"engine_reset", "websocket_reset"}


def _cancel_startup_timer(reason: str = "") -> bool:
    """Cancel the pending startup-zones timer if one is running."""
    global _startup_timer
    with _startup_timer_lock:
        timer = _startup_timer
        _startup_timer = None
    if timer is None:
        return False
    timer.cancel()
    if reason:
        logger.info("Startup zones hold cancelled (%s)", reason)
    return True


def _on_startup_hold_expired() -> None:
    """Fire when STARTUP_HOLD_SECONDS elapses without a real LED overlay."""
    global _startup_timer
    with _startup_timer_lock:
        _startup_timer = None
    _led_post("/clear", {})
    logger.info("Startup zones hold elapsed; LEDs cleared")


def _start_zones_hold(reason: str) -> None:
    """Show the startup zones scene and keep it visible until pre-empted or expired."""
    global _startup_timer

    _cancel_startup_timer(reason)
    _led_post("/zones", {})
    with _startup_timer_lock:
        timer = threading.Timer(STARTUP_HOLD_SECONDS, _on_startup_hold_expired)
        timer.daemon = True
        _startup_timer = timer
    timer.start()
    logger.info("LED zones display started (%s); %.0fs hold", reason, STARTUP_HOLD_SECONDS)


def handle_fen_update(data: dict) -> None:
    """FEN changed — sync board state without forcing a visible redraw."""
    global _last_fen
    fen = data.get("fen", "")
    if not fen:
        return
    _last_fen = fen
    _led_post("/fen-sync", {"fen": fen})
    logger.info("Board state synced from %s: %s", data.get("source", "?"), fen[:40])


def handle_state_sync(data: dict) -> None:
    """Seed the LED board with the bridge snapshot, then run startup once.

    Startup contract (see docs/led_flow.md §1):
      1. /fen-sync     — non-rendering, seeds the LED board model
      2. /zones        — visible startup overlay
      3. hold the zones display for STARTUP_HOLD_SECONDS; the next
         real led_player_turn or led_engine_turn pre-empts it via
         _cancel_startup_timer; otherwise /clear at expiry.
    Do NOT synthesize a player- or engine-turn overlay from this
    snapshot — the bridge will publish the real LED-intent event.
    """
    global _startup_completed
    handle_fen_update(data)
    if _startup_completed:
        return
    _startup_completed = True
    _start_zones_hold("startup")


def handle_led_player_turn(data: dict) -> None:
    """Display the player's overlay for the current turn."""
    _cancel_startup_timer("led_player_turn")
    fen = data.get("fen", "")
    if fen:
        handle_fen_update({"fen": fen, "source": "led_player_turn"})

    selected_square = data.get("selected_square")
    selected_rc = _sq_to_rc(selected_square) if isinstance(selected_square, str) else None

    targets = []
    for square in data.get("legal_targets", []):
        rc = _sq_to_rc(square)
        if rc is None:
            continue
        targets.append({"row": rc[0], "col": rc[1]})

    best_move = None
    best_from = data.get("best_move_from")
    best_to = data.get("best_move_to")
    best_from_rc = _sq_to_rc(best_from) if isinstance(best_from, str) else None
    best_to_rc = _sq_to_rc(best_to) if isinstance(best_to, str) else None
    if best_from_rc or best_to_rc:
        best_move = {
            "from": None if best_from_rc is None else {"row": best_from_rc[0], "col": best_from_rc[1]},
            "to": None if best_to_rc is None else {"row": best_to_rc[0], "col": best_to_rc[1]},
        }

    _led_post(
        "/player-turn",
        {
            "fen": fen or _last_fen,
            "selected": None if selected_rc is None else {"row": selected_rc[0], "col": selected_rc[1]},
            "targets": targets,
            "best_move": best_move,
        },
    )
    logger.info("Player-turn LED overlay updated")


def handle_move_made(data: dict) -> None:
    """Keep the board model in sync after authoritative moves."""
    fen = data.get("fen", "")
    if fen:
        handle_fen_update({"fen": fen, "source": data.get("source", "")})


def handle_led_engine_turn(data: dict) -> None:
    """Display the engine's chosen move with blue/purple endpoints."""
    _cancel_startup_timer("led_engine_turn")
    fen = data.get("fen", "")
    if fen:
        handle_fen_update({"fen": fen, "source": "led_engine_turn"})

    from_sq = data.get("from", "")
    to_sq = data.get("to", "")
    from_rc = _sq_to_rc(from_sq)
    to_rc = _sq_to_rc(to_sq)
    if from_rc is None or to_rc is None:
        return
    _led_post(
        "/engine-turn",
        {
            "fen": fen or _last_fen,
            "from_r": from_rc[0],
            "from_c": from_rc[1],
            "to_r": to_rc[0],
            "to_c": to_rc[1],
        },
    )
    logger.info("Engine-turn LED overlay updated for %s→%s", from_sq, to_sq)


def handle_led_game_result(data: dict) -> None:
    """Play the win/draw sequence for terminal positions."""
    result = data.get("result", "")
    if result == "draw":
        _led_post("/draw", {})
        logger.info("Draw LED sequence played")
        return

    winner = data.get("winner")
    if winner in ("red", "black"):
        _led_post("/win", {"side": winner})
        logger.info("Win LED sequence played for %s", winner)


def handle_led_reset(data: dict) -> None:
    """Clear any currently lit LEDs after reset / terminal sequences."""
    reason = data.get("reason", "reset")
    if reason in _RESET_ZONE_REASONS:
        _start_zones_hold(reason)
        return
    _cancel_startup_timer(reason)
    _led_post("/clear", {})
    logger.info("LEDs cleared (%s)", reason)


def handle_led_command(data: dict) -> None:
    """CV system requests LED off (camera capture) or on."""
    cmd = data.get("command", "")
    source = data.get("source", "")
    if source == "bridge_direct_http":
        logger.info("Skipping LED command %s because bridge already applied it directly", cmd)
        return
    if cmd == "off" or cmd == "clear":
        _led_post("/cv_pause", {})
        logger.info("LEDs paused (command: %s)", cmd)
    elif cmd == "on":
        _led_post("/cv_resume", {})
        logger.info("LEDs resumed")


def handle_game_reset(_data: dict) -> None:
    """Game reset — resync the board model to the starting FEN."""
    handle_fen_update({"fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"})
    logger.info("Game reset state synced")


EVENT_HANDLERS = {
    "state_sync": handle_state_sync,
    "fen_update": handle_fen_update,
    "cv_capture": handle_fen_update,
    "move_made": handle_move_made,
    "led_player_turn": handle_led_player_turn,
    "led_engine_turn": handle_led_engine_turn,
    "led_game_result": handle_led_game_result,
    "led_reset": handle_led_reset,
    "led_command": handle_led_command,
    "game_reset": handle_game_reset,
}


# ── Main ─────────────────────────────────────────────────────────────

def run_bridge_mode(bridge_url: str, led_url: str, bridge_token: str | None = None) -> None:
    global LED_URL
    LED_URL = led_url
    url = f"{bridge_url.rstrip('/')}/state/events"
    logger.info("Starting bridge subscriber — LED server: %s", led_url)

    for event in sse_stream(url, bridge_token=bridge_token):
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
    parser.add_argument(
        "--bridge-token",
        default=os.getenv("STATE_BRIDGE_TOKEN", "").strip(),
        help=(
            "Bearer token for the state bridge SSE endpoint "
            "(default: STATE_BRIDGE_TOKEN env var)"
        ),
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
        run_bridge_mode(
            args.bridge_url,
            args.led_url,
            bridge_token=args.bridge_token or None,
        )


if __name__ == "__main__":
    main()
