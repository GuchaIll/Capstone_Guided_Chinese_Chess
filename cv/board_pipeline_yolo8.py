import os
import cv2
import math
import json
import time
import threading
import urllib.request
import urllib.error
from collections import Counter

import numpy as np
from flask import Flask, jsonify
from ultralytics import YOLO


# =========================
# config
# =========================

CAMERA_INDEX = 1

REQUIRED_IDS = [0, 1, 2, 3]
WARP_W = 900
WARP_H = 1000

# These control how much source area is used for perspective warp.
# Bigger pad = zoom out, more area visible.
# Smaller or negative pad = zoom in, less area visible.
LEFT_PAD = -20
RIGHT_PAD = -20
TOP_PAD = -110
BOTTOM_PAD = -110
PAD_STEP = 10

BOARD_LEFT = 75
BOARD_RIGHT = 825
BOARD_TOP = 60
BOARD_BOTTOM = 945

GRID_COLS = 9
GRID_ROWS = 10

SAVE_CAPTURE_IMAGE = True
CAPTURE_PATH = "cv/output/http_capture.jpg"
DEBUG_CROP_PATH = "cv/output/board_crop_debug.jpg"

SHOW_RAW_WINDOW = True
SHOW_WARPED_WINDOW = True
SHOW_DETECTIONS_WINDOW = True

MODEL_PATH = "cv/models/best.pt"
YOLO_IMGSZ = 640
YOLO_CONF = 0.25
YOLO_DEVICE = "cpu"

POINT_MODE = "center"
DISTANCE_THRESHOLD_RATIO = 0.45

REQUIRE_FULL_BOARD_FOR_CAPTURE = True
KEEP_LAST_VALID_BOARD = True

USE_MANUAL_GRID_CALIBRATION = True
GRID_CALIBRATION_FILE = "cv/calibration/grid_calibration.npy"
GRID_OUTER_OFFSET = 50

LED_HANDSHAKE_ENABLED = False
LED_OFF_BEFORE_CAPTURE_SEC = 0.10
LED_RESTORE_AFTER_CAPTURE = True

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:5003")
CV_SERVER_HOST = os.getenv("CV_SERVER_HOST", "0.0.0.0")
CV_SERVER_PORT = int(os.getenv("CV_SERVER_PORT", "5005"))

# Uppercase = red, lowercase = black
CLASS_TO_FEN = {
    "R_red": "R",
    "H_red": "H",
    "E_red": "E",
    "A_red": "A",
    "G_red": "G",
    "C_red": "C",
    "S_red": "S",
    "R_bla": "r",
    "H_bla": "h",
    "E_bla": "e",
    "A_bla": "a",
    "G_bla": "g",
    "C_bla": "c",
    "S_bla": "s",
}

VALID_FEN_PIECES = set("RHEAGCSrheagcs")
DEFAULT_SIDE_TO_MOVE = "w"
DEFAULT_EXTRA_FEN = "- - 0 1"


# =========================
# shared state
# =========================

app = Flask(__name__)
state_lock = threading.Lock()

capture_requested = False
last_result = {
    "status": "not_ready",
    "fen": None,
    "issues": [],
    "detections": 0,
    "assigned": 0,
}

calib_points = []
calib_ready = False
saved_board_corners = None


# =========================
# Flask endpoints
# =========================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "cv"})


@app.route("/capture", methods=["POST"])
def request_capture():
    global capture_requested

    with state_lock:
        capture_requested = True

    return jsonify({"status": "capture_requested"})


@app.route("/last_result", methods=["GET"])
def get_last_result():
    with state_lock:
        return jsonify(last_result.copy())


# =========================
# calibration helpers
# =========================

def warped_mouse_callback(event, x, y, flags, param):
    global calib_points, calib_ready

    if event == cv2.EVENT_LBUTTONDOWN:
        if len(calib_points) < 4:
            calib_points.append([x, y])
            print(f"Calibration point {len(calib_points)}: ({x}, {y})")

        if len(calib_points) == 4:
            calib_ready = True
            print("Grid calibration points ready")


