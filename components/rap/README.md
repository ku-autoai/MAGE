# Retrieval-Augmented Planning

Retrieve relevant manual sections and generate procedures for GUI tasks.
The pipelines are separated into `OSWorld/` (task instructions plus optional
initial screenshots) and `Slack/` (text-only setup context and main tasks).

## Install

From the repository root, use Python 3.10 or newer:

```bash
python -m pip install -r components/rap/requirements.txt
```

Generation loads local Hugging Face models. The OSWorld runner loads one
model across the GPUs listed in `RBP_GENERATION_DEVICE_NUMS`, reserves 2 GiB
per GPU, and rejects CPU/disk offloading. Set GPU IDs for your own machine;
the defaults assume multiple GPUs. The installed Transformers version must
support the selected model. Model weights may be downloaded on first use.

## OSWorld

By default, the runner uses the bundled Calc manual
(`components/Task_generator/Libreoffice/calc/section_filtered.json`) and
`osworld/evaluation_examples/`.

Check the bundled Calc manual and task inputs without loading models:

```bash
python components/rap/OSWorld/run_local_model.py --dry-run
```

Generate a small set with GPUs 0 and 1, from the repository root:

```bash
RBP_EMBED_DEVICE_NUM=0 RBP_GENERATION_DEVICE_NUMS=0,1 \
python components/rap/OSWorld/run_local_model.py --max_examples 2
```

The input paths above use the repository's Calc manual and
`osworld/evaluation_examples/`. Output defaults to
`components/rap/OSWorld/outputs/libreoffice_calc/`. Override `RBP_PROGRAM_NAME`,
`RBP_MANUAL_PATH`, `RBP_EVALUATION_EXAMPLES_ROOT`, `RBP_OUTPUT_ROOT`, and
`RBP_FIRST_IMAGE_ROOT` through environment variables. These Python scripts
read exported environment variables; they do not automatically load `.env`.
See [OSWorld configuration](OSWorld/config.py) for model, retrieval, and GPU settings.
Relative override paths are resolved from the working directory.

For another application, set both its program name (for example `gimp` or
`vs_code`) and its matching manual JSON. Manuals must contain a list of objects
with `text` and optional `start_page`/`end_page` fields. Manuals for GIMP and
VS Code are not included here.

Screenshots are optional and are not bundled. Place them under
`OSWorld/first_screen_images/<program>/<task_id>/step_1.png`, or provide a
screenshot root with the same domain/task layout. Tasks without an image use
text-only inputs. `--smoke_test_image` checks actual image tensors but loads
a model processor and may download its files; `--dry-run` does neither.

An existing output directory requires `--overwrite`; otherwise choose a new
`RBP_OUTPUT_ROOT`. Output may not contain input data or the runner's source.
Each run writes one application's task JSONs and metadata. Use separate
outputs for each application and merge metadata explicitly when combining them.
Run evaluation from `osworld/` so generated support-file paths resolve correctly.

## Slack

```bash
python components/rap/Slack/run_slack_plan.py --dry-run
python components/rap/Slack/run_slack_plan.py --max-tasks 1 \
  --output components/rap/Slack/outputs/smoke.json
```

See [the Slack guide](Slack/README.md) for retrieval, model settings, and output
format.
Use your own test data for private workspaces and review generated text before
publishing. Runtime outputs, screenshots, caches, and `.env` files are ignored.

## Checks without model inference

From the repository root:

```bash
python3.10 -m unittest discover -s components/rap/tests
```

The tests check configuration paths, retrieval selection, mocked GPU placement,
support-file relocation, output protection, and precomputed task references.
They do not validate model quality or run inference on a GPU.
