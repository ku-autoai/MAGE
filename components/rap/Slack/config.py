import os
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent

MANUAL_PATH = Path(
    os.environ.get(
        "SLACK_PLAN_MANUAL_PATH",
        THIS_DIR / "manual" / "Slack_eng.json",
    )
)
TASK_PATH = Path(
    os.environ.get(
        "SLACK_PLAN_TASK_PATH",
        THIS_DIR / "task" / "Slack_val_plan_v2.json",
    )
)
OUTPUT_PATH = Path(
    os.environ.get(
        "SLACK_PLAN_OUTPUT_PATH",
        THIS_DIR / "outputs" / "Slack_val_plan_qwen.json",
    )
)

EMBED_MODEL_ID = os.environ.get(
    "SLACK_PLAN_EMBED_MODEL_ID",
    "Qwen/Qwen3-Embedding-0.6B",
)
GENERATION_MODEL_ID = os.environ.get(
    "SLACK_PLAN_GENERATION_MODEL_ID",
    os.environ.get("RBP_REWRITE_MODEL_ID", "Qwen/Qwen3.6-27B"),
)
EMBED_DEVICE = os.environ.get("SLACK_PLAN_EMBED_DEVICE", "cuda:0")
GENERATION_DEVICE = os.environ.get("SLACK_PLAN_GENERATION_DEVICE", "cuda:0")
TOP_K = int(os.environ.get("SLACK_PLAN_TOP_K", "5"))
MAX_NEW_TOKENS = int(os.environ.get("SLACK_PLAN_MAX_NEW_TOKENS", "512"))


SYSTEM_PROMPT = """You generate executable plans for a GUI agent using Slack.

You receive:
1. Setup context describing actions that have already been completed
2. One main task that remains to be completed
3. Potentially relevant Slack manual snippets retrieved for the task

Your goal is to generate a concise, step-by-step procedure that the agent can follow to complete the main task.

Requirements:
- Generate a procedure for the main task only.
- Treat all setup actions as already completed.
- Do not repeat, reverse, or modify completed setup actions unless the main task explicitly requires it.
- Include only actions that are directly necessary to complete the main task.
- Each step must describe exactly one realistic GUI interaction, such as clicking, typing, selecting, or scrolling.
- Refer to Slack UI elements using explicit labels, such as button names, menus, fields, icons, channels, and conversations.
- Preserve exact values from the task, including names, channel names, message text, status text, emoji, dates, times, and URLs.
- Use retrieved manual snippets only when they are relevant and consistent with the task.
- Ignore irrelevant or conflicting retrieved information.
- If multiple methods are available, choose the simplest and most reliable method.
- Do not assume that hidden or unavailable UI elements are present.
- When an element may not be immediately visible, explain how to locate it through menu navigation or scrolling.
- Do not include explanations, reasoning, background information, or task summaries.
- Do not repeat the main task instruction.

Robustness:
- Ensure the procedure remains executable despite minor Slack UI variations.
- When necessary, mention a simple alternative way to locate or activate an element.

Output format:
- Output exactly one section titled "Relevant procedure".
- Use a short, ordered, numbered list.
- Describe exactly one GUI action in each step.
- Do not output any text before or after the section.
"""
