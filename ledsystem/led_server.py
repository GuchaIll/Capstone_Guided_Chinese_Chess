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

    led.set_fen(fen)
    return jsonify({"status": "FEN updated"})


# =========================
# SHOW MOVES
# =========================
@app.route("/move", methods=["POST"])
def show_move():
    data = request.json

    piece = data.get("piece")
    row = data.get("row")
    col = data.get("col")

    if piece is None or row is None or col is None:
        return jsonify({"error": "Missing inputs"}), 400

    led.show_moves(piece, row, col)

    return jsonify({"status": "Move displayed"})


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

    led.show_opponent_move(fr, fc, tr, tc)

    return jsonify({"status": "Opponent move displayed"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
