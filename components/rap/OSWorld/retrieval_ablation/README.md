# Retrieval ablation

This runner reuses [the OSWorld planner](../run_local_model.py) with one of
three retrieval conditions:

- `top5`: similarity ranks 1–5.
- `top6_10`: similarity ranks 6–10.
- `random5`: five sections sampled using a stable seed derived from the task
  instruction and `--random-seed`.

Each condition returns up to five sections, depending on manual size. Defaults
use the Calc manual and tasks. All `RBP_*` overrides remain available.

Run from the repository root after installing the planning requirements:

```bash
export RBP_MANUAL_PATH="$PWD/components/Task_generator/Libreoffice/calc/section_filtered.json"
export RBP_EVALUATION_EXAMPLES_ROOT="$PWD/osworld/evaluation_examples"

python components/rap/OSWorld/retrieval_ablation/run_ablation.py --dry-run
RBP_EMBED_DEVICE_NUM=0 RBP_GENERATION_DEVICE_NUMS=0,1 \
python components/rap/OSWorld/retrieval_ablation/run_ablation.py \
  --ablation-mode top6_10 --max_examples 1
RBP_EMBED_DEVICE_NUM=0 RBP_GENERATION_DEVICE_NUMS=0,1 \
python components/rap/OSWorld/retrieval_ablation/run_ablation.py \
  --ablation-mode random5 --random-seed 42 --max_examples 1
```

Outputs are separated into `outputs/top5/`, `outputs/top6_10/`, and
`outputs/random5_seed<seed>/` under this directory. `RBP_OUTPUT_ROOT` overrides
these locations. Existing output requires `--overwrite`. Dry runs validate
local inputs without loading models, performing retrieval, or writing files.
