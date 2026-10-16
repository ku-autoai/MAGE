import os
from typing import Optional, Tuple

import torch
import torch.distributed as dist

try:
    import deepspeed
    from deepspeed.ops.adam import DeepSpeedCPUAdam
    from deepspeed.runtime.zero import GatheredParameters
except ImportError:
    deepspeed = None
    DeepSpeedCPUAdam = None
    GatheredParameters = None


def is_dist_initialized() -> bool:
    return dist.is_available() and dist.is_initialized()


def get_global_rank() -> int:
    if is_dist_initialized():
        return dist.get_rank()
    return 0


def should_use_deepspeed(engine: str) -> bool:
    if engine == "python":
        return False
    if engine == "deepspeed":
        return True
    env_flag = os.getenv("USE_DEEPSPEED")
    if env_flag is not None:
        return env_flag == "1"
    return int(os.getenv("WORLD_SIZE", "1")) > 1


class SimpleEngine:
    def __init__(self, module, optimizer, device: torch.device):
        self.module = module
        self.optimizer = optimizer
        self.device = device
        self.module.to(device)

    def __call__(self, *args, **kwargs):
        return self.module(*args, **kwargs)

    def train(self):
        self.module.train()

    def backward(self, loss):
        loss.backward()

    def step(self):
        self.optimizer.step()

    def zero_grad(self):
        self.optimizer.zero_grad(set_to_none=True)

    def save_checkpoint(self, *args, **kwargs):
        return


def get_deepspeed_components() -> Tuple[Optional[object], Optional[object], Optional[object]]:
    return deepspeed, DeepSpeedCPUAdam, GatheredParameters
