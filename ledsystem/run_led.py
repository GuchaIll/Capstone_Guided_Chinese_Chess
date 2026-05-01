from led_board import LEDBoard
import time


START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
CAPTURE_FEN = "9/9/9/9/9/9/9/9/p8/R8 w - - 0 1"
ENGINE_MOVE_FEN = "r1bakabnr/9/1cn4c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2"


def pause(label):
    print(label)
    time.sleep(3)


led = LEDBoard()

print("Starting LED scene smoke test...")

print("Syncing starting FEN...")
led.set_fen(START_FEN)
pause("Board rendered from FEN")

led.show_player_turn(
    None,
    [],
    {"from_r": 0, "from_c": 1, "to_r": 2, "to_c": 2},
)
pause("Idle player-turn scene: recommended piece only")

led.set_fen(CAPTURE_FEN, render=False)
led.show_player_turn(
    {"row": 0, "col": 0},
    [{"row": 1, "col": 0}],
    {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 0},
)
pause("Selected player-turn scene: capture target should be orange")

led.set_fen(ENGINE_MOVE_FEN, render=False)
led.show_opponent_move(9, 1, 7, 2)
pause("Engine-turn scene")

led.show_start_zones()
pause("Startup zones scene")

led.celebrate_win("red")
pause("Red win celebration")

led.celebrate_win("black")
pause("Black win celebration")

led.celebrate_draw()
pause("Draw celebration")

print("Clearing LEDs...")
led.clear()

print("Smoke test complete.")
