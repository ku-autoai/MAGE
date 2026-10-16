# Release Artifacts

This page describes the external model and trajectory bundles. For model
background and intended use, see the [model card](../MODEL_CARD.md).

## Checkpoint Downloads

- [Download LoRA bundle](https://anonymous-hf.com/a/1kv7rcpncczd/)

Download and extract the bundle, then use the application directory described
in [LoRA adapter layout](#lora-adapter-layout).

## Trajectory Dataset

- [Download training trajectories (anonymous)](https://anonymous-hf.com/a/he3p2p7rtgw3/)

The release bundle contains 49 ZIP archives (approximately 90.4 GB) of
generated training trajectories. Download the archives from the dataset page
and extract them into the same directory to preserve the model/application
hierarchy:

```bash
mkdir -p /path/to/trajectories
for archive in /path/to/downloaded-zips/*.zip; do
  unzip -q "$archive" -d /path/to/trajectories
done
```

## Trajectory Dataset Layout

```text
EvoCUA/
  1_libreoffice_calc/
  2_libreoffice_impress/
  3_libreoffice_writer/
  4_gimp/
  5_vscode/
UI-TARS/
  1_libreoffice_calc/
  2_libreoffice_impress/
  3_libreoffice_writer/
  4_gimp/
  5_vscode/
```

Each application contains cycle directories with individual episode folders,
including screenshots and a trajectory JSON. For example:

```text
EvoCUA/1_libreoffice_calc/cycle_0_1/<episode-id>/
  0.png
  1.png
  <episode-id>.json
```

These are collected episodes. The GRPO loader expects a prepared task-group
layout with an `info.json` containing `sample_number` entries for each group.
Use the preparation script below to create that layout before setting
`DATA_ROOT` or the config `data_root`.

## Prepare Training Groups

From the repository root, run
[`prepare_train.py`](../components/Model_trainer/prepare_train.py) on one
extracted model/application directory. The script uses only Python's standard
library:

```bash
python components/Model_trainer/prepare_train.py /path/to/trajectories/EvoCUA/1_libreoffice_calc --dry-run
python components/Model_trainer/prepare_train.py /path/to/trajectories/EvoCUA/1_libreoffice_calc
```

The first command validates the trajectory metadata and reports episode/group
counts without copying. The second recursively collects episodes from all
subdirectories and copies them to a sibling directory with `_train` appended:

```text
EvoCUA/1_libreoffice_calc_train/
  task_<sha256-of-task-text>/
    info.json
    <episode-id>/
      <episode-id>.json
      0.png
      ...
```

- Grouping uses exact `real_input` text, falling back to `project` when
  `real_input` is empty or absent. Whitespace and wording differences create
  separate groups. Folder names and cycle numbers are not parsed; matching
  tasks across all input subfolders are combined.
- For round-based training, supply only the episodes available up to the
  intended round. The script does not select rounds or generate new rollouts.
  Preparing the entire bundle creates a combined dataset, not the sequence of
  per-round datasets described in the paper.
- Each `info.json` contains `sample_number`, scores, success flags, step
  counts, rewards, and group statistics. Source files remain unchanged.
- Episode folder names are preserved unless a name collides within a group;
  collisions receive a source-path hash suffix. The copied trajectory JSON is
  named to match its destination episode folder.
- Existing output or `<input-name>_train.partial` directories are not
  overwritten. An interrupted copy remains in `.partial`; inspect and move or
  remove it before retrying. This script does not resume partial copies.

Set `DATA_ROOT` to the generated application directory, which directly contains
the task groups:

```bash
export DATA_ROOT=/path/to/trajectories/EvoCUA/1_libreoffice_calc_train
```

Use the matching model/application for training. See the
[Writer training example](REPRODUCTION.md#5-run-training) for config overrides.
The preparation script's `project` fallback is for grouping; the current
training loader still expects `real_input` in trajectory JSONs.

## LoRA Adapter Layout

The checkpoint bundle is organized by base model, then application:

```text
EvoCUA/
  1_libreoffice_calc/
  2_libreoffice_impress/
  3_libreoffice_writer/
  4_gimp/
  5_vscode/
  6_slack/
UI-TARS-1.5/
  1_libreoffice_calc/
  2_libreoffice_impress/
  3_libreoffice_writer/
  4_gimp/
  5_vscode/
  6_slack/
```
