#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
RESULT_DIR="${RESULT_DIR:-./experiment_plan/calc/default_run}"
MAX_STEPS="${MAX_STEPS:-50}"
NUM_ENVS="${NUM_ENVS:-3}"
TEST_ALL_META_PATH="${TEST_ALL_META_PATH:-evaluation_examples/test_all.json}"
TEST_CONFIG_BASE_DIR="${TEST_CONFIG_BASE_DIR:-evaluation_examples}"
LORA_PATH="${LORA_PATH:-}"

cmd=(
  python scripts/python/run_multienv_uitars15_v1.py
  --result_dir "$RESULT_DIR"
  --max_steps "$MAX_STEPS"
  --num_envs "$NUM_ENVS"
  --domain libreoffice_calc
  --test_all_meta_path "$TEST_ALL_META_PATH"
  --test_config_base_dir "$TEST_CONFIG_BASE_DIR"
)

if [[ -n "$LORA_PATH" ]]; then
  cmd+=(--lora_path "$LORA_PATH")
fi

CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES" "${cmd[@]}"
