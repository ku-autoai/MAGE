"""Calc configuration for retrieval ablation plan generation.

The defaults mirror OSWorld/config.py, while all values can still
be overridden with the existing RBP_* environment variables.
"""

import importlib.util
import os
from pathlib import Path


_THIS_DIR = Path(__file__).resolve().parent
_BASE_CONFIG_PATH = _THIS_DIR.parent / "config.py"
_SPEC = importlib.util.spec_from_file_location("_retrieval_base_config", _BASE_CONFIG_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load base configuration: {_BASE_CONFIG_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)

# Re-export the settings expected by OSWorld/run_local_model.py.
EMBED_MODEL_ID = _BASE.EMBED_MODEL_ID
EVALUATION_EXAMPLES_ROOT = _BASE.EVALUATION_EXAMPLES_ROOT
FIRST_IMAGE_ROOT = _BASE.FIRST_IMAGE_ROOT
GENERATION_BATCH_SIZE = _BASE.GENERATION_BATCH_SIZE
K = 5
MANUAL_PATH = _BASE.MANUAL_PATH
MAX_NEW_TOKENS = _BASE.MAX_NEW_TOKENS
META_FILE_NAMES = _BASE.META_FILE_NAMES
PROGRAM_NAME = _BASE.PROGRAM_NAME
REWRITE_MODEL_ID = _BASE.REWRITE_MODEL_ID
SYSTEM_PROMPT = _BASE.SYSTEM_PROMPT

# GPU settings. Edit the defaults below directly, or override them at runtime:
#   RBP_EMBED_DEVICE_NUM=1
#   RBP_GENERATION_DEVICE_NUMS=0,1,2,3
EMBED_DEVICE_NUM = int(
    os.environ.get("RBP_EMBED_DEVICE_NUM", "0")
)
GENERATION_DEVICE_NUMS = [
    int(device.strip())
    for device in os.environ.get(
        "RBP_GENERATION_DEVICE_NUMS",
        "0,1,2,3",
    ).split(",")
    if device.strip()
]

# run_ablation.py replaces this default with a mode-specific directory unless
# the caller explicitly supplies RBP_OUTPUT_ROOT.
OUTPUT_ROOT = os.environ.get(
    "RBP_OUTPUT_ROOT",
    str((_THIS_DIR / "outputs" / "top5").resolve()),
)
