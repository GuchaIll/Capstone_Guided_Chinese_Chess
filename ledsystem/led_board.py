import board
import neopixel
import time
import random

class LEDBoard:
    def __init__(self):
        self.PIXEL_PIN = board.D18
        self.NUM_PIXELS = 400
        self.ORDER = neopixel.GRBW

        self.pixels = neopixel.NeoPixel(
            self.PIXEL_PIN,
            self.NUM_PIXELS,
            brightness=0.20,
            auto_write=False,
            pixel_order=self.ORDER
        )

        self.BOARD_LED_MAP = [
            [3,   6,   9,  12,  15,  18,  21,  24,  27],
            [61, 58,  55,  52,  49,  46,  43,  40,  37],
            [73, 76,  79,  82,  85,  88,  91,  94,  97],
            [146, 143, 140, 137, 134, 131, 128, 125, 122],
            [158, 161, 164, 167, 170, 173, 176, 179, 182],
            [216, 213, 210, 207, 204, 201, 198, 195, 192],
            [227, 230, 233, 236, 239, 242, 245, 248, 251],
            [286, 283, 280, 277, 274, 271, 268, 265, 262],
            [298, 301, 304, 307, 310, 313, 316, 319, 322],
            [359, 356, 353, 350, 347, 344, 341, 338, 335],
        ]

        self.ROWS = 10
        self.COLS = 9

        # colors
        self.OFF = (0,0,0,0)
        self.WHITE = (0,0,0,255)
        self.RED = (255,0,0,0)
        self.BLUE = (0,0,255,0)
        self.GREEN = (0,255,0,0)
        self.ORANGE = (255,80,0,0)
        self.PURPLE = (180,0,255,0)
        self.CYAN   = (0, 255, 255, 0)
        self.YELLOW = (255, 255, 0, 0)
        self.PINK   = (255, 0, 120, 0)

        self.board_state = [["." for _ in range(9)] for _ in range(10)]

    # =====================================================
    # BASIC HELPERS
    # =====================================================
    def clear(self):
        self.pixels.fill(self.OFF)
        self.pixels.show()

    def set_square(self, r, c, color):
        idx = self.BOARD_LED_MAP[r][c]
        self.pixels[idx] = color

    def in_bounds(self, r, c):
        return 0 <= r < self.ROWS and 0 <= c < self.COLS

    # =====================================================
    # FEN
    # =====================================================
    def set_fen(self, fen):
        rows = fen.split()[0].split("/")
        board = []

        for row in rows:
            expanded = []
            for ch in row:
                if ch.isdigit():
                    expanded.extend(["."] * int(ch))
                else:
                    expanded.append(ch)
            board.append(expanded)

        self.board_state = board

    # =====================================================
    # MOVE DISPLAY
    # =====================================================
    def show_moves(self, piece_name, r, c):
        piece = self.board_state[r][c]

        if piece == ".":
            print("No piece there")
            return

        moves = get_moves(self.board_state, r, c)
        best = best_move_for_piece(self.board_state, r, c, moves)

        self.clear()

        # moves
        for mr, mc in moves:
            if self.board_state[mr][mc] == ".":
                self.set_square(mr, mc, self.WHITE)
            else:
                self.set_square(mr, mc, self.ORANGE)

        # best move
        if best:
            self.set_square(best[0], best[1], self.GREEN)

        # selected
        self.set_square(r, c, self.RED)

        self.pixels.show()

    def show_start_zones(self):
        """
        Lights:
        - Palaces (top & bottom) in RED
        - River (between rows 4 and 5) in CYAN
        - Territories: top half BLUE, bottom half GREEN
        """

        self.clear()

        # --- Territories ---
        # Top side (rows 0-4)
        for r in range(0, 5):
            for c in range(self.COLS):
                self.set_square(r, c, self.BLUE)

        # Bottom side (rows 5-9)
        for r in range(5, 10):
            for c in range(self.COLS):
                self.set_square(r, c, self.GREEN)

        # --- River (rows 4 and 5 boundary) ---
        # We’ll color BOTH rows 4 and 5 for visibility
        for r in [4, 5]:
            for c in range(self.COLS):
                self.set_square(r, c, self.CYAN)

        # --- Palaces (override colors) ---
        # Top palace: rows 0-2, cols 3-5
        for r in range(0, 3):
            for c in range(3, 6):
                self.set_square(r, c, self.RED)

        # Bottom palace: rows 7-9, cols 3-5
        for r in range(7, 10):
            for c in range(3, 6):
                self.set_square(r, c, self.RED)

        self.pixels.show()

    # =====================================================
    # WIN CELEBRATION
    # =====================================================
    def celebrate_win(self, side, duration=3.0, interval=0.15):
        """
        Flashes all LEDs on the winner's side with fun colors.

        side: "red" or "black"
        - "black" = top half (rows 0-4)
        - "red"   = bottom half (rows 5-9)

        duration: total seconds to run
        interval: how fast to change colors
        """

        start_time = time.time()

        # Determine which rows belong to the winner
        if side == "black":
            rows = range(0, 5)
        elif side == "red":
            rows = range(5, 10)
        else:
            print("celebrate_win: side must be 'red' or 'black'")
            return

        palette = [self.RED, self.GREEN, self.BLUE, self.YELLOW, self.PURPLE, self.CYAN, self.PINK, self.ORANGE]

        while time.time() - start_time < duration:
            color = random.choice(palette)

            # Fill only the winner's side
            for r in rows:
                for c in range(self.COLS):
                    self.set_square(r, c, color)

            self.pixels.show()
            time.sleep(interval)

        self.clear()

    # =====================================================
    # INDEX VERSION
    # =====================================================
    def show_moves_index(self, piece_name, idx):
        r = idx // 9
        c = idx % 9
        self.show_moves(piece_name, r, c)

    # =====================================================
    # OPPONENT MOVE
    # =====================================================
    def show_opponent_move(self, fr, fc, tr, tc):
        self.clear()
        self.set_square(fr, fc, self.BLUE)
        self.set_square(tr, tc, self.PURPLE)
        self.pixels.show()
