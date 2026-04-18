from flask import Flask, request, jsonify
from led_board import LEDBoard

app = Flask(__name__)
led = LEDBoard()

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
