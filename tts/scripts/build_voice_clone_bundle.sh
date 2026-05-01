#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: tts/scripts/build_voice_clone_bundle.sh <voice-id> [extra args...]" >&2
  exit 1
fi

VOICE_ID="$1"
shift

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

python3 tts/prepare_voice_cloning.py --bootstrap
python3 tts/build_voice_clone_bundle.py --voice-id "$VOICE_ID" "$@"
