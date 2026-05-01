import board
import neopixel
import time
import random

class LEDBoard:
    def __init__(self):
        self.PIXEL_PIN = board.D18
        self.NUM_PIXELS = 400
        self.ORDER = neopixel.GRBW
        self.cv_mode = False

        self.pixels = neopixel.NeoPixel(
            self.PIXEL_PIN,
            self.NUM_PIXELS,
            brightness=0.20,
            auto_write=False,
            pixel_order=self.ORDER
        )

        self.BOARD_LED_MAP = [
            [335, 338, 341, 344, 347, 350, 353, 356, 359],
            [322, 319, 316, 313, 310, 307, 304, 301, 298],
            [262, 265, 268, 271, 274, 277, 280, 283, 286],
            [251, 248, 245, 242, 239, 236, 233, 230, 227],
            [192, 195, 198, 201, 204, 207, 210, 213, 216],
            [182, 179, 176, 173, 170, 167, 164, 161, 158],
            [122, 125, 128, 131, 134, 137, 140, 143, 146],
            [97, 94, 91, 88, 85, 82, 79, 76, 73],
            [37, 40, 43, 46, 49, 52, 55, 58, 61],
            [27, 24, 21, 18, 15, 12, 9, 6, 3],
        ]

        self.ROWS = 10
        self.COLS = 9

        # Colors
        self.OFF = (0,0,0,0)
        self.WHITE = (0,0,0,255)
        self.RED = (255,0,0,0)
        self.BLUE = (0,0,255,0)
        self.GREEN = (0,255,0,0)
        self.ORANGE = (255,80,0,0)
        self.PURPLE = (180,0,255,0)
        self.CYAN = (0,255,255,0)
        self.YELLOW = (255,255,0,0)
        self.PINK = (255,0,120,0)

        self.board_state = [["." for _ in range(9)] for _ in range(10)]
        self._pending_display = None

    # ===================== BASIC =====================
    def clear(self):
        self.pixels.fill(self.OFF)
        self.pixels.show()

    def cv_pause(self):
        """
        Turn off LEDs and prevent any updates.
        Used before capturing camera frame.
        """
        self.cv_mode = True
        self.clear()

    def cv_resume(self):
        """
        Re-enable LED updates after CV is done.
        """
        self.cv_mode = False
        if self._pending_display is not None:
            action, payload = self._pending_display
            self._pending_display = None
            if action == "render_board":
                self.render_board()
            elif action == "show_player_turn":
                self.show_player_turn(
                    payload.get("selected"),
                    payload.get("targets", []),
                    payload.get("best_move"),
                )
            elif action == "show_opponent_move":
                self.show_opponent_move(
                    payload["from_r"],
                    payload["from_c"],
                    payload["to_r"],
                    payload["to_c"],
                )
            elif action == "show_start_zones":
                self.show_start_zones()
            elif action == "celebrate_win":
                self.celebrate_win(payload["side"])
            elif action == "celebrate_draw":
                self.celebrate_draw()
        else:
            self.clear()

    def pixel_index(self, r, c):
        # Keep the software model in algebraic Xiangqi rows (row 0 = red
        # back rank) but flip at the final hardware lookup because the
        # physical strip map is wired top-to-bottom.
        return self.BOARD_LED_MAP[self.ROWS - 1 - r][c]

    def set_square(self, r, c, color):
        self.pixels[self.pixel_index(r, c)] = color

    def _queue_display(self, action, payload=None):
        self._pending_display = (action, payload or {})

    def in_bounds(self, r, c):
        return 0 <= r < self.ROWS and 0 <= c < self.COLS

    def piece_side(self, piece):
        return "red" if piece.isupper() else "black"

    def is_empty(self, r, c):
        return self.board_state[r][c] == "."

    # ===================== FEN =====================
    def normalize_piece(self, piece):
        # The repo's engine/bridge FEN uses chess-style letters for two
        # Xiangqi pieces: N/n for horse and B/b for elephant. Keep the
        # LED board model on the historical H/h and E/e forms internally.
        translation = {
            "n": "h",
            "N": "H",
            "b": "e",
            "B": "E",
        }
        return translation.get(piece, piece)

    def set_fen(self, fen, *, render=True):
        rows = fen.split()[0].split("/")
        board = []
        for row in rows:
            expanded = []
            for ch in row:
                if ch.isdigit():
                    expanded.extend(["."] * int(ch))
                else:
                    expanded.append(self.normalize_piece(ch))
            board.append(expanded)
        # FEN lists rank 9 first; reverse it so board_state[row][col] uses
        # algebraic Xiangqi rows where row 0 is red's back rank.
        self.board_state = list(reversed(board))
        if not render:
            return
        if self.cv_mode:
            self._queue_display("render_board")
        else:
            self.render_board()

    def render_board(self):
        if self.cv_mode:
            self._queue_display("render_board")
            return

        self.clear()
        for r in range(self.ROWS):
            for c in range(self.COLS):
                piece = self.board_state[r][c]
                if piece == ".":
                    continue
                self.set_square(r, c, self.RED if self.piece_side(piece) == "red" else self.BLUE)
        self.pixels.show()

    # ===================== DISPLAY =====================
    def _selected_rc(self, selected):
        if selected is None:
            return None
        sr = selected.get("row")
        sc = selected.get("col")
        if sr is None or sc is None or not self.in_bounds(sr, sc):
            return None
        return (sr, sc)

    def _best_from_rc(self, best_move):
        if best_move is None:
            return None
        br = best_move.get("from_r")
        bc = best_move.get("from_c")
        if br is None or bc is None or not self.in_bounds(br, bc):
            return None
        return (br, bc)

    def _paint_targets(self, targets):
        for target in targets:
            tr = target.get("row")
            tc = target.get("col")
            if tr is None or tc is None or not self.in_bounds(tr, tc):
                continue
            color = self.WHITE if self.is_empty(tr, tc) else self.ORANGE
            self.set_square(tr, tc, color)

    def show_player_turn(self, selected, targets, best_move):
        if self.cv_mode:
            self._queue_display(
                "show_player_turn",
                {"selected": selected, "targets": targets, "best_move": best_move},
            )
            return

        selected_rc = self._selected_rc(selected)
        best_from_rc = self._best_from_rc(best_move)

        # Selection-only contract (docs/led_flow.md §2): if there is
        # nothing to paint, leave the previous overlay (engine-turn,
        # zones, etc.) on the strip instead of wiping it. Without this,
        # any blank LED_PLAYER_TURN payload — e.g. a deselect or a fresh
        # turn before any best-move arrives — produces a dark board.
        if selected_rc is None and best_from_rc is None:
            return

        self.clear()

        if selected_rc is None:
            # Idle scene: only the best-move source square in green.
            self.set_square(best_from_rc[0], best_from_rc[1], self.GREEN)
            self.pixels.show()
            return

        self._paint_targets(targets)
        self.set_square(selected_rc[0], selected_rc[1], self.RED)
        self.pixels.show()

    def show_opponent_move(self, fr, fc, tr, tc):
        if self.cv_mode:
            self._queue_display(
                "show_opponent_move",
                {"from_r": fr, "from_c": fc, "to_r": tr, "to_c": tc},
            )
            return
        self.clear()
        self.set_square(fr,fc,self.BLUE)
        self.set_square(tr,tc,self.PURPLE)
        self.pixels.show()

    # ===================== ZONES =====================
    def show_start_zones(self):
        if self.cv_mode:
            self._queue_display("show_start_zones")
            return

        self.clear()

        for r in range(0,5):
            for c in range(self.COLS):
                self.set_square(r,c,self.BLUE)

        for r in range(5,10):
            for c in range(self.COLS):
                self.set_square(r,c,self.GREEN)

        for r in [4,5]:
            for c in range(self.COLS):
                self.set_square(r,c,self.CYAN)

        for r in range(0,3):
            for c in range(3,6):
                self.set_square(r,c,self.RED)

        for r in range(7,10):
            for c in range(3,6):
                self.set_square(r,c,self.RED)

        self.pixels.show()

    # ===================== WIN =====================
    def celebrate_win(self, side):
        if self.cv_mode:
            self._queue_display("celebrate_win", {"side": side})
            return

        start = time.time()
        # Under the algebraic-rank convention (row 0 = red back, row 9 =
        # black back), light up the winner's half of the board.
        rows = range(5,10) if side=="black" else range(0,5)
        palette = [self.RED,self.GREEN,self.BLUE,self.YELLOW,self.PURPLE,self.CYAN,self.PINK,self.ORANGE]

        while time.time()-start < 3:
            color = random.choice(palette)
            for r in rows:
                for c in range(self.COLS):
                    self.set_square(r,c,color)
            self.pixels.show()
            time.sleep(0.15)

        self.clear()

    # ===================== DRAW =====================
    def celebrate_draw(self):
        if self.cv_mode:
            self._queue_display("celebrate_draw")
            return

        start = time.time()
        palette = [self.CYAN, self.YELLOW, self.WHITE, self.PURPLE]

        while time.time() - start < 3:
            color = random.choice(palette)
            for r in range(self.ROWS):
                for c in range(self.COLS):
                    self.set_square(r, c, color)
            self.pixels.show()
            time.sleep(0.15)

        self.clear()
