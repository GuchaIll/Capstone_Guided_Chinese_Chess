# from led_board import LEDBoard

# led = LEDBoard()

# led.set_fen("rheakaehr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RHEAKAEHR")

# led.show_moves("soldier", 6, 0)

# # simulate opponent move
# # led.show_opponent_move(from_r, from_c, to_r, to_c)
# led.show_opponent_move(2, 4, 4, 4)

from led_board import LEDBoard

led = LEDBoard()

# Show zones
led.show_start_zones()

input("Press Enter to celebrate red win...")

# Celebrate red side win
led.celebrate_win("red")
