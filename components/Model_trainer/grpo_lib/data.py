import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset
import random

try:
    from ..model.uitars import create_input_uitars
except ImportError:
    from model.uitars import create_input_uitars


@dataclass
class TrajectoryRecord:
    instance_id: str
    sampled_path: str
    traj_info: Dict[str, Any]
    reward: float
    group_avg: float
    group_std: float


@dataclass
class CachedBatch:
    prompt_ids: torch.Tensor
    prompt_mask: torch.Tensor
    completion_ids: torch.Tensor
    completion_mask: torch.Tensor
    pixel_values: Optional[torch.Tensor]
    image_grid_thw: Optional[torch.Tensor]
    prompt_length: int

    @classmethod
    def from_inputs(cls, inputs: Dict[str, Any]) -> "CachedBatch":
        prompt_length = inputs["prompt_length"]
        if isinstance(prompt_length, torch.Tensor):
            prompt_length = int(prompt_length.item())
        else:
            prompt_length = int(prompt_length)
        return cls(
            prompt_ids=inputs["prompt_ids"],
            prompt_mask=inputs["prompt_mask"],
            completion_ids=inputs["completion_ids"],
            completion_mask=inputs["completion_mask"],
            pixel_values=inputs.get("pixel_values"),
            image_grid_thw=inputs.get("image_grid_thw"),
            prompt_length=prompt_length,
        )

    def to_obs(self) -> Dict[str, torch.Tensor]:
        return {
            "input_ids": torch.cat([self.prompt_ids, self.completion_ids], dim=1),
            "attention_mask": torch.cat([self.prompt_mask, self.completion_mask], dim=1),
            "pixel_values": self.pixel_values,
            "image_grid_thw": self.image_grid_thw,
        }

    def slice_completion_log_probs(self, per_token_log_probs: torch.Tensor) -> torch.Tensor:
        return per_token_log_probs[:, self.prompt_length - 1 :]

    def completion_token_mask(self) -> torch.Tensor:
        return self.completion_mask



def exp_step_penalty(step_len: int, min_step: int, gamma: float = 1.0) -> float:
    x = step_len - min_step
    if x < 0:
        return 1.0
    return float(np.exp(-gamma * x))

def step_reward_minmaxnorm(step_len: int, min_step: int, max_step: int) -> float:
    if max_step < min_step:
        raise ValueError("max_step must be greater than min_step")
    if step_len < min_step:
        raise  ValueError("max_step must be greater than min_step")
    if step_len > max_step:
        raise  ValueError("max_step must be greater than min_step")

    if max_step == min_step:
        return 0
    else:
        return float((max_step - step_len) / (max_step - min_step))

def compute_trajectory_reward(element: Dict[str, Any], info: Dict[str, Any], gamma = 0.1, max_step: float = 50) -> float:
    def _safe_int(value: Any, default: int) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    success = _safe_int(element.get("success", 0), 0)
    step_len = _safe_int(element.get("step_num", 0), 0)
    min_step = _safe_int(info.get("min_step_num"), step_len)
    if success == 1:
        return float(success + step_reward_minmaxnorm(step_len, min_step, max_step) * gamma)
    return float(success)


def judge_collate_fn(batch: List[Dict[str, Any]]) -> Dict[str, Any]:
    collated: Dict[str, Any] = {}
    tensor_keys = {"final_result", "score", "reward", "group_mean_reward", "group_std_reward"}
    for key in batch[0]:
        values = [item[key] for item in batch]
        if key in tensor_keys:
            collated[key] = torch.tensor(values, dtype=torch.float32)
        else:
            collated[key] = values
    return collated


def build_records(
    info: Dict[str, Any],
    candidate_dirs: List[str],
) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    records = []
    for dirname in candidate_dirs:
        element = info["sample_number"][dirname]
        records.append(
            {
                "name": dirname,
                "reward": compute_trajectory_reward(element, info),
            }
        )
    return records


def build_trajectories(data_root: str, uniform_sampling) -> List[TrajectoryRecord]:
    trajectoryRecords: List[TrajectoryRecord] = []
    i= 0
    for folder_name in sorted(os.listdir(data_root)):
        task_record : List[TrajectoryRecord] = []

        folder_path = os.path.join(data_root, folder_name)
        if not os.path.isdir(folder_path):
            continue
        info_json = os.path.join(folder_path, "info.json")
        if not os.path.isfile(info_json):
            continue
        with open(info_json, "r") as f:
            traj_info = json.load(f)
        subdirs = [
            d
            for d in os.listdir(folder_path)
            if os.path.isdir(os.path.join(folder_path, d)) and d in traj_info.get("sample_number", {})
        ]
        records = build_records(traj_info, subdirs)

        group_rewards = np.array([rec["reward"] for rec in records], dtype=np.float32)
        group_avg = float(group_rewards.mean())
        group_std = float(group_rewards.std())

        if group_std < 1e-6:
            group_std = 1e-6
            continue

        for rec in records:
            sampled_path = os.path.join(folder_path, rec["name"])
            if not os.path.isdir(sampled_path):
                continue
            task_record.append(
                TrajectoryRecord(
                    instance_id=folder_name,
                    sampled_path=sampled_path,
                    traj_info=traj_info,
                    reward=float(rec["reward"]),
                    group_avg=group_avg,
                    group_std=group_std,
                )
            )
        
        
        if uniform_sampling:
            trajectoryRecords.append(random.choice(task_record))
        else:
            trajectoryRecords.extend(task_record)
    print(f"Total trajectories loaded: {len(trajectoryRecords)}")
    return trajectoryRecords


