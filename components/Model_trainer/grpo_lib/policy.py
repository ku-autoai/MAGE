from typing import Any, Dict, Tuple

import torch
import torch.nn as nn


class ObsToLogitsBackbone(nn.Module):
    """Policy backbone adapter with an obs -> logits contract."""

    def __init__(self, base_model):
        super().__init__()
        self.base_model = base_model

    def _unpack_obs(self, obs: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        return {
            "input_ids": obs["input_ids"],
            "attention_mask": obs["attention_mask"],
            "pixel_values": obs["pixel_values"],
            "image_grid_thw": obs["image_grid_thw"],
        }

    def forward_with_outputs(self, obs: Dict[str, torch.Tensor], **kwargs):
        model_inputs = self._unpack_obs(obs)
        return self.base_model(
            **model_inputs,
            return_dict=True,
            **kwargs,
        )

    def forward(self, obs: Dict[str, torch.Tensor], **kwargs):
        outputs = self.forward_with_outputs(obs, **kwargs)
        return outputs.logits


class PolicyModel(nn.Module):
    """Wrapper owning the obs->logits backbone and log-prob helpers."""

    def __init__(self, base_model):
        super().__init__()
        self.backbone = ObsToLogitsBackbone(base_model)
        self.base_model = base_model

    def forward_logits(self, obs: Dict[str, torch.Tensor], **kwargs):
        return self.backbone(obs, **kwargs)

    def forward(self, obs: Dict[str, torch.Tensor], **kwargs):
        return self.forward_logits(obs, **kwargs)

    def forward_log_probs(self, obs: Dict[str, torch.Tensor]) -> Tuple[torch.Tensor, Any]:
        outputs = self.backbone.forward_with_outputs(
            obs,
            output_hidden_states=False,
        )
    
        logits = outputs.logits[:, :-1, :]
        labels = obs["input_ids"][:, 1:]
    
        log_probs = logits.log_softmax(dim=-1)
        per_token_log_probs = torch.gather(
            log_probs,
            dim=-1,
            index=labels.unsqueeze(-1)
        ).squeeze(-1)

        return per_token_log_probs
