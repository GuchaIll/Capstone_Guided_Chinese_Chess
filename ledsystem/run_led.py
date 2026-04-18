from led_board import LEDBoard
import time

led = LEDBoard()

print("Starting LED system test...")

# =========================
# 1. LOAD STARTING POSITION
# =========================
print("Setting starting FEN...")
led.set_fen("rheakaehr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RHEAKAEHR")
time.sleep(3)

# =========================
# 2. SHOW MOVES (SOLDIER)
# =========================
print("Showing soldier moves...")
led.show_moves("", 6, 0)
time.sleep(3)

# =========================
# 3. SHOW MOVES (CHARIOT)
# =========================
print("Showing chariot moves...")
led.show_moves("", 9, 0)
time.sleep(3)

# =========================
# 4. SHOW MOVES (HORSE)
# =========================
print("Showing horse moves...")
led.show_moves("", 9, 1)
time.sleep(3)

# =========================
# 5. SHOW MOVES (CANNON)
# =========================
print("Showing cannon moves...")
led.show_moves("", 7, 1)
time.sleep(3)

# =========================
# 6. OPPONENT MOVE
# =========================
print("Showing opponent move...")
led.show_opponent_move(2, 4, 4, 4)
time.sleep(3)

# =========================
# 7. SHOW BOARD ZONES
# =========================
print("Showing board zones...")
led.show_start_zones()
time.sleep(3)

# =========================
# 8. WIN CELEBRATION (RED)
# =========================
print("Celebrating RED win...")
led.celebrate_win("red")
time.sleep(3)

# =========================
# 9. WIN CELEBRATION (BLACK)
# =========================
print("Celebrating BLACK win...")
led.celebrate_win("black")
time.sleep(3)

# =========================
# 10. CLEAR BOARD
# =========================
print("Clearing LEDs...")
led.clear()

print("Test complete.")
