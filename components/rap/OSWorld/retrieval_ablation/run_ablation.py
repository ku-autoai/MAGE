"""Run plan-generation retrieval ablations without modifying the base pipeline."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import random
import sys
from pathlib import Path

import config


THIS_DIR = Path(__file__).resolve().parent
BASE_RUNNER = THIS_DIR.parent / "run_local_model.py"
MODES = ("top5", "top6_10", "random5")
SECTION_COUNT = 5


def task_seed(seed: int, task: str) -> int:
    """Derive a stable per-task seed (unlike Python's process-randomized hash)."""
    digest = hashlib.sha256(f"{seed}\0{task}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def select_sections(
    task: str,
    vectorstore,
    manual_sections_by_id: dict[int, dict],
    mode: str,
    seed: int,
) -> tuple[list[str], list[tuple[int | None, int | None]]]:
    if mode not in MODES:
        raise ValueError(f"Unknown ablation mode: {mode}")

    if mode == "random5":
        section_ids = sorted(manual_sections_by_id)
        rng = random.Random(task_seed(seed, task))
        selected_ids = rng.sample(section_ids, min(SECTION_COUNT, len(section_ids)))
        sections = [manual_sections_by_id[section_id] for section_id in selected_ids]
        return (
            [section["text_full"] for section in sections],
            [
                (section.get("start_page"), section.get("end_page"))
                for section in sections
            ],
        )

    rank_start = 0 if mode == "top5" else SECTION_COUNT
    docs = vectorstore.similarity_search(
        task,
        k=rank_start + SECTION_COUNT,
    )[rank_start : rank_start + SECTION_COUNT]
    return (
        [
            manual_sections_by_id[doc.metadata["section_id"]]["text_full"]
            for doc in docs
        ],
        [
            (doc.metadata.get("start_page"), doc.metadata.get("end_page"))
            for doc in docs
        ],
    )


def load_base_runner():
    # The base runner imports a module named "config"; make that import resolve
    # to this directory's ablation configuration.
    sys.modules["config"] = config
    spec = importlib.util.spec_from_file_location("_retrieval_base_runner", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load base runner: {BASE_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_ablation_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ablation-mode", choices=MODES, default="top5")
    parser.add_argument("--random-seed", type=int, default=0)
    return parser.parse_known_args()


def main() -> None:
    args, base_args = parse_ablation_args()
    base_runner = load_base_runner()

    def retrieve(task, vectorstore, manual_sections_by_id, _k):
        return select_sections(
            task,
            vectorstore,
            manual_sections_by_id,
            args.ablation_mode,
            args.random_seed,
        )

    base_runner.retrieve = retrieve
    base_runner.K = SECTION_COUNT

    if "RBP_OUTPUT_ROOT" not in os.environ:
        suffix = args.ablation_mode
        if args.ablation_mode == "random5":
            suffix = f"{suffix}_seed{args.random_seed}"
        base_runner.OUTPUT_ROOT = str((THIS_DIR / "outputs" / suffix).resolve())

    print(f"[ABLATION] mode={args.ablation_mode}")
    print(f"[ABLATION] sections_per_task={SECTION_COUNT}")
    if args.ablation_mode == "top6_10":
        print("[ABLATION] using similarity ranks 6-10 (1-based)")
    elif args.ablation_mode == "random5":
        print(f"[ABLATION] random_seed={args.random_seed} (stable per task)")
    print(f"[ABLATION] output_root={base_runner.OUTPUT_ROOT}")

    # Leave only the arguments understood by the original runner.
    sys.argv = [sys.argv[0], *base_args]
    base_runner.main()


if __name__ == "__main__":
    main()