def reset_grid_calibration():
    global calib_points, calib_ready, saved_board_corners

    calib_points = []
    calib_ready = False
    saved_board_corners = None

    if os.path.exists(GRID_CALIBRATION_FILE):
        os.remove(GRID_CALIBRATION_FILE)
        print(f"Deleted {GRID_CALIBRATION_FILE}")

    print("Grid calibration reset")


def save_grid_calibration(points, path=GRID_CALIBRATION_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    arr = np.array(points, dtype=np.float32)
    np.save(path, arr)
    print(f"Saved grid calibration to {path}")


def load_grid_calibration(path=GRID_CALIBRATION_FILE):
    global saved_board_corners

    if os.path.exists(path):
        saved_board_corners = np.load(path).astype(np.float32)
        print(f"Loaded grid calibration from {path}")
    else:
        saved_board_corners = None


def draw_points(img, points, color=(0, 0, 255), label_prefix=""):
    vis = img.copy()

    for i, p in enumerate(points):
        x, y = int(p[0]), int(p[1])
        cv2.circle(vis, (x, y), 6, color, -1)
        cv2.putText(
            vis,
            f"{label_prefix}{i}",
            (x + 8, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    return vis


def board_corners_to_bounds(board_corners):
    xs = board_corners[:, 0]
    ys = board_corners[:, 1]

    board_left = float(np.min(xs))
    board_right = float(np.max(xs))
    board_top = float(np.min(ys))
    board_bottom = float(np.max(ys))

    return board_left, board_right, board_top, board_bottom


def get_board_corners_for_grid():
    global saved_board_corners

    if saved_board_corners is not None:
        return saved_board_corners.copy()

    return np.array(
        [
            [BOARD_LEFT, BOARD_TOP],
            [BOARD_RIGHT, BOARD_TOP],
            [BOARD_RIGHT, BOARD_BOTTOM],
            [BOARD_LEFT, BOARD_BOTTOM],
        ],
        dtype=np.float32,
    )


def crop_with_offset(img, board_corners, offset=50):
    x1 = max(0, int(np.min(board_corners[:, 0]) - offset))
    x2 = min(img.shape[1], int(np.max(board_corners[:, 0]) + offset))
    y1 = max(0, int(np.min(board_corners[:, 1]) - offset))
    y2 = min(img.shape[0], int(np.max(board_corners[:, 1]) + offset))
    return img[y1:y2, x1:x2]


# =========================
# aruco / warp / grid
# =========================

def order_board_corners(marker_dict):
    top_left = marker_dict[0][2]
    top_right = marker_dict[1][3]
    bottom_right = marker_dict[2][0]
    bottom_left = marker_dict[3][1]

    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def draw_corner_points(img, pts, color=(255, 0, 0)):
    for i, p in enumerate(pts):
        x, y = int(p[0]), int(p[1])
        cv2.circle(img, (x, y), 6, color, -1)
        cv2.putText(
            img,
            str(i),
            (x + 8, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )


def expand_src_asymmetric(src, left_pad=0, right_pad=0, top_pad=0, bottom_pad=0):
    src = src.astype(np.float32).copy()

    src[0, 0] -= left_pad
    src[3, 0] -= left_pad

    src[1, 0] += right_pad
    src[2, 0] += right_pad

    src[0, 1] -= top_pad
    src[1, 1] -= top_pad

    src[2, 1] += bottom_pad
    src[3, 1] += bottom_pad

    return src


def generate_grid_points(board_left, board_top, board_right, board_bottom, cols=9, rows=10):
    xs = np.linspace(board_left, board_right, cols)
    ys = np.linspace(board_top, board_bottom, rows)

    grid = np.zeros((rows, cols, 2), dtype=np.float32)

    for r in range(rows):
        for c in range(cols):
            grid[r, c] = [xs[c], ys[r]]

    return grid


def draw_grid_points(img, grid, radius=5):
    vis = img.copy()
    rows, cols = grid.shape[:2]

    for r in range(rows):
        for c in range(cols):
            x, y = grid[r, c]
            x, y = int(x), int(y)

            cv2.circle(vis, (x, y), radius, (0, 255, 0), -1)
            cv2.putText(
                vis,
                f"{r},{c}",
                (x + 5, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (0, 0, 255),
                1,
            )

    return vis


def find_nearest_grid_point(cx, cy, grid):
    rows, cols = grid.shape[:2]

    min_dist = float("inf")
    best_rc = None
    best_xy = None

    for r in range(rows):
        for c in range(cols):
            gx, gy = grid[r, c]
            dist = (cx - gx) ** 2 + (cy - gy) ** 2

            if dist < min_dist:
                min_dist = dist
                best_rc = (r, c)
                best_xy = (gx, gy)

    return best_rc, best_xy, math.sqrt(min_dist)


def get_grid_spacing(grid):
    dx = abs(grid[0, 1, 0] - grid[0, 0, 0])
    dy = abs(grid[1, 0, 1] - grid[0, 0, 1])
    return float(dx), float(dy)


def detect_and_warp_aruco(frame, detector, dst):
    result = {
        "raw_vis": frame.copy(),
        "has_ids": False,
        "have_full_board": False,
        "ids_flat": [],
        "warped": None,
        "marker_count": 0,
        "aruco_src": None,
    }

    corners, ids, _ = detector.detectMarkers(frame)

    if ids is None or len(ids) == 0:
        return result

    result["has_ids"] = True
    cv2.aruco.drawDetectedMarkers(result["raw_vis"], corners, ids)

    ids_flat = ids.flatten()
    result["ids_flat"] = list(map(int, ids_flat))
    result["marker_count"] = len(ids_flat)

    marker_dict = {}
    for i, marker_id in enumerate(ids_flat):
        marker_dict[int(marker_id)] = corners[i][0]

    if not all(mid in marker_dict for mid in REQUIRED_IDS):
        return result

    result["have_full_board"] = True

    src = order_board_corners(marker_dict)
    src = expand_src_asymmetric(
        src,
        left_pad=LEFT_PAD,
        right_pad=RIGHT_PAD,
        top_pad=TOP_PAD,
        bottom_pad=BOTTOM_PAD,
    )

    result["aruco_src"] = src
    draw_corner_points(result["raw_vis"], src, color=(255, 0, 0))

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(frame, M, (WARP_W, WARP_H))

    result["warped"] = warped
    return result


# =========================
# YOLO
# =========================

def load_model(model_path):
    return YOLO(model_path)


def run_yolo_on_warped(model, warped):
    results = model.predict(
        source=warped,
        imgsz=YOLO_IMGSZ,
        conf=YOLO_CONF,
        verbose=False,
        device=YOLO_DEVICE,
    )

    result = results[0]
    names = result.names
    detections = []

    if result.boxes is None:
        return detections

    boxes_xyxy = result.boxes.xyxy.cpu().numpy()
    confs = result.boxes.conf.cpu().numpy()
    clss = result.boxes.cls.cpu().numpy().astype(int)

    for box, conf, cls_idx in zip(boxes_xyxy, confs, clss):
        x1, y1, x2, y2 = box.tolist()
        class_name = names[int(cls_idx)]

        detections.append(
            {
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "conf": float(conf),
                "class_name": class_name,
            }
        )

    return detections


# =========================
# detection -> grid
# =========================

def bbox_to_anchor_point(bbox, mode="center"):
    x1, y1, x2, y2 = bbox

    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0

    if mode == "center":
        return cx, cy

    if mode == "lower_center":
        ay = 0.35 * y1 + 0.65 * y2
        return cx, ay

    return cx, cy


def map_detections_to_grid(detections, grid):
    dx, dy = get_grid_spacing(grid)
    max_dist = DISTANCE_THRESHOLD_RATIO * min(dx, dy)

    mapped = []

    for det in detections:
        cx, cy = bbox_to_anchor_point(det["bbox"], POINT_MODE)
        rc, xy, dist = find_nearest_grid_point(cx, cy, grid)

        if dist > max_dist:
            continue

        mapped.append(
            {
                **det,
                "anchor": [float(cx), float(cy)],
                "grid_rc": rc,
                "grid_xy": [float(xy[0]), float(xy[1])],
                "grid_dist": float(dist),
            }
        )

    return mapped


def resolve_grid_conflicts(mapped_detections):
    best_per_cell = {}

    for det in mapped_detections:
        rc = det["grid_rc"]

        if rc not in best_per_cell:
            best_per_cell[rc] = det
            continue

        current = best_per_cell[rc]

        better = False
        if det["conf"] > current["conf"]:
            better = True
        elif det["conf"] == current["conf"] and det["grid_dist"] < current["grid_dist"]:
            better = True

        if better:
            best_per_cell[rc] = det

    return list(best_per_cell.values())


def draw_assignments(img, assigned):
    vis = img.copy()

    for det in assigned:
        x1, y1, x2, y2 = det["bbox"]
        ax, ay = det["anchor"]
        gx, gy = det["grid_xy"]
        rc = det["grid_rc"]
        label = f'{det["class_name"]}->{rc[0]},{rc[1]}'

        cv2.rectangle(vis, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 255), 2)
        cv2.circle(vis, (int(ax), int(ay)), 4, (0, 255, 255), -1)
        cv2.circle(vis, (int(gx), int(gy)), 6, (255, 255, 0), -1)
        cv2.line(vis, (int(ax), int(ay)), (int(gx), int(gy)), (255, 255, 0), 1)

        cv2.putText(
            vis,
            label,
            (int(x1), max(20, int(y1) - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 0, 255),
            2,
        )

    return vis


# =========================
# board / fen / sanity
# =========================

def make_empty_board():
    return [["." for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)]


def assigned_to_board(assigned):
    board = make_empty_board()
    unknown_classes = []

    for det in assigned:
        class_name = det["class_name"]
        symbol = CLASS_TO_FEN.get(class_name)

        if symbol is None:
            unknown_classes.append(class_name)
            continue

        r, c = det["grid_rc"]
        board[r][c] = symbol

    return board, unknown_classes


def board_to_fen_rows(board):
    rows_out = []

    for row in board:
        count = 0
        s = ""

        for cell in row:
            if cell == ".":
                count += 1
            else:
                if count > 0:
                    s += str(count)
                    count = 0
                s += cell

        if count > 0:
            s += str(count)

        rows_out.append(s)

    return rows_out


def board_to_fen(board, side_to_move=DEFAULT_SIDE_TO_MOVE, extra_fen=DEFAULT_EXTRA_FEN):
    rows_out = board_to_fen_rows(board)
    board_part = "/".join(rows_out)
    return f"{board_part} {side_to_move} {extra_fen}"


def count_pieces(board):
    counter = Counter()

    for row in board:
        for cell in row:
            if cell != ".":
                counter[cell] += 1

    return counter


def sanity_check_board(board):
    issues = []
    counter = count_pieces(board)
    total_pieces = sum(counter.values())

    if total_pieces > 32:
        issues.append(f"too many pieces: {total_pieces}")

    for piece in counter:
        if piece not in VALID_FEN_PIECES:
            issues.append(f"invalid piece symbol: {piece}")

    if counter["G"] > 1:
        issues.append("more than one red general")
    if counter["g"] > 1:
        issues.append("more than one black general")

    if counter["A"] > 2:
        issues.append("too many red advisors")
    if counter["a"] > 2:
        issues.append("too many black advisors")

    if counter["E"] > 2:
        issues.append("too many red elephants")
    if counter["e"] > 2:
        issues.append("too many black elephants")

    if counter["H"] > 2:
        issues.append("too many red horses")
    if counter["h"] > 2:
        issues.append("too many black horses")

    if counter["R"] > 2:
        issues.append("too many red chariots")
    if counter["r"] > 2:
        issues.append("too many black chariots")

    if counter["C"] > 2:
        issues.append("too many red cannons")
    if counter["c"] > 2:
        issues.append("too many black cannons")

    if counter["S"] > 5:
        issues.append("too many red soldiers")
    if counter["s"] > 5:
        issues.append("too many black soldiers")

    return issues


def board_to_text(board):
    return "\n".join(" ".join(board[r]) for r in range(GRID_ROWS))


# =========================
# display helpers
# =========================

def put_status_text(img, lines, x=20, y=30, dy=30, color=(0, 255, 255)):
    vis = img.copy()
    yy = y

    for line in lines:
        cv2.putText(
            vis,
            str(line),
            (x, yy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            color,
            2,
        )
        yy += dy

    return vis


# =========================
# bridge / LED
# =========================

def _bridge_post(path, payload):
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{BRIDGE_URL}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=2) as res:
            status = res.getcode()
            if status >= 400:
                print(f"[bridge] {path} failed: {status}")
                return False
            return True

    except urllib.error.HTTPError as e:
        print(f"[bridge] {path} HTTP error: {e.code}")
    except urllib.error.URLError as e:
        print(f"[bridge] {path} connection failed: {e.reason}")
    except Exception as exc:
        print(f"[bridge] {path} unexpected error: {exc}")

    return False


def publish_fen(fen):
    _bridge_post("/state/fen", {"fen": fen, "source": "cv"})


def notify_led_off():
    _bridge_post("/state/led-command", {"command": "off"})
    print("LED OFF requested")


def notify_led_on():
    _bridge_post("/state/led-command", {"command": "on"})
    print("LED ON requested")


def prepare_frame_for_capture(warped):
    if LED_HANDSHAKE_ENABLED:
        notify_led_off()
        time.sleep(LED_OFF_BEFORE_CAPTURE_SEC)

    capture_frame = warped.copy()

    if LED_HANDSHAKE_ENABLED and LED_RESTORE_AFTER_CAPTURE:
        notify_led_on()

    return capture_frame


# =========================
# capture pipeline
# =========================

def process_capture(model, warped, grid, current_board_corners, last_valid_state):
    last_valid_board = last_valid_state["board"]
    last_valid_fen = last_valid_state["fen"]
    last_assigned = last_valid_state["assigned"]

    capture_frame = prepare_frame_for_capture(warped)

    if SAVE_CAPTURE_IMAGE:
        os.makedirs(os.path.dirname(CAPTURE_PATH), exist_ok=True)
        cv2.imwrite(CAPTURE_PATH, capture_frame)
        print(f"Saved capture to {CAPTURE_PATH}")

    if DEBUG_CROP_PATH:
        os.makedirs(os.path.dirname(DEBUG_CROP_PATH), exist_ok=True)
        crop_debug = crop_with_offset(capture_frame, current_board_corners, GRID_OUTER_OFFSET)
        cv2.imwrite(DEBUG_CROP_PATH, crop_debug)

    detections = run_yolo_on_warped(model, capture_frame)
    mapped = map_detections_to_grid(detections, grid)
    assigned = resolve_grid_conflicts(mapped)
    board, unknown_classes = assigned_to_board(assigned)
    issues = sanity_check_board(board)
    fen = board_to_fen(board)

    use_this_board = True

    if unknown_classes:
        issues.append("unknown classes: " + ", ".join(sorted(set(unknown_classes))))

    if issues and KEEP_LAST_VALID_BOARD and last_valid_board is not None:
        use_this_board = False

    if use_this_board:
        if not issues:
            last_valid_state["board"] = [row[:] for row in board]
            last_valid_state["fen"] = fen
            last_valid_state["assigned"] = assigned[:]
    else:
        board = [row[:] for row in last_valid_board]
        fen = last_valid_fen
        assigned = last_assigned[:]
        issues = ["rejected current frame, using last valid board"] + issues

    print()
    print("=" * 60)
    print("HTTP CAPTURE TRIGGERED")
    print("detections:", len(detections))
    print("mapped:", len(mapped))
    print("assigned:", len(assigned))
    print("board:")
    print(board_to_text(board))
    print("fen:")
    print(fen)

    publish_fen(fen)

    if issues:
        print("issues:")
        for item in issues:
            print("-", item)

    result_payload = {
        "status": "ok" if not issues else "ok_with_issues",
        "fen": fen,
        "issues": issues,
        "detections": len(detections),
        "mapped": len(mapped),
        "assigned": len(assigned),
    }

    with state_lock:
        last_result.clear()
        last_result.update(result_payload)

    return capture_frame, assigned, fen, issues


# =========================
# keyboard pad control
# =========================

def adjust_all_pads(delta):
    global LEFT_PAD, RIGHT_PAD, TOP_PAD, BOTTOM_PAD

    LEFT_PAD += delta
    RIGHT_PAD += delta
    TOP_PAD += delta
    BOTTOM_PAD += delta

    if delta > 0:
        action = "zoom out / expand warp"
    else:
        action = "zoom in / shrink warp"

    #print(f"{action}: L={LEFT_PAD}, R={RIGHT_PAD}, T={TOP_PAD}, B={BOTTOM_PAD}")


def reset_pads_to_zero():
    global LEFT_PAD, RIGHT_PAD, TOP_PAD, BOTTOM_PAD

    LEFT_PAD = 0
    RIGHT_PAD = 0
    TOP_PAD = 0
    BOTTOM_PAD = 0

    #print("Reset warp pads to zero")


# =========================
# main
# =========================

def main():
    global calib_points, calib_ready, saved_board_corners, capture_requested

    load_grid_calibration()

    model = load_model(MODEL_PATH)

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {CAMERA_INDEX}")

    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, params)

    dst = np.array(
        [
            [0, 0],
            [WARP_W - 1, 0],
            [WARP_W - 1, WARP_H - 1],
            [0, WARP_H - 1],
        ],
        dtype=np.float32,
    )

    last_valid_state = {
        "board": None,
        "fen": None,
        "assigned": [],
    }

    if SHOW_WARPED_WINDOW:
        cv2.namedWindow("warped board with grid", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("warped board with grid", 900, 1000)
        if USE_MANUAL_GRID_CALIBRATION:
            cv2.setMouseCallback("warped board with grid", warped_mouse_callback)

    print(f"CV Flask server running at http://{CV_SERVER_HOST}:{CV_SERVER_PORT}")
    print("POST /capture to trigger one board capture")
    print("GET /last_result to see the latest FEN result")
    print("Keyboard controls:")
    print("  + or = : zoom out / expand warp")
    print("  - or _ : zoom in / shrink warp")
    print("  0      : reset pads to 0")
    print("  r      : reset manual grid calibration")
    print("  q/ESC  : quit")

    while True:
        ret, frame = cap.read()

        if not ret or frame is None:
            print("Failed to read frame")
            key = cv2.waitKey(1) & 0xFF
            if key == 27 or key == ord("q"):
                break
            continue

        pipeline = detect_and_warp_aruco(frame, detector, dst)
        raw_vis = pipeline["raw_vis"]
        warped = pipeline["warped"]

        raw_lines = [
            f'markers: {pipeline["marker_count"]}',
            f'full board: {"YES" if pipeline["have_full_board"] else "NO"}',
            "HTTP trigger: POST /capture",
            "+/= zoom out, -/_ zoom in, 0 reset pad",
            "press q or ESC to quit",
        ]

        if saved_board_corners is not None:
            raw_lines.append("grid calibration: loaded")

        if USE_MANUAL_GRID_CALIBRATION:
            raw_lines.append("calibration mode: ON")
            raw_lines.append("click 4 board corners on warped view")
            raw_lines.append("press r to reset calibration")

        if LED_HANDSHAKE_ENABLED:
            raw_lines.append("LED handshake: ON")

        if SHOW_RAW_WINDOW:
            raw_vis_disp = put_status_text(raw_vis, raw_lines, color=(0, 255, 255))
            cv2.imshow("camera", raw_vis_disp)

        key = cv2.waitKey(1) & 0xFF

        if key == 27 or key == ord("q"):
            break

        if key == ord("r"):
            reset_grid_calibration()
            continue

        if key == ord("=") or key == ord("+"):
            adjust_all_pads(PAD_STEP)
            continue

        if key == ord("-") or key == ord("_"):
            adjust_all_pads(-PAD_STEP)
            continue

        if key == ord("0"):
            reset_pads_to_zero()
            continue

        if warped is None:
            if SHOW_WARPED_WINDOW:
                blank = np.zeros((WARP_H, WARP_W, 3), dtype=np.uint8)
                blank = put_status_text(blank, ["Waiting for 4 ArUco markers"], color=(0, 0, 255))
                cv2.imshow("warped board with grid", blank)
                if USE_MANUAL_GRID_CALIBRATION:
                    cv2.setMouseCallback("warped board with grid", warped_mouse_callback)

            with state_lock:
                if capture_requested:
                    capture_requested = False
                    last_result.clear()
                    last_result.update(
                        {
                            "status": "failed",
                            "fen": None,
                            "issues": ["capture requested, but full ArUco board was not visible"],
                            "detections": 0,
                            "mapped": 0,
                            "assigned": 0,
                        }
                    )
                    print("Capture requested, but warped board is not available")

            continue

        if calib_ready:
            saved_board_corners = np.array(calib_points, dtype=np.float32)
            save_grid_calibration(saved_board_corners)
            calib_points = []
            calib_ready = False

        current_board_corners = get_board_corners_for_grid()
        board_left, board_right, board_top, board_bottom = board_corners_to_bounds(current_board_corners)

        grid = generate_grid_points(
            board_left=board_left,
            board_top=board_top,
            board_right=board_right,
            board_bottom=board_bottom,
            cols=GRID_COLS,
            rows=GRID_ROWS,
        )

        warped_disp = draw_grid_points(warped, grid)
        warped_disp = draw_points(warped_disp, current_board_corners, color=(255, 255, 0), label_prefix="B")

        if USE_MANUAL_GRID_CALIBRATION and len(calib_points) > 0:
            warped_disp = draw_points(warped_disp, calib_points, color=(0, 0, 255), label_prefix="C")

        with state_lock:
            request_pending = capture_requested

        warped_status = [
            "HTTP capture: PENDING" if request_pending else "HTTP capture: waiting",
            f"pad L/R/T/B: {LEFT_PAD}, {RIGHT_PAD}, {TOP_PAD}, {BOTTOM_PAD}",
            "+/= zoom out, -/_ zoom in, 0 reset",
            f'grid calib mode: {"ON" if USE_MANUAL_GRID_CALIBRATION else "OFF"}',
            f'crop offset: {GRID_OUTER_OFFSET}',
            f'LED handshake: {"ON" if LED_HANDSHAKE_ENABLED else "OFF"}',
        ]

        warped_disp = put_status_text(warped_disp, warped_status, color=(0, 255, 255))

        if SHOW_WARPED_WINDOW:
            cv2.imshow("warped board with grid", warped_disp)
            if USE_MANUAL_GRID_CALIBRATION:
                cv2.setMouseCallback("warped board with grid", warped_mouse_callback)

        with state_lock:
            should_capture = capture_requested
            if should_capture:
                capture_requested = False

        if REQUIRE_FULL_BOARD_FOR_CAPTURE and not pipeline["have_full_board"]:
            if should_capture:
                with state_lock:
                    last_result.clear()
                    last_result.update(
                        {
                            "status": "failed",
                            "fen": None,
                            "issues": ["capture requested, but full ArUco board was not visible"],
                            "detections": 0,
                            "mapped": 0,
                            "assigned": 0,
                        }
                    )
                print("Capture requested, but full ArUco board was not visible")
            should_capture = False

        if not should_capture:
            continue

        capture_frame, assigned, fen, issues = process_capture(
            model=model,
            warped=warped,
            grid=grid,
            current_board_corners=current_board_corners,
            last_valid_state=last_valid_state,
        )

        if SHOW_DETECTIONS_WINDOW:
            det_vis = draw_assignments(draw_grid_points(capture_frame, grid), assigned)
            det_vis = draw_points(det_vis, current_board_corners, color=(255, 255, 0), label_prefix="B")

            overlay_lines = [
                "trigger: HTTP /capture",
                f"assigned: {len(assigned)}",
                f"fen: {fen}",
            ]

            if issues:
                overlay_lines.append("issues: " + " | ".join(issues[:2]))

            det_vis = put_status_text(det_vis, overlay_lines, color=(255, 255, 0))
            cv2.imshow("detections and assignments", det_vis)

    cap.release()
    cv2.destroyAllWindows()


def start_flask_server():
    app.run(
        host=CV_SERVER_HOST,
        port=CV_SERVER_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    server_thread = threading.Thread(target=start_flask_server, daemon=True)
    server_thread.start()
    main()
