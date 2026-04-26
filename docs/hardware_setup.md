# Hardware Setup Guide

This guide walks through a three-machine physical-board setup:

1. The main computer runs the Docker stack.
2. A CV computer runs the camera pipeline and publishes board state.
3. A Raspberry Pi runs the LED controller.

If you want to combine roles, you can run the CV pipeline on the Pi instead of a separate CV computer. The network and startup order stay the same.

---

## 1. Topology

Use this guide when your setup looks like this:

```text
Main computer
  - docker compose stack
  - frontend on :3000
  - state bridge on :5003

CV computer
  - USB / CSI camera
  - cv/board_pipeline_yolo8.py
  - posts FEN to http://<main-ip>:5003/state/fen

Raspberry Pi
  - ledsystem/led_server.py on :5000
  - ledsystem/bridge_subscriber.py
  - subscribes to http://<main-ip>:5003/state/events
```

All three devices must be on the same LAN.

Recommended static or reserved IPs:

| Device | Example IP | Why it matters |
|---|---|---|
| Main computer | `192.168.1.100` | CV and Pi must reach the state bridge here |
| CV computer | `192.168.1.101` | Only needed for remote access / debugging |
| Raspberry Pi | `192.168.1.102` | Useful if you later ssh into the Pi |

Important ports:

| Service | Host | Port |
|---|---|---|
| Frontend | Main computer | `3000` |
| Go dashboard | Main computer | `5002` |
| State bridge | Main computer | `5003` |
| LED server | Raspberry Pi | `5000` |

---

## 2. Before You Start

You will need:

