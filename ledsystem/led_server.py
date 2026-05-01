import logging

from flask import Flask, jsonify, request


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger("led_server")

MISSING_FEN_ERROR = "Missing FEN"
MISSING_INPUTS_ERROR = "Missing inputs"


class MockLEDBoard:
    def set_fen(self, fen, *, render=True):
        logger.info("Mock LED board set_fen render=%s fen=%s", render, fen)

    def show_player_turn(self, selected, targets, best_move):
        logger.info(
            "Mock LED board player-turn selected=%s targets=%s best_move=%s",
            selected,
            targets,
            best_move,
        )

    def show_start_zones(self):
        logger.info("Mock LED board zones")

    def celebrate_win(self, side):
        logger.info("Mock LED board win side=%s", side)

    def celebrate_draw(self):
        logger.info("Mock LED board draw")

    def cv_pause(self):
        logger.info("Mock LED board cv_pause")

    def cv_resume(self):
        logger.info("Mock LED board cv_resume")

    def clear(self):
        logger.info("Mock LED board clear")

    def show_opponent_move(self, fr, fc, tr, tc):
        logger.info(
            "Mock LED board opponent move (%s, %s) -> (%s, %s)",
            fr,
            fc,
            tr,
            tc,
        )


def _create_led_board():
    try:
        from led_board import LEDBoard
    except Exception as exc:
        logger.warning(
            "LED hardware module unavailable; starting with mock LED board: %s",
            exc,
        )
        return MockLEDBoard()

    try:
        return LEDBoard()
    except Exception as exc:
        logger.warning(
            "LED hardware initialization failed; starting with mock LED board: %s",
            exc,
        )
        return MockLEDBoard()

app = Flask(__name__)
led = _create_led_board()

logger.info("LED server starting...")


def _json_body():
    return request.get_json(silent=True) or {}


def _error(message, status=400):
    return jsonify({"error": message}), status


def _parse_square(square_data):
    if not isinstance(square_data, dict):
        return None
    row = square_data.get("row")
    col = square_data.get("col")
    if row is None or col is None:
        return None
    return {"row": int(row), "col": int(col)}


def _parse_targets(raw_targets):
    targets = []
    if isinstance(raw_targets, list):
        for item in raw_targets:
            parsed = _parse_square(item)
            if parsed is not None:
                targets.append(parsed)
    return targets


def _parse_best_move(best_move):
    if not isinstance(best_move, dict):
        return None
    best_from = _parse_square(best_move.get("from"))
    best_to = _parse_square(best_move.get("to"))
    return {
        "from_r": None if best_from is None else best_from["row"],
        "from_c": None if best_from is None else best_from["col"],
        "to_r": None if best_to is None else best_to["row"],
        "to_c": None if best_to is None else best_to["col"],
    }


def _show_opponent_move(data, *, require_fen, status_message):
    fen = data.get("fen")
    fr = data.get("from_r")
    fc = data.get("from_c")
    tr = data.get("to_r")
    tc = data.get("to_c")

    if require_fen and not fen:
        return _error(MISSING_FEN_ERROR)
    if None in [fr, fc, tr, tc]:
        return _error(MISSING_INPUTS_ERROR)

    try:
        if require_fen:
            led.set_fen(fen, render=False)
        led.show_opponent_move(int(fr), int(fc), int(tr), int(tc))
        return jsonify({"status": status_message})
    except Exception as exc:
        logger.exception("Opponent move display failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/fen", methods=["POST"])
def set_fen():
    data = _json_body()
    fen = data.get("fen")

    logger.info("/fen request received: %s", fen)

    if not fen:
        logger.warning("Missing FEN in request")
        return _error(MISSING_FEN_ERROR)

    try:
        led.set_fen(fen)
        return jsonify({"status": "FEN updated"})
    except Exception as exc:
        logger.exception("FEN update failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/fen-sync", methods=["POST"])
def sync_fen():
    data = _json_body()
    fen = data.get("fen")

    if not fen:
        return _error(MISSING_FEN_ERROR)

    try:
        led.set_fen(fen, render=False)
        return jsonify({"status": "FEN synced"})
    except Exception as exc:
        logger.exception("FEN sync failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/player-turn", methods=["POST"])
def player_turn():
    data = _json_body()
    fen = data.get("fen")
    selected = _parse_square(data.get("selected"))
    targets = _parse_targets(data.get("targets", []))
    normalized_best_move = _parse_best_move(data.get("best_move"))

    if not fen:
        return _error(MISSING_FEN_ERROR)

    try:
        led.set_fen(fen, render=False)
        led.show_player_turn(selected, targets, normalized_best_move)
        return jsonify({"status": "Player turn displayed"})
    except Exception as exc:
        logger.exception("Player-turn visualization failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/zones", methods=["POST"])
def zones():
    try:
        led.show_start_zones()
        return jsonify({"status": "zones shown"})
    except Exception as exc:
        logger.exception("Zone display failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/win", methods=["POST"])
def win():
    side = _json_body().get("side")

    logger.info("/win request received: side=%s", side)

    if not side:
        logger.warning("Missing win side")
        return _error("Missing side")

    try:
        led.celebrate_win(side)
        return jsonify({"status": f"{side} celebration"})
    except Exception as exc:
        logger.exception("Win animation failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/draw", methods=["POST"])
def draw():
    logger.info("/draw request received")

    try:
        led.celebrate_draw()
        return jsonify({"status": "draw celebration"})
    except Exception as exc:
        logger.exception("Draw animation failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/cv_pause", methods=["POST"])
def cv_pause():
    logger.info("CV pause requested")

    try:
        led.cv_pause()
        return jsonify({"status": "LEDs off for CV"})
    except Exception as exc:
        logger.exception("CV pause failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/cv_resume", methods=["POST"])
def cv_resume():
    try:
        led.cv_resume()
        return jsonify({"status": "LEDs re-enabled"})
    except Exception as exc:
        logger.exception("CV resume failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/clear", methods=["POST"])
def clear():
    try:
        led.clear()
        return jsonify({"status": "LEDs cleared"})
    except Exception as exc:
        logger.exception("Clear failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/opponent", methods=["POST"])
def opponent_move():
    data = _json_body()
    logger.info(
        "/opponent request: (%s, %s) -> (%s, %s)",
        data.get("from_r"),
        data.get("from_c"),
        data.get("to_r"),
        data.get("to_c"),
    )
    return _show_opponent_move(
        data,
        require_fen=False,
        status_message="Opponent move displayed",
    )


@app.route("/engine-turn", methods=["POST"])
def engine_turn():
    return _show_opponent_move(
        _json_body(),
        require_fen=True,
        status_message="Engine turn displayed",
    )


if __name__ == "__main__":
    logger.info("Starting Flask LED server on port 5000")
    app.run(host="0.0.0.0", port=5000)