class GRPODataset(Dataset):
    def __init__(
        self,
        sampled_data: List[TrajectoryRecord],
        include_failed_trajectories: bool,
        history_n: int,
        preprocessed_records_path: Optional[str] = None,
        program_name: Optional[str] = "Libre Calc",
    ):
        self.program_name = program_name
        self.include_failed_trajectories = include_failed_trajectories
        self.history_n = history_n
        self.preprocessed_records_path = preprocessed_records_path
        if preprocessed_records_path:
            self.data_list = self._load_preprocessed_data(sampled_data, preprocessed_records_path)
        else:
            self.data_list = self._build_data(sampled_data)
        print(f"[INFO] train samples: {len(self.data_list)}")

    def _build_data(self, trajectoryRecords: List[TrajectoryRecord]) -> List[Dict[str, Any]]:
        train_data: List[Dict[str, Any]] = []

        # calc_train_path = "/path/to/libreoffice/calc_train.json"
        # with open(calc_train_path, "r", encoding="utf-8") as f:
        #     calc_train_data = json.load(f)

        # task_map = {}
        # for task_set in calc_train_data:
        #     main_task = f"In {self.program_name}, " + task_set.get("main_task", "")
        #     main_inst = main_task

        #     if task_set.get("relevant_procedure"):
        #         main_rag = main_inst + "\n\n" + task_set.get("relevant_procedure")
        #     else:
        #         main_rag = main_inst

        #     task_map[main_task] = main_rag

        for data in trajectoryRecords:
            json_path = None
            for file_name in os.listdir(data.sampled_path):
                if file_name.endswith(".json"):
                    json_path = os.path.join(data.sampled_path, file_name)
                    break
            if json_path is None or not os.path.isfile(json_path):
                continue

            with open(json_path, "r") as f:
                project = json.load(f)

            final_result = bool(project.get("final_result", False))
            # if (not self.include_failed_trajectories) and (not final_result):
            #     continue

            task = project["real_input"]
            # task = project["project"]
            # task_text = task_map.get(task, task)
            steps = project["steps"]
            score = project.get("score", 0)
            images: List[str] = []
            responses: List[str] = []
            end_reward = 1 if final_result else -1

            for step in steps:
                images.append(os.path.join(data.sampled_path, f"{step['id']}.png"))
                if len(images) > self.history_n:
                    images = images[-self.history_n:].copy()
                responses.append(step["model_output"])
                train_data.append(
                    {
                        "instance_id": data.instance_id,
                        "trajectory_id": data.sampled_path,
                        "task": task,
                        "image": images.copy(),
                        "step_num": len(steps),
                        "model_output": responses.copy(),
                        "final_result": end_reward,
                        "score": score,
                        "reward": data.reward,
                        "group_mean_reward": data.group_avg,
                        "group_std_reward": data.group_std,
                    }
                )

        return train_data

    def __len__(self):
        return len(self.data_list)

    def __getitem__(self, idx):
        return self.data_list[idx]


def compute_completion_log_probs_from_cached(model, cached: CachedBatch) -> Tuple[torch.Tensor, Any]:
    obs = cached.to_obs()
    target_model = model.module if hasattr(model, "module") else model
    per_token_log_probs = target_model.forward_log_probs(obs)
    per_token_log_probs = cached.slice_completion_log_probs(per_token_log_probs)
    return per_token_log_probs


def build_cached_batch_from_uitars(
    model,
    processor,
    image,
    task,
    device,
    target=None,
    max_seq_len=None,
    use_model_output=None,
    history_n = 5
):
    inputs, prompt_inputs = create_input_uitars(
        image,
        task,
        model,
        processor,
        device,
        target,
        use_model_output=use_model_output,
        history_n=history_n,
    )

    prompt_ids, completion_ids = inputs["prompt_ids"], inputs["completion_ids"]
    completion_mask = inputs["completion_mask"]

    if max_seq_len is not None:
        prompt_len = prompt_ids.size(1)
        max_comp = max_seq_len - prompt_len
        if max_comp <= 0:
            return None, None
        if completion_ids.size(1) > max_comp:
            inputs["completion_ids"] = completion_ids[:, :max_comp]
            inputs["completion_mask"] = completion_mask[:, :max_comp]

    return CachedBatch.from_inputs(inputs), prompt_inputs