- Docker Desktop on the main computer
- Python 3.10+ on the CV computer
- Python 3 on the Raspberry Pi
- A camera aimed at the board
- A NeoPixel GRBW strip wired to Raspberry Pi GPIO `D18`
- This repository checked out on every machine that needs to run code
- Download trained YOLOv8 weights (https://drive.google.com/uc?export=download&id=105-iI2_ArfrD1dKi1qAU0owMpz2jPXdq)

One repo detail is important before setup:

- The CV script expects to run from the `cv/` directory.
- The CV script currently looks for YOLO weights at `cv/models/best.pt`.
- That file is not present in this repo by default, so you must place your trained weights there or change `MODEL_PATH` in `cv/board_pipeline_yolo8.py`.

---

## 3. Main Computer Setup

This is the machine that runs the product stack in Docker (only run the first time)

### Step 1. Install and clone

```bash
git clone --recurse-submodules <repo-url>
cd Capstone_Guided_Chinese_Chess
cp .env.example .env
```

### Step 2. Start the stack

```bash
docker compose up --build -d
```

This starts the main services, including:

- `client` on `:3000`
- `state-bridge` on `:5003`
- `go-coaching` on `:5002`
- `engine`, `coaching`, `chromadb`, `embedding`, and `kibo`

### Step 3. Find the main computer IP

Use the LAN IP, not `localhost`.

Examples:

```bash
# macOS
ipconfig getifaddr en0

# Linux
hostname -I
```

In the rest of this guide, replace `<main-ip>` with that address, for example `192.168.1.100`.

### Step 4. Verify the main stack

From the main computer:

```bash
curl http://localhost:5003/health
docker compose ps
```

Open these pages in a browser:

- `http://localhost:3000`
- `http://localhost:3000/hardware`
- `http://localhost:5002/dashboard/`

### Step 5. Allow other machines to reach the bridge

Make sure the CV computer and the Pi can reach:

- `http://<main-ip>:5003/health`
- `http://<main-ip>:5003/state`
- `http://<main-ip>:5003/state/events`

If your OS firewall is enabled, allow inbound connections to at least:

- `3000`
- `5002`
- `5003`

---

## 4. CV Computer Setup

This machine is responsible for capturing the board and publishing `cv_fen` to the state bridge.

### Step 1. Clone the repo

```bash
git clone --recurse-submodules <repo-url>
cd Capstone_Guided_Chinese_Chess
```

### Step 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r cv/requirements.txt
```

### Step 3. Provide the model weights

Put your YOLO weights at:

```text
cv/models/best.pt
```

If you want a different filename or location, update `MODEL_PATH` in:

- `cv/board_pipeline_yolo8.py`

### Step 4. Create the expected runtime folders

The script writes captures and calibration files relative to `cv/`.

```bash
mkdir -p cv/output cv/calibration
```

### Step 5. Review the camera settings

Open `cv/board_pipeline_yolo8.py` and check these values before first launch:

- `CAMERA_INDEX = 1`
- `MODEL_PATH = "models/best.pt"`
- `AUTO_CAPTURE_ENABLED = False`
- `MANUAL_CAPTURE_KEY = ord("c")`
- `BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:5003")`

Typical first change:

- If your camera is the default webcam, change `CAMERA_INDEX` from `1` to `0`.

### Step 6. Start the CV pipeline

Run from the `cv/` directory so relative paths resolve correctly:

```bash
cd cv
BRIDGE_URL=http://<main-ip>:5003 ../.venv/bin/python board_pipeline_yolo8.py
```

### Step 7. Verify CV-to-bridge connectivity

When the script is running:

- the camera window should open
- all 4 ArUco markers must be visible for a valid full-board warp
- pressing `c` triggers a capture
- the script posts the generated FEN to `http://<main-ip>:5003/state/fen`

On the main computer, refresh `http://localhost:3000/hardware` and confirm:

- `SSE Event Bus` is connected
- `Camera / CV Service` updates after a capture

### Notes about current behavior

The CV script in this repo is currently manual-capture by default:

- `AUTO_CAPTURE_ENABLED = False`
- capture is triggered with the `c` key

That means the normal physical move flow today is:

1. Move the piece on the real board.
2. Press `c` on the CV computer to publish the new board state.
3. Press `End Turn` in the frontend on the main computer.

---

## 5. Raspberry Pi LED Setup

This machine runs the LED hardware layer and subscribes to the bridge SSE stream.

### Step 1. Prepare the Pi

On the Raspberry Pi:

```bash
git clone --recurse-submodules <repo-url>
cd Capstone_Guided_Chinese_Chess
python3 -m venv .venv
source .venv/bin/activate
pip install flask adafruit-blinka adafruit-circuitpython-neopixel
```

Why these packages:

- `flask` powers `ledsystem/led_server.py`
- `adafruit-blinka` provides the `board` module
- `adafruit-circuitpython-neopixel` provides NeoPixel control

### Step 2. Confirm the LED wiring assumptions

The current LED code expects:

- GPIO pin `D18`
- `400` total pixels
- `GRBW` color order

Those values live in:

- `ledsystem/led_board.py`

If your strip differs, update that file before running the server.

### Step 3. Start the LED server

In one terminal on the Pi:

```bash
cd /path/to/Capstone_Guided_Chinese_Chess
source .venv/bin/activate
python ledsystem/led_server.py
```

If you hit GPIO or permissions errors, rerun it with:

```bash
sudo -E .venv/bin/python ledsystem/led_server.py
```

The LED server listens on:

```text
http://localhost:5000
```

### Step 4. Start the bridge subscriber

In a second terminal on the Pi:

```bash
cd /path/to/Capstone_Guided_Chinese_Chess
source .venv/bin/activate
python ledsystem/bridge_subscriber.py \
  --bridge-url http://<main-ip>:5003 \
  --led-url http://localhost:5000
```

The subscriber:

- connects to `http://<main-ip>:5003/state/events`
- listens for bridge SSE events
- translates them into LED server `POST` calls

### Step 5. Verify Pi-to-bridge connectivity

From the Pi:

```bash
curl http://<main-ip>:5003/health
```

When `bridge_subscriber.py` connects successfully, it should log that the SSE stream is connected.

On the main computer hardware dashboard, LED activity should start appearing once events are published.

---

## 6. Recommended Startup Order

Bring the system up in this order:

1. Start the Docker stack on the main computer.
2. Confirm `http://<main-ip>:5003/health` is healthy.
3. Start `ledsystem/led_server.py` on the Raspberry Pi.
4. Start `ledsystem/bridge_subscriber.py` on the Raspberry Pi.
5. Start `cv/board_pipeline_yolo8.py` on the CV computer.
6. Open `http://<main-ip>:3000/hardware` on the main computer.

This order makes debugging much easier because each downstream machine can immediately reach the bridge.

---

## 7. First End-to-End Test

Use this sequence for the first bring-up test.

### Test A. Bridge and SSE

1. Open `http://<main-ip>:3000/hardware`.
2. Confirm the `SSE Event Bus` card says `Connected`.

If it says `Disconnected`, the frontend is not reaching the bridge proxy.

### Test B. CV publish

1. Put the board in view of the camera.
2. Make sure the 4 ArUco markers are visible.
3. On the CV computer, press `c`.

Expected result:

- the CV script prints a FEN
- the hardware dashboard shows a new camera event

### Test C. LED subscriber

After a successful CV publish:

- the Pi subscriber should react to bridge events
- the LED board should redraw from the latest FEN

### Test D. Physical move loop

1. Move a piece on the real board.
2. Press `c` on the CV computer.
3. Press `End Turn` in the browser on the main computer.

Expected result:

- the bridge compares `cv_fen` to the current engine position
- if legal, the move is accepted
- if illegal, the frontend reports the mismatch and the previous state remains authoritative

---

## 8. Troubleshooting

| Symptom | Most likely cause | What to check |
|---|---|---|
| Hardware dashboard shows bridge SSE disconnected | Main stack not healthy or browser cannot reach `/bridge/state/events` | `docker compose ps`, `http://localhost:5003/health`, reload `/hardware` |
| CV script starts but never captures a valid board | Missing ArUco markers or wrong camera index | `CAMERA_INDEX`, marker visibility, warped board window |
| CV script fails on startup with missing model file | `cv/models/best.pt` is absent | Add weights or update `MODEL_PATH` |
| CV capture runs but frontend says no camera board position is available yet | CV publish never reached the bridge | `BRIDGE_URL`, `curl http://<main-ip>:5003/health`, main hardware dashboard |
| LED server crashes on import | Missing Pi hardware packages | Install `adafruit-blinka` and `adafruit-circuitpython-neopixel` |
| LED server starts but lights do not respond | Wiring mismatch or permission issue | GPIO `D18`, pixel count, run with `sudo -E` if needed |
| Pi subscriber keeps reconnecting | Pi cannot reach the main bridge | `curl http://<main-ip>:5003/health` from the Pi |

---

## 9. Related Docs

- `README.md` for the full software stack
- `docs/led_controller_manual.md` for LED colors and event mapping
- `docs/bridge_server_flow.md` for the bridge event lifecycle

