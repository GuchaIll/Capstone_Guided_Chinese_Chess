# CV Module

This folder contains the computer vision pipeline for the guided Chinese chess project.

## Features
- ArUco-based board localization and perspective warp
- YOLO-based piece detection (YOLOv8 / YOLOX)
- Grid mapping and FEN generation
- Manual grid calibration support
- Optional LED-off handshake before frame capture

## Main scripts
- `board_pipeline_yolo8.py`
- `board_pipeline_yolox.py`

## Input
- Camera stream (Continuity Camera)
- Optional trigger:
  - manual key press (`c`)
  - or automatic (~200 ms stability)

## Output
- FEN string representing current board state
- Debug images saved to `output/`

Example FEN:
6S2/9/A7C/9/9/9/7G1/3E5

## Trigger Mechanism
- Frame is captured when:
  - user presses `c`
  - OR board remains stable for ~200 ms

## LED Coordination (for integration)
- Before capturing a frame:
  - CV → LED OFF
  - wait ~100 ms
  - capture frame
  - CV → LED ON

- Currently implemented via:
  - `notify_led_off()`
  - `notify_led_on()`

- To be replaced

## Calibration
- Save calibration file to:
  - `calibration/grid_calibration.npy`
- Used to fix board grid position after manual setup

## Run
- python board_pipeline_yolo8.py
- or
- python board_pipeline_yolox.py

## Notes
- Model weights are not included in the repository
- Place models in cv/models/
  - best.pt (YOLOv8)
  - best_ckpt.pth (YOLOX)
- Works best with fixed camera setup and stable lighting