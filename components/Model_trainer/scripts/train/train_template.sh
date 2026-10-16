#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

CONFIG_PATH="${1:?usage: $0 <config_path>}"

python -m Model_trainer.tools.train.run_grpo_from_config \
  --config "${CONFIG_PATH}"

# Example:
# (from components/) bash Model_trainer/scripts/train/train_template.sh Model_trainer/config/train/Cycle_1_writer.json
