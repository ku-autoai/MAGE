import os
from pathlib import Path


_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]

MANUAL_PATH = os.environ.get(
    "RBP_MANUAL_PATH",
    str(
        (
            _REPO_ROOT
            / "components"
            / "Task_generator"
            / "Libreoffice"
            / "calc"
            / "section_filtered.json"
        ).resolve()
    ),
)

# Use the leaf directory name under evaluation_examples/examples, for example:
# libreoffice_calc, libreoffice_writer, chrome, gimp, vs_code, etc.
PROGRAM_NAME = os.environ.get("RBP_PROGRAM_NAME", "libreoffice_calc")

EVALUATION_EXAMPLES_ROOT = os.environ.get(
    "RBP_EVALUATION_EXAMPLES_ROOT",
    str((_REPO_ROOT / "osworld" / "evaluation_examples").resolve()),
)
OUTPUT_ROOT = os.environ.get(
    "RBP_OUTPUT_ROOT",
    str((_THIS_DIR / "outputs" / PROGRAM_NAME).resolve()),
)
FIRST_IMAGE_ROOT = os.environ.get(
    "RBP_FIRST_IMAGE_ROOT",
    str((_THIS_DIR / "first_screen_images").resolve()),
)

# Metadata files to copy with only the selected program's ids.
META_FILE_NAMES = [
    "test_all.json",
    "test_infeasible.json",
    "test_nogdrive.json",
    "test_small.json",
]

def _parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


def _parse_int_list_env(name: str, default: list[int]) -> list[int]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    parsed = [int(token.strip()) for token in raw.split(",") if token.strip()]
    return parsed or default


EMBED_MODEL_ID = os.environ.get("RBP_EMBED_MODEL_ID", "Qwen/Qwen3-Embedding-0.6B")
REWRITE_MODEL_ID = os.environ.get("RBP_REWRITE_MODEL_ID", "Qwen/Qwen3.6-27B")
EMBED_DEVICE_NUM = _parse_int_env("RBP_EMBED_DEVICE_NUM", 1)
GENERATION_DEVICE_NUMS = _parse_int_list_env("RBP_GENERATION_DEVICE_NUMS", [0, 1, 2, 3])
K = _parse_int_env("RBP_TOPK", 5)
GENERATION_BATCH_SIZE = _parse_int_env("RBP_GENERATION_BATCH_SIZE", 3)
MAX_NEW_TOKENS = _parse_int_env("RBP_MAX_NEW_TOKENS", 512)


SYSTEM_PROMPT = """
You are a procedure generator for a GUI agent operating on real screenshots.

You will be given:
1) A GUI task instruction
2) The first screenshot of the environment
3) Potentially relevant manual snippets retrieved for this task

Your goal is to generate a concise, step-by-step procedure that the agent can follow to complete the task.

Requirements:
- Focus only on actions that are directly useful for completing the task.
- Each step must correspond to a realistic GUI interaction (e.g., click, type, scroll, select).
- Ground each step in visible UI elements from the screenshot (e.g., button labels, menus, input fields, icons, relative positions).
- Prefer explicit interaction targets (e.g., “click the ‘Insert’ menu at the top toolbar” instead of vague descriptions).
- If multiple paths are possible, choose the most straightforward and reliable one.
- Avoid assumptions about hidden UI or unavailable elements.
- If the UI element is not clearly visible, describe how to locate it (e.g., via menu navigation or scrolling).
- Do not include unnecessary explanations, reasoning, or background knowledge.
- Do not repeat the task instruction.

Robustness:
- If an action might fail, suggest a simple alternative interaction (e.g., using a button instead of typing).
- Ensure the procedure is executable even with minor UI variations.

Output format:
- Output only one section titled "Relevant procedure".
- Use short, ordered, numbered steps.
- Each step should describe exactly one action.
"""
