# Slack retrieval-augmented plan generation

This pipeline creates a Qwen embedding for each Slack manual section, retrieves
the sections relevant to the full task context, and asks Qwen to generate a plan
for `main_task` only.

Each manual embedding concatenates:

- page title
- page URL
- section title
- every item in the section's `content`

No screenshot, image file, image URL, or image tensor is used. Plan generation
uses a text-only Qwen model interface.

Each retrieval query concatenates `setup_task`, every `setup_steps` item, and
`main_task`. The generation prompt treats setup as already completed, so its
output does not repeat setup actions.

## Run

From this directory:

```bash
python run_slack_plan.py --dry-run
python run_slack_plan.py
```

Useful smaller runs:

```bash
python run_slack_plan.py --max-tasks 1
python run_slack_plan.py --max-tasks 1 --retrieval-only
```

The default output is `outputs/Slack_val_plan_qwen.json`. It contains the
retrieval query, ranked sections and cosine scores, and `main_task_plan` for
each task.

Configuration can be changed through CLI options:

```bash
python run_slack_plan.py \
  --embed-device cuda:0 \
  --generation-device cuda:1 \
  --top-k 5 \
  --output outputs/Slack_val_plan_qwen.json
```

Equivalent environment variables are defined in `config.py`, including
`SLACK_PLAN_EMBED_MODEL_ID`, `SLACK_PLAN_GENERATION_MODEL_ID`,
`SLACK_PLAN_EMBED_DEVICE`, and `SLACK_PLAN_GENERATION_DEVICE`.
