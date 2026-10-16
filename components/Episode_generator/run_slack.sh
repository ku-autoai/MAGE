#!/usr/bin/env bash
set -euo pipefail

# mode: "train" or "val"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
PORT="${PORT:-3333}"
START_TASK_IDX="${START_TASK_IDX:-0}"
END_TASK_IDX="${END_TASK_IDX:-}"
TRAJECTORY_NUM="${TRAJECTORY_NUM:-1}"
MOD="${MOD:-val}"
BASE_DIR="${BASE_DIR:-./test/slack_val/default_run}"
LORA_PATH="${LORA_PATH:-}"
LORA_EPOCHS="${LORA_EPOCHS:-1}"
MAX_STEP="${MAX_STEP:-50}"
WITH_STEP="${WITH_STEP:-0}"
RAG="${RAG:-1}"
MARK_COORDS="${MARK_COORDS:-1}"

cmd=(
  python note_server.py
  --start_task_idx "$START_TASK_IDX"
  --trajectory_num "$TRAJECTORY_NUM"
  --port "$PORT"
  --mod "$MOD"
  --base_dir "$BASE_DIR"
  --program slack
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
