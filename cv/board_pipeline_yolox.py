import os
import sys
import cv2
import numpy as np
import time
import math
from collections import Counter

import torch
import torch.backends.cudnn as cudnn

from yolox.exp import get_exp
from yolox.data.data_augment import ValTransform
from yolox.utils import postprocess


# =========================
# config
# =========================

CAMERA_INDEX = 1

REQUIRED_IDS = [0, 1, 2, 3]
WARP_W = 900
WARP_H = 1000

LEFT_PAD = -20
RIGHT_PAD = -20
TOP_PAD = -110
BOTTOM_PAD = -110

BOARD_LEFT = 75
BOARD_RIGHT = 825
BOARD_TOP = 60
BOARD_BOTTOM = 945

GRID_COLS = 9
GRID_ROWS = 10

STABLE_TIME_SEC = 0.20
DIFF_THRESHOLD = 2.5
BLUR_KSIZE = 5

AUTO_CAPTURE_ENABLED = False
MANUAL_CAPTURE_KEY = ord("c")
SAVE_CAPTURE_IMAGE = True
CAPTURE_PATH = "output/stable_capture.jpg"

SHOW_RAW_WINDOW = True
SHOW_WARPED_WINDOW = True
SHOW_DETECTIONS_WINDOW = True

YOLOX_EXP_FILE = "models/YOLOX_exp.py"
YOLOX_CKPT_PATH = "models/best_ckpt.pth"
YOLOX_CONF = 0.25
YOLOX_NMS = 0.45
YOLOX_TSIZE = 960
YOLOX_DEVICE = "mps"   # "cpu" or "mps"

POINT_MODE = "center"
DISTANCE_THRESHOLD_RATIO = 0.45

REQUIRE_FULL_BOARD_FOR_CAPTURE = True
KEEP_LAST_VALID_BOARD = True

USE_MANUAL_GRID_CALIBRATION = False
GRID_CALIBRATION_FILE = "calibration/grid_calibration.npy"
GRID_OUTER_OFFSET = 50

# YOLOX class names must match your training order exactly
YOLOX_CLASS_NAMES = [
    "A_bla",
    "A_red",
    "C_bla",
    "C_red",
    "R_bla",
    "R_red",
    "E_bla",
    "E_red",
    "G_bla",
    "G_red",
    "H_bla",
    "H_red",
    "S_bla",
    "S_red",
]

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
# global calibration state
# =========================

calib_points = []
calib_ready = False
saved_board_corners = None


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
            2
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

    return np.array([
        [BOARD_LEFT, BOARD_TOP],
        [BOARD_RIGHT, BOARD_TOP],
        [BOARD_RIGHT, BOARD_BOTTOM],
        [BOARD_LEFT, BOARD_BOTTOM]
    ], dtype=np.float32)


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

    src = np.array(
        [top_left, top_right, bottom_right, bottom_left],
        dtype=np.float32
    )
    return src


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
            2
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
                1
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
        bottom_pad=BOTTOM_PAD
    )

    result["aruco_src"] = src
    draw_corner_points(result["raw_vis"], src, color=(255, 0, 0))

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(frame, M, (WARP_W, WARP_H))

    result["warped"] = warped
    return result


# =========================
# stability trigger
# =========================

def preprocess_for_stability(warped):
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (BLUR_KSIZE, BLUR_KSIZE), 0)
    return gray


def compute_frame_diff_score(prev_gray, curr_gray):
    diff = cv2.absdiff(prev_gray, curr_gray)
    score = float(np.mean(diff))
    return score


def update_stability_state(prev_gray, curr_gray, stable_since, diff_threshold):
    score = compute_frame_diff_score(prev_gray, curr_gray)

    if score < diff_threshold:
        if stable_since is None:
            stable_since = time.time()
    else:
        stable_since = None

    return score, stable_since


def is_stable_long_enough(stable_since, stable_time_sec):
    if stable_since is None:
        return False
    return (time.time() - stable_since) >= stable_time_sec


def reset_stability_state():
    return None, None, False


# =========================
# yolox
# =========================

def choose_torch_device():
    if YOLOX_DEVICE == "mps":
        if torch.backends.mps.is_available():
            return torch.device("mps")
        print("MPS requested but not available, falling back to CPU")
    return torch.device("cpu")


