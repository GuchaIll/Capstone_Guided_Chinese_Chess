import board
import neopixel

# =========================================================
# LED SETUP
# =========================================================
PIXEL_PIN = board.D18
NUM_PIXELS = 400   # highest index in your map is 358
ORDER = neopixel.GRBW

pixels = neopixel.NeoPixel(
    PIXEL_PIN,
    NUM_PIXELS,
    brightness=0.20,
    auto_write=False,
    pixel_order=ORDER
)

# =========================================================
# BOARD -> LED MAP (10 rows x 9 cols)
# Assumption: first row missing value is 18
# =========================================================
BOARD_LED_MAP = [
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

ROWS = 10
COLS = 9

# =========================================================
# COLORS
# =========================================================
OFF = (0, 0, 0, 0)
WHITE = (0, 0, 0, 255)     # empty move
RED = (255, 0, 0, 0)       # selected piece
BLUE = (0, 0, 255, 0)      # opponent start
GREEN = (0, 255, 0, 0)     # best move
ORANGE = (255, 80, 0, 0)   # capture
PURPLE = (180, 0, 255, 0)  # opponent destination

# =========================================================
# PIECE NAME <-> FEN LETTERS
# =========================================================
NAME_TO_FEN = {
    "chariot": {"r", "R"},
    "horse": {"h", "H"},
    "elephant": {"e", "E"},
    "advisor": {"a", "A"},
    "general": {"k", "K"},
    "cannon": {"c", "C"},
    "soldier": {"p", "P"},
}

FEN_TO_NAME = {
    "r": "chariot", "R": "chariot",
    "h": "horse",   "H": "horse",
    "e": "elephant","E": "elephant",
    "a": "advisor", "A": "advisor",
    "k": "general", "K": "general",
    "c": "cannon",  "C": "cannon",
    "p": "soldier", "P": "soldier",
}

# =========================================================
# LED HELPERS
# =========================================================
def clear():
    pixels.fill(OFF)
    pixels.show()

def set_square(r, c, color):
    led_idx = BOARD_LED_MAP[r][c]
    pixels[led_idx] = color

def show_position(board_state, selected=None, moves=None, best_move=None):
    clear()

    if moves is None:
        moves = []

    for r, c in moves:
        if board_state[r][c] == ".":
            set_square(r, c, WHITE)   # empty move
        else:
            set_square(r, c, ORANGE)  # capture

    # best move overrides others
    if best_move is not None:
        br, bc = best_move
        set_square(br, bc, GREEN)

    # selected piece overrides everything at that square
    if selected is not None:
        sr, sc = selected
        set_square(sr, sc, RED)

    pixels.show()

PIECE_VALUES = {
    "k": 1000, "K": 1000,
    "r": 90,   "R": 90,
    "c": 50,   "C": 50,
    "h": 40,   "H": 40,
    "e": 20,   "E": 20,
    "a": 20,   "A": 20,
    "p": 10,   "P": 10,
}

def best_move_for_piece(board_state, r, c, moves):
    if not moves:
        return None

    best = None
    best_score = float("-inf")

    for mr, mc in moves:
        target = board_state[mr][mc]

        score = 0

        # prioritize captures
        if target != ".":
            score += 1000 + PIECE_VALUES.get(target, 0)

        # small center preference
        score += max(0, 4 - abs(mc - 4)) * 0.5

        if score > best_score:
            best_score = score
            best = (mr, mc)

    return best

# =========================================================
# BOARD HELPERS
# =========================================================
def in_bounds(r, c):
    return 0 <= r < ROWS and 0 <= c < COLS

def piece_side(piece):
    if piece == ".":
        return None
    return "red" if piece.isupper() else "black"

def is_empty(board_state, r, c):
    return board_state[r][c] == "."

def is_enemy(board_state, r, c, side):
    piece = board_state[r][c]
    return piece != "." and piece_side(piece) != side

def is_friend(board_state, r, c, side):
    piece = board_state[r][c]
    return piece != "." and piece_side(piece) == side

def add_if_legal(board_state, moves, r, c, side):
    if not in_bounds(r, c):
        return
    if is_friend(board_state, r, c, side):
        return
    moves.append((r, c))

def in_palace(r, c, side):
    if side == "red":
        return 7 <= r <= 9 and 3 <= c <= 5
    return 0 <= r <= 2 and 3 <= c <= 5

# =========================================================
# FEN PARSING
# Xiangqi FEN board part only, e.g.
# rheakaehr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RHEAKAEHR
# =========================================================
def parse_xiangqi_fen(fen_str):
    fen_board = fen_str.strip().split()[0]
    rows = fen_board.split("/")

    if len(rows) != 10:
        raise ValueError(f"FEN must have 10 rows, got {len(rows)}")

    board_state = []

    for row in rows:
        expanded = []
        for ch in row:
            if ch.isdigit():
                expanded.extend(["."] * int(ch))
            else:
                expanded.append(ch)

        if len(expanded) != 9:
            raise ValueError(f"Each FEN row must expand to 9 columns, got {len(expanded)} from row '{row}'")

        board_state.append(expanded)

    return board_state

def print_board(board_state):
    print("\nBoard:")
    for r in range(ROWS):
        print(r, " ".join(board_state[r]))
    print("   0 1 2 3 4 5 6 7 8\n")

# =========================================================
# MOVE GENERATION
# =========================================================
def chariot_moves(board_state, r, c):
    moves = []
    side = piece_side(board_state[r][c])

    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for dr, dc in directions:
        nr, nc = r + dr, c + dc
        while in_bounds(nr, nc):
            if is_empty(board_state, nr, nc):
                moves.append((nr, nc))
            else:
                if is_enemy(board_state, nr, nc, side):
                    moves.append((nr, nc))
                break
            nr += dr
            nc += dc

    return moves

def cannon_moves(board_state, r, c):
    moves = []
    side = piece_side(board_state[r][c])

    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for dr, dc in directions:
        nr, nc = r + dr, c + dc
        jumped = False

        while in_bounds(nr, nc):
            if not jumped:
                if is_empty(board_state, nr, nc):
                    moves.append((nr, nc))
                else:
                    jumped = True
            else:
                if not is_empty(board_state, nr, nc):
                    if is_enemy(board_state, nr, nc, side):
                        moves.append((nr, nc))
                    break

            nr += dr
            nc += dc

    return moves

def horse_moves(board_state, r, c):
    moves = []
    side = piece_side(board_state[r][c])

    horse_patterns = [
        ((-1, 0), (-2, -1)),
        ((-1, 0), (-2, 1)),
        ((1, 0), (2, -1)),
        ((1, 0), (2, 1)),
        ((0, -1), (-1, -2)),
        ((0, -1), (1, -2)),
        ((0, 1), (-1, 2)),
        ((0, 1), (1, 2)),
    ]

    for leg, dest in horse_patterns:
        leg_r, leg_c = r + leg[0], c + leg[1]
        dest_r, dest_c = r + dest[0], c + dest[1]

        if not in_bounds(leg_r, leg_c):
            continue
        if not is_empty(board_state, leg_r, leg_c):
            continue
        add_if_legal(board_state, moves, dest_r, dest_c, side)

    return moves

def elephant_moves(board_state, r, c):
    moves = []
    side = piece_side(board_state[r][c])

    deltas = [(-2, -2), (-2, 2), (2, -2), (2, 2)]

    for dr, dc in deltas:
        eye_r, eye_c = r + dr // 2, c + dc // 2
        nr, nc = r + dr, c + dc

        if not in_bounds(nr, nc):
            continue

        # Elephant eye blocking
        if not is_empty(board_state, eye_r, eye_c):
            continue

        # River restriction
        if side == "red" and nr < 5:
            continue
        if side == "black" and nr > 4:
            continue

        add_if_legal(board_state, moves, nr, nc, side)

    return moves

def advisor_moves(board_state, r, c):
    moves = []
    side = piece_side(board_state[r][c])

    for dr, dc in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        nr, nc = r + dr, c + dc
        if in_bounds(nr, nc) and in_palace(nr, nc, side):
            add_if_legal(board_state, moves, nr, nc, side)

    return moves

def general_moves(board_state, r, c):
    moves = []
    side = piece_side(board_state[r][c])

    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nr, nc = r + dr, c + dc
        if in_bounds(nr, nc) and in_palace(nr, nc, side):
            add_if_legal(board_state, moves, nr, nc, side)

    # Flying general capture
    # Look straight down/up same column for enemy general with no pieces between
    enemy_general = "k" if side == "red" else "K"
    step = -1 if side == "red" else 1
    nr = r + step
    blocked = False
    while in_bounds(nr, c):
        if board_state[nr][c] != ".":
            if board_state[nr][c] == enemy_general and not blocked:
                moves.append((nr, c))
            break
        nr += step

    return moves

def soldier_moves(board_state, r, c):
    moves = []
    side = piece_side(board_state[r][c])

    if side == "red":
        forward_r, forward_c = r - 1, c
        add_if_legal(board_state, moves, forward_r, forward_c, side)

        # After crossing river
        if r <= 4:
            add_if_legal(board_state, moves, r, c - 1, side)
            add_if_legal(board_state, moves, r, c + 1, side)

    else:
        forward_r, forward_c = r + 1, c
        add_if_legal(board_state, moves, forward_r, forward_c, side)

        # After crossing river
        if r >= 5:
            add_if_legal(board_state, moves, r, c - 1, side)
            add_if_legal(board_state, moves, r, c + 1, side)

    return moves

def get_moves(board_state, r, c):
    piece = board_state[r][c]
    if piece == ".":
        return []

    name = FEN_TO_NAME.get(piece)
    if name == "chariot":
        return chariot_moves(board_state, r, c)
    if name == "horse":
        return horse_moves(board_state, r, c)
    if name == "elephant":
        return elephant_moves(board_state, r, c)
    if name == "advisor":
        return advisor_moves(board_state, r, c)
    if name == "general":
        return general_moves(board_state, r, c)
    if name == "cannon":
        return cannon_moves(board_state, r, c)
    if name == "soldier":
        return soldier_moves(board_state, r, c)

    return []

def highlight_opponent_move(from_r, from_c, to_r, to_c):
    """
    Show opponent move:
    - start = blue
    - end = purple
    """

    if not in_bounds(from_r, from_c) or not in_bounds(to_r, to_c):
        print("Invalid opponent move")
        return

    clear()

    set_square(from_r, from_c, BLUE)
    set_square(to_r, to_c, PURPLE)

    pixels.show()

# =========================================================
# INPUT HELPERS
# =========================================================
def linear_index_to_rc(idx):
    if not (0 <= idx < ROWS * COLS):
        raise ValueError(f"Linear index must be between 0 and {ROWS * COLS - 1}")
    return idx // COLS, idx % COLS

# =========================================================
# MAIN LOOP
# =========================================================
def main():
    clear()

    print("Xiangqi LED system ready.")
    print("Commands:")
    print("  fen <FEN_STRING>")
    print("  show")
    print("  move <piece_name> <row> <col>")
    print("  moveidx <piece_name> <linear_index_0_to_89>")
    print("  opp <from_r> <from_c> <to_r> <to_c>")
    print("  q")

    current_fen = "rheakaehr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RHEAKAEHR"
    board_state = parse_xiangqi_fen(current_fen)

    while True:
        cmd = input("\n> ").strip()

        if cmd.lower() == "q":
            clear()
            print("Exiting.")
            break

        if cmd.lower() == "show":
            print_board(board_state)
            continue

        if cmd.lower() == "zones":
            led.show_start_zones()
            continue

        if cmd.lower().startswith("win "):
            parts = cmd.split()
            if len(parts) != 2:
                print("Use: win red|black")
                continue
            led.celebrate_win(parts[1])
            continue

        if cmd.lower().startswith("fen "):
            fen_str = cmd[4:].strip()
            try:
                board_state = parse_xiangqi_fen(fen_str)
                current_fen = fen_str
                clear()
                print("FEN loaded.")
                print_board(board_state)
            except Exception as e:
                print(f"FEN parse error: {e}")
            continue

        if cmd.lower().startswith("opp "):
            parts = cmd.split()
            if len(parts) != 5:
                print("Use: opp from_r from_c to_r to_c")
                continue

            try:
                fr = int(parts[1])
                fc = int(parts[2])
                tr = int(parts[3])
                tc = int(parts[4])
            except:
                print("Invalid numbers")
                continue

            highlight_opponent_move(fr, fc, tr, tc)
            continue

        if cmd.lower().startswith("moveidx "):
            parts = cmd.split()
            if len(parts) != 3:
                print("Use: moveidx <piece_name> <linear_index>")
                continue

            piece_name = parts[1].lower()
            try:
                idx = int(parts[2])
                r, c = linear_index_to_rc(idx)
            except Exception as e:
                print(f"Bad index: {e}")
                continue

            if piece_name not in NAME_TO_FEN:
                print("Unknown piece name.")
                continue

            board_piece = board_state[r][c]
            if board_piece == ".":
                print(f"No piece at ({r}, {c})")
                continue

            if board_piece not in NAME_TO_FEN[piece_name]:
                print(f"Piece mismatch at ({r}, {c}): board has '{board_piece}' ({FEN_TO_NAME.get(board_piece)})")
                continue

            moves = get_moves(board_state, r, c)
            best = best_move_for_piece(board_state, r, c, moves)
            show_position(board_state, selected=(r, c), moves=moves, best_move=best)
            print(f"{piece_name} at ({r}, {c}) -> {moves}")
            continue

        if cmd.lower().startswith("move "):
            parts = cmd.split()
            if len(parts) != 4:
                print("Use: move <piece_name> <row> <col>")
                continue

            piece_name = parts[1].lower()

            try:
                r = int(parts[2])
                c = int(parts[3])
            except ValueError:
                print("Row and col must be integers.")
                continue

            if not in_bounds(r, c):
                print("Out of bounds.")
                continue

            if piece_name not in NAME_TO_FEN:
                print("Unknown piece name.")
                continue

            board_piece = board_state[r][c]
            if board_piece == ".":
                print(f"No piece at ({r}, {c})")
                continue

            if board_piece not in NAME_TO_FEN[piece_name]:
                print(f"Piece mismatch at ({r}, {c}): board has '{board_piece}' ({FEN_TO_NAME.get(board_piece)})")
                continue

            moves = get_moves(board_state, r, c)
            best = best_move_for_piece(board_state, r, c, moves)
            show_position(board_state, selected=(r, c), moves=moves, best_move=best)
            print(f"{piece_name} at ({r}, {c}) -> {moves}")
            continue

        print("Unknown command.")

if __name__ == "__main__":
    main()
