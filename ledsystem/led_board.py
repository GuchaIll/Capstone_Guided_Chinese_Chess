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
            [27, 24, 21, 18, 15, 12, 9, 6, 3],
            [37, 40, 43, 46, 49, 52, 55, 58, 61],
            [97, 94, 91, 88, 85, 82, 79, 76, 73],
            [122, 125, 128, 131, 134, 137, 140, 143, 146],
            [182, 179, 176, 173, 170, 167, 164, 161, 158],
            [192, 195, 198, 201, 204, 207, 210, 213, 216],
            [251, 248, 245, 242, 239, 236, 233, 230, 227],
            [262, 265, 268, 271, 274, 277, 280, 283, 286],
            [322, 319, 316, 313, 310, 307, 304, 301, 298],
            [335, 338, 341, 344, 347, 350, 353, 356, 359],
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
            elif action == "show_moves":
                self.show_moves("", payload["row"], payload["col"])
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
            self.render_board()

    def set_square(self, r, c, color):
        self.pixels[self.BOARD_LED_MAP[r][c]] = color

    def _queue_display(self, action, payload=None):
        self._pending_display = (action, payload or {})

    def in_bounds(self, r, c):
        return 0 <= r < self.ROWS and 0 <= c < self.COLS

    def piece_side(self, piece):
        return "red" if piece.isupper() else "black"

    def is_empty(self, r, c):
        return self.board_state[r][c] == "."

    def is_enemy(self, r, c, side):
        return not self.is_empty(r,c) and self.piece_side(self.board_state[r][c]) != side

    def add_if_legal(self, moves, r, c, side):
        if self.in_bounds(r,c) and (self.is_empty(r,c) or self.is_enemy(r,c,side)):
            moves.append((r,c))

    def in_palace(self, r, c, side):
        if side == "red":
            return 7 <= r <= 9 and 3 <= c <= 5
        return 0 <= r <= 2 and 3 <= c <= 5

    # ===================== FEN =====================
    def normalize_piece(self, piece):
        # The repo's engine/bridge FEN uses chess-style letters for two
        # Xiangqi pieces: N/n for horse and B/b for elephant. The LED move
        # generator below uses H/h and E/e internally, so translate only
        # those incoming engine variants here.
        translation = {
            "n": "h",
            "N": "H",
            "b": "e",
            "B": "E",
        }
        return translation.get(piece, piece)

    def set_fen(self, fen):
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
        self.board_state = board
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

    # ===================== MOVES =====================
    def chariot_moves(self, r, c):
        moves = []
        side = self.piece_side(self.board_state[r][c])
        for dr,dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr,nc = r+dr,c+dc
            while self.in_bounds(nr,nc):
                if self.is_empty(nr,nc):
                    moves.append((nr,nc))
                else:
                    if self.is_enemy(nr,nc,side):
                        moves.append((nr,nc))
                    break
                nr += dr
                nc += dc
        return moves

    def cannon_moves(self, r, c):
        moves = []
        side = self.piece_side(self.board_state[r][c])
        for dr,dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr,nc = r+dr,c+dc
            jumped = False
            while self.in_bounds(nr,nc):
                if not jumped:
                    if self.is_empty(nr,nc):
                        moves.append((nr,nc))
                    else:
                        jumped = True
                else:
                    if not self.is_empty(nr,nc):
                        if self.is_enemy(nr,nc,side):
                            moves.append((nr,nc))
                        break
                nr += dr
                nc += dc
        return moves

    def horse_moves(self, r, c):
        moves = []
        side = self.piece_side(self.board_state[r][c])
        patterns = [
            ((-1,0),(-2,-1)),((-1,0),(-2,1)),
            ((1,0),(2,-1)),((1,0),(2,1)),
            ((0,-1),(-1,-2)),((0,-1),(1,-2)),
            ((0,1),(-1,2)),((0,1),(1,2)),
        ]
        for leg, dest in patterns:
            lr,lc = r+leg[0],c+leg[1]
            dr,dc = r+dest[0],c+dest[1]
            if not self.in_bounds(lr,lc): continue
            if not self.is_empty(lr,lc): continue
            self.add_if_legal(moves,dr,dc,side)
        return moves

    def elephant_moves(self, r, c):
        moves = []
        side = self.piece_side(self.board_state[r][c])
        for dr,dc in [(-2,-2),(-2,2),(2,-2),(2,2)]:
            eye_r,eye_c = r+dr//2,c+dc//2
            nr,nc = r+dr,c+dc
            if not self.in_bounds(nr,nc): continue
            if not self.is_empty(eye_r,eye_c): continue
            if side=="red" and nr<5: continue
            if side=="black" and nr>4: continue
            self.add_if_legal(moves,nr,nc,side)
        return moves

    def advisor_moves(self, r, c):
        moves = []
        side = self.piece_side(self.board_state[r][c])
        for dr,dc in [(-1,-1),(-1,1),(1,-1),(1,1)]:
            nr,nc = r+dr,c+dc
            if self.in_bounds(nr,nc) and self.in_palace(nr,nc,side):
                self.add_if_legal(moves,nr,nc,side)
        return moves

    def general_moves(self, r, c):
        moves = []
        side = self.piece_side(self.board_state[r][c])
        for dr,dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr,nc = r+dr,c+dc
            if self.in_bounds(nr,nc) and self.in_palace(nr,nc,side):
                self.add_if_legal(moves,nr,nc,side)

        # flying general
        enemy = "k" if side=="red" else "K"
        step = -1 if side=="red" else 1
        nr = r+step
        while self.in_bounds(nr,c):
            if not self.is_empty(nr,c):
                if self.board_state[nr][c] == enemy:
                    moves.append((nr,c))
                break
            nr += step
        return moves

    def soldier_moves(self, r, c):
        moves = []
        side = self.piece_side(self.board_state[r][c])
        if side=="red":
            self.add_if_legal(moves,r-1,c,side)
            if r<=4:
                self.add_if_legal(moves,r,c-1,side)
                self.add_if_legal(moves,r,c+1,side)
        else:
            self.add_if_legal(moves,r+1,c,side)
            if r>=5:
                self.add_if_legal(moves,r,c-1,side)
                self.add_if_legal(moves,r,c+1,side)
        return moves

    def get_moves(self, r, c):
        piece = self.board_state[r][c]
        if piece==".":
            return []
        p = piece.lower()
        if p=="r": return self.chariot_moves(r,c)
        if p=="c": return self.cannon_moves(r,c)
        if p=="h": return self.horse_moves(r,c)
        if p=="e": return self.elephant_moves(r,c)
        if p=="a": return self.advisor_moves(r,c)
        if p=="k": return self.general_moves(r,c)
        if p=="p": return self.soldier_moves(r,c)
        return []

    # ===================== DISPLAY =====================
    def show_moves(self, piece_name, r, c):
        if self.cv_mode:
            self._queue_display("show_moves", {"row": r, "col": c})
            return

        if self.board_state[r][c]==".":
            print("No piece")
            return

        moves = self.get_moves(r,c)
        best = moves[0] if moves else None

        self.clear()

        for mr,mc in moves:
            if self.is_empty(mr,mc):
                self.set_square(mr,mc,self.WHITE)
            else:
                self.set_square(mr,mc,self.ORANGE)

        if best:
            self.set_square(best[0],best[1],self.GREEN)

        self.set_square(r,c,self.RED)
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

    # ===================== DRAW =====================
def celebrate_draw(self):
    if self.cv_mode:
        self._queue_display("celebrate_draw")
        return

    self.clear()

    palette = [
        self.RED,
        self.GREEN,
        self.BLUE,
        self.YELLOW,
        self.PURPLE,
        self.CYAN,
        self.PINK,
        self.ORANGE,
        self.WHITE,
    ]

    start = time.time()

    while time.time() - start < 4:
        for r in range(self.ROWS):
            for c in range(self.COLS):
                color = random.choice(palette)
                self.set_square(r, c, color)

        self.pixels.show()
        time.sleep(0.20)

    self.clear()

    # ===================== WIN =====================
    def celebrate_win(self, side):
        if self.cv_mode:
            self._queue_display("celebrate_win", {"side": side})
            return

        start = time.time()
        rows = range(0,5) if side=="black" else range(5,10)
        palette = [self.RED,self.GREEN,self.BLUE,self.YELLOW,self.PURPLE,self.CYAN,self.PINK,self.ORANGE]

        while time.time()-start < 3:
            color = random.choice(palette)
            for r in rows:
                for c in range(self.COLS):
                    self.set_square(r,c,color)
            self.pixels.show()
            time.sleep(0.15)

        self.clear()
