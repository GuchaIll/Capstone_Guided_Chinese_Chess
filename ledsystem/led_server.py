from flask import Flask, request, jsonify
from led_board import LEDBoard
import logging

# =========================
# LOGGING SETUP
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger("led_server")

app = Flask(__name__)
led = LEDBoard()

logger.info("LED server starting...")


# =========================
# SET FEN
# =========================
@app.route("/fen", methods=["POST"])
def set_fen():
    data = request.json
    fen = data.get("fen")

    logger.info(f"/fen request received: {fen}")

    if not fen:
        logger.warning("Missing FEN in request")
        return jsonify({"error": "Missing FEN"}), 400

    try:
        logger.info("Updating board FEN...")
        led.set_fen(fen)
        logger.info("FEN successfully applied")
        return jsonify({"status": "FEN updated"})
    except Exception as e:
        logger.exception("FEN update failed")
        return jsonify({"error": str(e)}), 500


# =========================
# SHOW MOVES
# =========================
@app.route("/move", methods=["POST"])
def show_move():
    data = request.json

    row = data.get("row")
    col = data.get("col")

    logger.info(f"/move request: row={row}, col={col}")

    if row is None or col is None:
        logger.warning("Missing move inputs")
        return jsonify({"error": "Missing inputs"}), 400

    try:
        logger.info("Turning LEDs ON for move visualization")
        led.show_moves("", int(row), int(col))
        logger.info("Move LEDs displayed")
        return jsonify({"status": "Move displayed"})
    except Exception as e:
        logger.exception("Move visualization failed")
        return jsonify({"error": str(e)}), 500


# =========================
# STARTING SEQUENCE
# =========================
@app.route("/zones", methods=["POST"])
def zones():
    logger.info("/zones request received")

    try:
        logger.info("Displaying board zones")
        led.show_start_zones()
        logger.info("Zone LEDs active")
        return jsonify({"status": "zones shown"})
    except Exception as e:
        logger.exception("Zone display failed")
        return jsonify({"error": str(e)}), 500


# =========================
# WIN SEQUENCE
# =========================
@app.route("/win", methods=["POST"])
def win():
    side = request.json.get("side")

    logger.info(f"/win request received: side={side}")

    if not side:
        logger.warning("Missing win side")
        return jsonify({"error": "Missing side"}), 400

    try:
        logger.info(f"Starting {side} celebration LEDs")
        led.celebrate_win(side)
        logger.info("Celebration sequence completed")
        return jsonify({"status": f"{side} celebration"})
    except Exception as e:
        logger.exception("Win animation failed")
        return jsonify({"error": str(e)}), 500

# =========================
# DRAW SEQUENCE
# =========================
@app.route("/draw", methods=["POST"])
def draw():
    logger.info("/draw request received")

    try:
        logger.info("Starting draw animation")
        led.celebrate_draw()
        logger.info("Draw animation completed")
        return jsonify({"status": "draw celebration"})
    except Exception as e:
        logger.exception("Draw animation failed")
        return jsonify({"error": str(e)}), 500

        
# =========================
# CV PAUSE (TURN OFF LEDS)
# =========================
@app.route("/cv_pause", methods=["POST"])
def cv_pause():
    logger.info("CV pause requested — turning LEDs OFF")

    try:
        led.cv_pause()
        logger.info("LEDs OFF for CV")
        return jsonify({"status": "LEDs off for CV"})
    except Exception as e:
        logger.exception("CV pause failed")
        return jsonify({"error": str(e)}), 500


# =========================
# CV RESUME
# =========================
@app.route("/cv_resume", methods=["POST"])
def cv_resume():
    logger.info("CV resume requested — turning LEDs back ON")

    try:
        led.cv_resume()
        logger.info("LEDs re-enabled")
        return jsonify({"status": "LEDs re-enabled"})
    except Exception as e:
        logger.exception("CV resume failed")
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

    logger.info(
        f"/opponent request: ({fr}, {fc}) -> ({tr}, {tc})"
    )

    if None in [fr, fc, tr, tc]:
        logger.warning("Missing opponent move inputs")
        return jsonify({"error": "Missing inputs"}), 400

    try:
        logger.info("Displaying opponent move LEDs")
        led.show_opponent_move(
            int(fr), int(fc), int(tr), int(tc)
        )
        logger.info("Opponent move LEDs displayed")
        return jsonify({"status": "Opponent move displayed"})
    except Exception as e:
        logger.exception("Opponent move display failed")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    logger.info("Starting Flask LED server on port 5000")
    app.run(host="0.0.0.0", port=5000)