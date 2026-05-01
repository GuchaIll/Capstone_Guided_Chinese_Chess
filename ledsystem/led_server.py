from flask import Flask, request, jsonify
from led_board import LEDBoard

app = Flask(__name__)
led = LEDBoard()


def _parse_square(square_data):
    if not isinstance(square_data, dict):
        return None
    row = square_data.get("row")
    col = square_data.get("col")
    if row is None or col is None:
        return None
    return {"row": int(row), "col": int(col)}

# =========================
# SET FEN
# =========================
@app.route("/fen", methods=["POST"])
def set_fen():
    data = request.json
    fen = data.get("fen")

    if not fen:
        return jsonify({"error": "Missing FEN"}), 400

    try:
        led.set_fen(fen)
        return jsonify({"status": "FEN updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/fen-sync", methods=["POST"])
def sync_fen():
    data = request.json
    fen = data.get("fen")

    if not fen:
        return jsonify({"error": "Missing FEN"}), 400

    try:
        led.set_fen(fen, render=False)
        return jsonify({"status": "FEN synced"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# SHOW MOVES
# =========================
@app.route("/move", methods=["POST"])
def show_move():
    data = request.json

    row = data.get("row")
    col = data.get("col")

    if row is None or col is None:
        return jsonify({"error": "Missing inputs"}), 400

    try:
        led.show_moves("", int(row), int(col))
        return jsonify({"status": "Move displayed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/player-turn", methods=["POST"])
def player_turn():
    data = request.json or {}
    fen = data.get("fen")
    selected = _parse_square(data.get("selected"))
    raw_targets = data.get("targets", [])
    best_move = data.get("best_move")

    if not fen:
        return jsonify({"error": "Missing FEN"}), 400

    try:
        targets = []
        if isinstance(raw_targets, list):
            for item in raw_targets:
                parsed = _parse_square(item)
                if parsed is not None:
                    targets.append(parsed)

        normalized_best_move = None
        if isinstance(best_move, dict):
            best_from = _parse_square(best_move.get("from"))
            best_to = _parse_square(best_move.get("to"))
            normalized_best_move = {
                "from_r": None if best_from is None else best_from["row"],
                "from_c": None if best_from is None else best_from["col"],
                "to_r": None if best_to is None else best_to["row"],
                "to_c": None if best_to is None else best_to["col"],
            }

        led.set_fen(fen, render=False)
        led.show_player_turn(selected, targets, normalized_best_move)
        return jsonify({"status": "Player turn displayed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# STARTING SEQUENCE
# =========================
@app.route("/zones", methods=["POST"])
def zones():
    try:
        led.show_start_zones()
        return jsonify({"status": "zones shown"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/draw", methods=["POST"])
def draw():
    try:
        led.celebrate_draw()
        return jsonify({"status": "draw celebration"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# WIN SEQUENCE
# =========================
@app.route("/win", methods=["POST"])
def win():
    side = request.json.get("side")

    if not side:
        return jsonify({"error": "Missing side"}), 400

    try:
        led.celebrate_win(side)
        return jsonify({"status": f"{side} celebration"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================
# CV PAUSE (TURN OFF LEDS)
# =========================
@app.route("/cv_pause", methods=["POST"])
def cv_pause():
    led.cv_pause()
    return jsonify({"status": "LEDs off for CV"})


# =========================
# CV RESUME
# =========================
@app.route("/cv_resume", methods=["POST"])
def cv_resume():
    led.cv_resume()
    return jsonify({"status": "LEDs re-enabled"})


@app.route("/clear", methods=["POST"])
def clear():
    led.clear()
    return jsonify({"status": "LEDs cleared"})


# =========================
# OPPONENT MOVE
# =========================
@app.route("/opponent", methods=["POST"])
def opponent_move():
    data = request.json

    fr = data.get("from_r")
    fc = data.get("from_c")
    tr = data.get("to_r")
    tc = data.get("to_c")

    if None in [fr, fc, tr, tc]:
        return jsonify({"error": "Missing inputs"}), 400

    try:
        led.show_opponent_move(
            int(fr), int(fc), int(tr), int(tc)
        )
        return jsonify({"status": "Opponent move displayed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/engine-turn", methods=["POST"])
def engine_turn():
    data = request.json or {}
    fen = data.get("fen")
    fr = data.get("from_r")
    fc = data.get("from_c")
    tr = data.get("to_r")
    tc = data.get("to_c")

    if not fen:
        return jsonify({"error": "Missing FEN"}), 400
    if None in [fr, fc, tr, tc]:
        return jsonify({"error": "Missing inputs"}), 400

    try:
        led.set_fen(fen, render=False)
        led.show_opponent_move(
            int(fr), int(fc), int(tr), int(tc)
        )
        return jsonify({"status": "Engine turn displayed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
