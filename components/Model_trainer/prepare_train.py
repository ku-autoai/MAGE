#!/usr/bin/env python3
"""Reorganize collected trajectories into GRPO task groups, without name parsing.

python prepare_train.py /path/to/application --dry-run
python prepare_train.py /path/to/application

Recursively discover JSON objects containing a `steps` list. Group episodes by
their exact `real_input` text (falling back to `project`), never by folder names.
Copy each episode folder into a sibling <input-name>_train/task_<hash>/ folder
and create info.json using the schema from dataset/tool/util.py. Input files
are not modified. Output must not already exist. Standard library only.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover(source):
    groups = {}
    for current, dirs, files in os.walk(source, followlinks=False):
        dirs.sort()
        candidates = []
        for filename in sorted(files):
            if not filename.lower().endswith(".json"):
                continue
            path = Path(current) / filename
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"Cannot read JSON {path}: {exc}") from exc
            if isinstance(data, dict) and isinstance(data.get("steps"), list):
                candidates.append((path, data))
        if not candidates:
            continue
        if len(candidates) != 1:
            raise ValueError(f"Multiple trajectory JSON files in {current}")
        path, data = candidates[0]
        task = data.get("real_input") or data.get("project")
        if not isinstance(task, str) or not task.strip():
            raise ValueError(f"Missing real_input/project task text: {path}")
        score = data.get("score", -1)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError(f"Invalid numeric score: {path}")
        success = 1 if data.get("final_result", False) else 0
        record = dict(sampling=0, score=score, success=success,
                      step_num=len(data["steps"]), reward=[score, success])
        groups.setdefault(task, []).append((path, record))
        # An episode folder is copied whole, including any nested assets.
        dirs[:] = []
    if not groups:
        raise ValueError("No trajectory JSON objects with a steps list found")
    return groups


def make_info(group_id, samples):
    scores = [r["score"] for r in samples.values()]
    successes = [r["success"] for r in samples.values()]
    steps = [r["step_num"] for r in samples.values() if r["success"]]
    avg_score = sum(scores) / len(scores)
    avg_success = sum(successes) / len(successes)
    return dict(
        id=group_id, avg_score=avg_score,
        std_score=math.sqrt(sum((x - avg_score) ** 2 for x in scores) / len(scores)),
        avg_success=avg_success,
        std_success=math.sqrt(sum((x - avg_success) ** 2 for x in successes) / len(successes)),
        trajectory_num=len(samples), min_step_num=min(steps) if steps else None,
        sample_number=samples, reward_list=[r["reward"] for r in samples.values()],
    )


def prepare(source, dry_run=False):
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"Input directory does not exist: {source}")
    output = source.with_name(source.name + "_train")
    staging = output.with_name(output.name + ".partial")
    if output.exists() or staging.exists():
        raise ValueError(f"Output or partial output already exists: {output}, {staging}")
    groups = discover(source)
    plans = []
    for task, episodes in sorted(groups.items()):
        group_id = "task_" + digest(task)
        names = set()
        planned = []
        for path, record in episodes:
            name = path.parent.name
            if name in names:
                name += "__" + digest(str(path.relative_to(source)))
            if name in names:
                raise ValueError(f"Duplicate output name: {path}")
            names.add(name)
            # The loader opens <episode-folder>/<episode-folder>.json.
            expected = path.parent / (name + ".json")
            if expected != path and expected.exists():
                raise ValueError(f"Cannot rename trajectory JSON without overwriting {expected}")
            planned.append((path, record, name))
        plans.append((group_id, planned))
    total = sum(len(episodes) for episodes in groups.values())
    print(f"Input: {source}\nOutput: {output}")
    print(f"{total} episodes -> {len(groups)} task groups", flush=True)
    print("Grouping: exact real_input text, falling back to project; all input subfolders combined.")
    if dry_run:
        print("Dry run complete: metadata validated, no files copied.")
        return output
    staging.mkdir()
    for index, (group_id, episodes) in enumerate(plans, 1):
        target = staging / group_id
        target.mkdir()
        samples = {}
        for path, record, name in episodes:
            destination = target / name
            shutil.copytree(path.parent, destination)
            copied_json = destination / path.name
            expected_json = destination / (name + ".json")
            if copied_json != expected_json:
                copied_json.rename(expected_json)
            samples[name] = record
        (target / "info.json").write_text(
            json.dumps(make_info(group_id, samples), ensure_ascii=False, indent=4,
                       allow_nan=False) + "\n", encoding="utf-8")
        print(f"[{index}/{len(plans)}] {group_id}: {len(samples)} episodes", flush=True)
    if output.exists():
        raise ValueError(f"Output appeared while copying: {output}")
    staging.rename(output)
    print(f"Done. Set DATA_ROOT={output}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        prepare(args.input_dir, args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Original files are unchanged. Any interrupted copy is retained in "
              "the sibling *_train.partial directory.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
