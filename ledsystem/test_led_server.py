from __future__ import annotations

from pathlib import Path


def test_led_server_source_keeps_player_turn_and_drops_legacy_move_route():
    source = Path("ledsystem/led_server.py").read_text()

    assert source.count('@app.route("/player-turn", methods=["POST"])') == 1
    assert source.count('@app.route("/fen-sync", methods=["POST"])') == 1
    assert source.count('@app.route("/draw", methods=["POST"])') == 1
    assert source.count('@app.route("/engine-turn", methods=["POST"])') == 1
    assert '@app.route("/move", methods=["POST"])' not in source
    assert "led.set_fen(fen, render=False)" in source
    assert "led.show_player_turn(selected, targets, normalized_best_move)" in source
