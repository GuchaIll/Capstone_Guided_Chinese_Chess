#!/usr/bin/env bash
set -euo pipefail

VOLUME_NAME="${1:-guided-chinese-chess-finetuning}"
LOCAL_FINETUNNING_DIR="${2:-./finetunning}"
LOCAL_MODEL_DIR="${3:-}"
REMOTE_FINETUNNING_DIR="/finetunning"
REMOTE_MODEL_DIR="/models/qwen-xiangqi"

modal volume create "${VOLUME_NAME}" >/dev/null 2>&1 || true

echo "Uploading ${LOCAL_FINETUNNING_DIR} -> ${VOLUME_NAME}:${REMOTE_FINETUNNING_DIR}"
modal volume put -f "${VOLUME_NAME}" "${LOCAL_FINETUNNING_DIR}" "${REMOTE_FINETUNNING_DIR}"

if [[ -n "${LOCAL_MODEL_DIR}" ]]; then
  echo "Uploading ${LOCAL_MODEL_DIR} -> ${VOLUME_NAME}:${REMOTE_MODEL_DIR}"
  modal volume put -f "${VOLUME_NAME}" "${LOCAL_MODEL_DIR}" "${REMOTE_MODEL_DIR}"
fi

echo
echo "Current remote contents:"
modal volume ls "${VOLUME_NAME}" / | sed -n '1,120p'
