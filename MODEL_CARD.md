# Model Card

This repository contains code for MAGE-style GUI-agent training and evaluation.
The checkpoint bundle contains task-specific PEFT LoRA adapters, not full
base-model weights.

## Model Overview

| Adapter family | Required base model | Applications |
| --- | --- | --- |
| UI-TARS-1.5 | `ByteDance-Seed/UI-TARS-1.5-7B` | Calc, Impress, Writer, GIMP, VS Code, Slack |
| EvoCUA | `meituan/EvoCUA-8B-20260105` | Calc, Impress, Writer, GIMP, VS Code, Slack |

Use the corresponding base model with each adapter. See
[checkpoint downloads](docs/ARTIFACTS.md#checkpoint-downloads)
for the release link, and
[bundle contents](docs/ARTIFACTS.md#lora-adapter-layout) for the directory layout.

## Intended Use

- Research on GUI agents, desktop automation, and training from user manuals.
- Running the [evaluation examples](docs/REPRODUCTION.md#6-run-evaluation).

## Out-of-Scope Use

- Autonomous operation on accounts, systems, or data without user permission.
- Security-sensitive desktop automation without additional review.

## Training Data

The training pipeline generates tasks/procedures from user manuals and collects
GUI trajectories through the episode-generation code under `components/`. The
released generated trajectory dataset is hosted outside this Git repository:

- [Download training trajectories (anonymous)](https://anonymous-hf.com/a/he3p2p7rtgw3/)
- The trajectory bundle contains EvoCUA and UI-TARS episodes for Calc,
  Impress, Writer, GIMP, and VS Code, packaged as ZIP archives.
- Use [`prepare_train.py`](components/Model_trainer/prepare_train.py) to copy
  collected episodes into the training input format. See
  [preparation instructions](docs/ARTIFACTS.md#prepare-training-groups) before
  configuring the training data path.

## Evaluation

Use the fixed base evaluation assets under:

- `osworld/evaluation_examples/test_all.json`
- `osworld/evaluation_examples/`

Use the retrieval-augmented evaluation assets under:

- `components/rap/OSWorld/Plan/libreoffice_plan/test_all.json`
- `components/rap/OSWorld/Plan/libreoffice_plan/`

Run the [domain evaluation commands](docs/REPRODUCTION.md#6-run-evaluation)
with `LORA_PATH` pointing to the released adapter checkpoint.

## Limitations

- GUI-agent results can vary with OS image, display resolution, package version,
  and remote-service state.
- The public repository does not include large generated trajectories or model
  checkpoints by default.
- API-backed generation/evaluation requires users to provide their own API keys.

## License

Code in this release root is provided under the MIT License unless a subdirectory
states a different license. Third-party assets retain their original licenses.
