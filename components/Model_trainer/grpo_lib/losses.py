from typing import Tuple

import torch


def ppo_loss(
    old_per_token_log_probs: torch.Tensor,
    per_token_log_probs: torch.Tensor,
    advantages: torch.Tensor,
    epsilon: float = 0.2,
) -> Tuple[torch.Tensor, torch.Tensor]:
    ratio = torch.exp(per_token_log_probs - old_per_token_log_probs)
    ratio_clipped = torch.clamp(ratio, 1 - epsilon, 1 + epsilon)
    loss1 = ratio * advantages.unsqueeze(1)
    loss2 = ratio_clipped * advantages.unsqueeze(1)
    per_token_loss = -torch.min(loss1, loss2)
    return per_token_loss, ratio