def load_yolox_model():
    device = choose_torch_device()

    exp = get_exp(YOLOX_EXP_FILE, None)
    exp.test_conf = YOLOX_CONF
    exp.nmsthre = YOLOX_NMS
    exp.test_size = (YOLOX_TSIZE, YOLOX_TSIZE)

    model = exp.get_model()

    try:
        ckpt = torch.load(YOLOX_CKPT_PATH, map_location=device, weights_only=False)
    except TypeError:
        ckpt = torch.load(YOLOX_CKPT_PATH, map_location=device)

    model.load_state_dict(ckpt["model"])
    model = model.to(device)
    model.eval()

    preproc = ValTransform(legacy=False)

    return {
        "model": model,
        "exp": exp,
        "device": device,
        "preproc": preproc,
    }


def run_yolox_on_warped(detector_bundle, warped):
    model = detector_bundle["model"]
    exp = detector_bundle["exp"]
    device = detector_bundle["device"]
    preproc = detector_bundle["preproc"]

    img_info = {}
    height, width = warped.shape[:2]
    img_info["height"] = height
    img_info["width"] = width

    ratio = min(exp.test_size[0] / height, exp.test_size[1] / width)
    img_info["ratio"] = ratio

    img, _ = preproc(warped, None, exp.test_size)
    img = torch.from_numpy(img).unsqueeze(0).float().to(device)

    with torch.no_grad():
        outputs = model(img)
        outputs = postprocess(
            outputs,
            exp.num_classes,
            exp.test_conf,
            exp.nmsthre,
            class_agnostic=False
        )

    detections = []

    if outputs is None or outputs[0] is None:
        return detections

    output = outputs[0].cpu().numpy()

    for row in output:
        x1, y1, x2, y2, obj_conf, cls_conf, cls_id = row.tolist()
        score = float(obj_conf * cls_conf)
        cls_id = int(cls_id)

        x1 /= ratio
        y1 /= ratio
        x2 /= ratio
        y2 /= ratio

        if cls_id < 0 or cls_id >= len(YOLOX_CLASS_NAMES):
            class_name = f"class_{cls_id}"
        else:
            class_name = YOLOX_CLASS_NAMES[cls_id]

        detections.append({
            "bbox": [float(x1), float(y1), float(x2), float(y2)],
            "conf": score,
            "class_name": class_name,
        })

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

        mapped.append({
            **det,
            "anchor": [float(cx), float(cy)],
            "grid_rc": rc,
            "grid_xy": [float(xy[0]), float(xy[1])],
            "grid_dist": float(dist),
        })

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
            2
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
            2
        )
        yy += dy

    return vis


# =========================
# main
# =========================

