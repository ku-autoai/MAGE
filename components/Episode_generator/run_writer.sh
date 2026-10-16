#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
PORT="${PORT:-8888}"
START_TASK_IDX="${START_TASK_IDX:-0}"
END_TASK_IDX="${END_TASK_IDX:-}"
TRAJECTORY_NUM="${TRAJECTORY_NUM:-1}"
MOD="${MOD:-val}"
BASE_DIR="${BASE_DIR:-./test/writer_val/default_run}"
LORA_PATH="${LORA_PATH:-}"
LORA_EPOCHS="${LORA_EPOCHS:-1}"
MAX_STEP="${MAX_STEP:-50}"
WITH_STEP="${WITH_STEP:-1}"
RAG="${RAG:-0}"
MARK_COORDS="${MARK_COORDS:-1}"

cmd=(
  python note_server.py
  --port "$PORT"
  --start_task_idx "$START_TASK_IDX"
  --trajectory_num "$TRAJECTORY_NUM"
  --mod "$MOD"
  --base_dir "$BASE_DIR"
  --program writer
  --max_step "$MAX_STEP"
  --lora_epochs "$LORA_EPOCHS"
)

if [[ "$MARK_COORDS" == "1" ]]; then
  cmd+=(--mark-coords)
fi

if [[ "$WITH_STEP" == "1" ]]; then
  cmd+=(--with_step)
fi

if [[ "$RAG" == "1" ]]; then
  cmd+=(--rag)
fi

if [[ -n "$LORA_PATH" ]]; then
  cmd+=(--lora_path "$LORA_PATH")
fi

if [[ -n "$END_TASK_IDX" ]]; then
  cmd+=(--end_task_idx "$END_TASK_IDX")
fi

CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES" "${cmd[@]}"
