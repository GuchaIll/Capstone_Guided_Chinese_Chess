# CV Module

This folder contains the computer vision pipeline for the guided Chinese chess project.

## Features
- ArUco-based board localization and warp
- YOLO-based piece detection
- Grid mapping and FEN generation
- Manual grid calibration support
- Optional LED-off handshake before capture

## Main scripts
- `board_pipeline_yolo8.py`
- `board_pipeline_yolox.py`

## Input
- camera frame

## Output
- FEN string
- debug images in `output/`

## Calibration
Saved calibration file:
- `calibration/grid_calibration.npy`

## Run
```bash
python board_pipeline_yolo8.py
#or 
python board_pipeline_yolox.py