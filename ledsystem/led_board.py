import board
import neopixel

class LEDBoard:
    def __init__(self):
        self.PIXEL_PIN = board.D18
        self.NUM_PIXELS = 359
        self.ORDER = neopixel.GRBW

        self.pixels = neopixel.NeoPixel(
            self.PIXEL_PIN,
            self.NUM_PIXELS,
            brightness=0.20,
            auto_write=False,
            pixel_order=self.ORDER
        )

        self.BOARD_LED_MAP = [
            [3,6,9,12,15,18,21,24,27],
            [60,57,54,51,49,46,43,40,37],
            [72,75,78,81,84,87,90,93,96],
            [145,142,139,136,133,130,127,124,121],
            [157,160,163,166,169,172,175,178,181],
            [215,212,209,206,203,200,197,194,191],
            [226,229,232,235,238,241,244,247,250],
            [285,282,279,276,273,270,267,264,261],
            [297,300,303,306,309,312,315,318,321],
            [358,355,352,349,346,343,340,337,334],
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
