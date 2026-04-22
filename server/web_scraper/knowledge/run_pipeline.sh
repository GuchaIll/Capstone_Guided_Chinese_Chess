#!/usr/bin/env bash
# run_pipeline.sh — End-to-end RAG knowledge pipeline runner
#
# Runs all four stages sequentially for a given wave (default: wave 1).
# Logs are written to knowledge/logs/pipeline_<timestamp>.log.
#
# Usage:
#   ./run_pipeline.sh                    # Wave 1, all stages
#   ./run_pipeline.sh --wave 2           # Wave 2 only
#   ./run_pipeline.sh --source-id xqinenglish_opening_basics_05
#   ./run_pipeline.sh --dry-run          # Acquire + normalize + chunk, skip real ingest
#   ./run_pipeline.sh --stage acquire    # Run only the acquire stage
#   ./run_pipeline.sh --force            # Force re-run all stages even if outputs exist
#   CHROMADB_URL=http://chromadb:8000 ./run_pipeline.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Defaults ─────────────────────────────────────────────────────────────────
WAVE=1
SOURCE_ID=""
DRY_RUN=false
FORCE=false
STAGE=""  # empty = all stages
CHROMADB_URL="${CHROMADB_URL:-http://localhost:8000}"
EMBEDDING_URL="${EMBEDDING_URL:-http://localhost:8100}"
RATE_LIMIT=2.0

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --wave)         WAVE="$2";      shift 2 ;;
    --source-id)    SOURCE_ID="$2"; shift 2 ;;
    --dry-run)      DRY_RUN=true;   shift ;;
    --force)        FORCE=true;     shift ;;
    --stage)        STAGE="$2";     shift 2 ;;
    --rate-limit)   RATE_LIMIT="$2";shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Logging setup ─────────────────────────────────────────────────────────────
mkdir -p logs
TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
LOG_FILE="logs/pipeline_${TIMESTAMP}.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "  Xiangqi RAG Pipeline — $(date)"
echo "  wave=${WAVE}  dry_run=${DRY_RUN}  force=${FORCE}"
[[ -n "$SOURCE_ID" ]] && echo "  source_id=${SOURCE_ID}"
[[ -n "$STAGE" ]]     && echo "  stage=${STAGE}"
echo "  chromadb=${CHROMADB_URL}"
echo "  embedding=${EMBEDDING_URL}"
echo "=========================================="

# ── Shared flags ──────────────────────────────────────────────────────────────
FORCE_FLAG=""
$FORCE && FORCE_FLAG="--force"

SOURCE_FLAG=""
[[ -n "$SOURCE_ID" ]] && SOURCE_FLAG="--source-id $SOURCE_ID"

WAVE_FLAG="--wave $WAVE"
[[ -n "$SOURCE_ID" ]] && WAVE_FLAG=""  # source-id overrides wave filter

# ── Stage: acquire ─────────────────────────────────────────────────────────
run_acquire() {
  echo ""
  echo "── Stage 1: Acquire ──────────────────────────────"
  python acquire.py \
    $WAVE_FLAG \
    $SOURCE_FLAG \
    --rate-limit "$RATE_LIMIT" \
    $FORCE_FLAG
  echo "acquire: OK"
}

# ── Stage: normalize ──────────────────────────────────────────────────────────
run_normalize() {
  echo ""
  echo "── Stage 2: Normalize ────────────────────────────"
  python normalize.py \
    $WAVE_FLAG \
    $SOURCE_FLAG \
    $FORCE_FLAG
  echo "normalize: OK"
}

# ── Stage: chunk ──────────────────────────────────────────────────────────────
run_chunk() {
  echo ""
  echo "── Stage 3: Chunk ────────────────────────────────"
  python chunk.py \
    $SOURCE_FLAG \
    $FORCE_FLAG
  echo "chunk: OK"
}

# ── Stage: ingest ──────────────────────────────────────────────────────────
run_ingest() {
  echo ""
  echo "── Stage 4: Ingest ───────────────────────────────"
  INGEST_FLAGS="--chromadb-url $CHROMADB_URL --embedding-url $EMBEDDING_URL $FORCE_FLAG"
  if $DRY_RUN; then
    INGEST_FLAGS="$INGEST_FLAGS --dry-run"
    echo "  [DRY RUN — no data will be written to ChromaDB]"
  fi
  python ingest.py $INGEST_FLAGS
  echo "ingest: OK"
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "$STAGE" in
  acquire)   run_acquire ;;
  normalize) run_normalize ;;
  chunk)     run_chunk ;;
  ingest)    run_ingest ;;
  "")
    run_acquire
    run_normalize
    run_chunk
    run_ingest
    ;;
  *)
    echo "Unknown stage: $STAGE. Valid stages: acquire, normalize, chunk, ingest"
    exit 1
    ;;
esac

echo ""
echo "=========================================="
echo "  Pipeline complete — $(date)"
echo "  Log: $LOG_FILE"
echo "=========================================="