def main():
    global calib_points, calib_ready, saved_board_corners

    load_grid_calibration()

    detector_bundle = load_yolox_model()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {CAMERA_INDEX}")

    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, params)

    dst = np.array([
        [0, 0],
        [WARP_W - 1, 0],
        [WARP_W - 1, WARP_H - 1],
        [0, WARP_H - 1]
    ], dtype=np.float32)

    prev_warped_gray, stable_since, captured_once = reset_stability_state()

    last_valid_board = None
    last_valid_fen = None
    last_assigned = []

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

        raw_lines = [
            f'markers: {pipeline["marker_count"]}',
            f'full board: {"YES" if pipeline["have_full_board"] else "NO"}',
            'press c to capture',
            'press q or ESC to quit',
        ]

        if saved_board_corners is not None:
            raw_lines.append('grid calibration: loaded')

        if USE_MANUAL_GRID_CALIBRATION:
            raw_lines.append('calibration mode: ON')
            raw_lines.append('click 4 board corners on warped view')
            raw_lines.append('press r to reset calibration')

        if SHOW_RAW_WINDOW:
            raw_vis_disp = put_status_text(raw_vis, raw_lines, color=(0, 255, 255))
            cv2.imshow("camera", raw_vis_disp)

        warped = pipeline["warped"]

        auto_trigger = False
        manual_trigger = False
        diff_score = None
        stable_text = "NOT READY"

        key = cv2.waitKey(1) & 0xFF

        if key == 27 or key == ord("q"):
            break

        if key == ord("r"):
            reset_grid_calibration()
            prev_warped_gray, stable_since, captured_once = reset_stability_state()
            continue

        if warped is None:
            prev_warped_gray, stable_since, captured_once = reset_stability_state()

            if SHOW_WARPED_WINDOW:
                blank = np.zeros((WARP_H, WARP_W, 3), dtype=np.uint8)
                blank = put_status_text(
                    blank,
                    ["Waiting for 4 ArUco markers"],
                    color=(0, 0, 255)
                )
                cv2.imshow("warped board with grid", blank)

            continue

        if USE_MANUAL_GRID_CALIBRATION:
            cv2.setMouseCallback("warped board with grid", warped_mouse_callback)

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
            rows=GRID_ROWS
        )

        warped_gray = preprocess_for_stability(warped)

        if prev_warped_gray is not None:
            diff_score, stable_since = update_stability_state(
                prev_warped_gray,
                warped_gray,
                stable_since,
                DIFF_THRESHOLD
            )

            if is_stable_long_enough(stable_since, STABLE_TIME_SEC):
                stable_text = "STABLE"
                if AUTO_CAPTURE_ENABLED and not captured_once:
                    auto_trigger = True
                    captured_once = True
            else:
                stable_text = "NOT STABLE"
                captured_once = False
        else:
            stable_text = "WARMING UP"

        prev_warped_gray = warped_gray

        if key == MANUAL_CAPTURE_KEY:
            manual_trigger = True

        warped_disp = draw_grid_points(warped, grid)
        warped_disp = draw_points(warped_disp, current_board_corners, color=(255, 255, 0), label_prefix="B")

        if USE_MANUAL_GRID_CALIBRATION and len(calib_points) > 0:
            warped_disp = draw_points(warped_disp, calib_points, color=(0, 0, 255), label_prefix="C")

        warped_status = [
            f'stability: {stable_text}',
            f'diff: {diff_score:.2f}' if diff_score is not None else 'diff: N/A',
            f'auto capture: {"ON" if AUTO_CAPTURE_ENABLED else "OFF"}',
            f'grid calib mode: {"ON" if USE_MANUAL_GRID_CALIBRATION else "OFF"}',
            f'crop offset: {GRID_OUTER_OFFSET}',
            'detector: YOLOX',
        ]
        warped_disp = put_status_text(warped_disp, warped_status, color=(0, 255, 255))

        if SHOW_WARPED_WINDOW:
            cv2.imshow("warped board with grid", warped_disp)

        should_capture = manual_trigger or auto_trigger

        if REQUIRE_FULL_BOARD_FOR_CAPTURE and not pipeline["have_full_board"]:
            should_capture = False

        if not should_capture:
            continue

        if SAVE_CAPTURE_IMAGE:
            cv2.imwrite(CAPTURE_PATH, warped)
            print(f"Saved capture to {CAPTURE_PATH}")

        crop_debug = crop_with_offset(warped, current_board_corners, GRID_OUTER_OFFSET)
        cv2.imwrite("board_crop_debug.jpg", crop_debug)

        detections = run_yolox_on_warped(detector_bundle, warped)
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
                last_valid_board = [row[:] for row in board]
                last_valid_fen = fen
                last_assigned = assigned[:]
        else:
            board = [row[:] for row in last_valid_board]
            fen = last_valid_fen
            assigned = last_assigned[:]
            issues = ["rejected current frame, using last valid board"] + issues

        print()
        print("=" * 60)
        print("CAPTURE TRIGGERED")
        print("trigger:", "manual" if manual_trigger else "auto")
        print("detections:", len(detections))
        print("mapped:", len(mapped))
        print("assigned:", len(assigned))
        print("board:")
        print(board_to_text(board))
        print("fen:")
        print(fen)
        if issues:
            print("issues:")
            for item in issues:
                print("-", item)

        if SHOW_DETECTIONS_WINDOW:
            det_vis = draw_assignments(draw_grid_points(warped, grid), assigned)
            det_vis = draw_points(det_vis, current_board_corners, color=(255, 255, 0), label_prefix="B")

            overlay_lines = [
                f"trigger: {'manual' if manual_trigger else 'auto'}",
                f"detections: {len(detections)}",
                f"assigned: {len(assigned)}",
                f"fen: {fen}",
            ]

            if issues:
                overlay_lines.append("issues: " + " | ".join(issues[:2]))

            det_vis = put_status_text(det_vis, overlay_lines, color=(255, 255, 0))
            cv2.imshow("detections and assignments", det_vis)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()