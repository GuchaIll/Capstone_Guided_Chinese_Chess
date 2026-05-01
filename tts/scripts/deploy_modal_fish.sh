#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

export MODAL_FISH_MODEL="${FISH_TTS_MODEL:-s2-pro}"

modal deploy tts/modal_serve_fish.py "$@"
