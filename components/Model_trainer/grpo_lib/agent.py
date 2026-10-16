import json
import os
import random
from typing import Any, Dict, Optional
from collections import defaultdict

import torch
import torch.distributed as dist
from peft import LoraConfig, TaskType, get_peft_model, get_peft_model_state_dict
from torch.utils.data import DataLoader, DistributedSampler
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm
import pandas as pd
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

from .data import (
    CachedBatch,
    GRPODataset,
    build_cached_batch_from_uitars,
    build_trajectories,
    compute_completion_log_probs_from_cached,
    judge_collate_fn,
)
from .losses import ppo_loss
from .policy import PolicyModel
from .runtime import (
    SimpleEngine,
    get_deepspeed_components,
    get_global_rank,
    is_dist_initialized,
    should_use_deepspeed,
)


class GRPOAgent:
    def __init__(self, args):
        self.args = args
        self.use_deepspeed = should_use_deepspeed(args.engine)
        self.rank = 0
        self.device = self._init_runtime()
        self.beta = args.beta
        self.processor = AutoProcessor.from_pretrained(args.model_path, max_pixels=4028160, min_pixels=3136)
        self.processor.pad_token_id = self.processor.tokenizer.pad_token_id
        self.processor.eos_token_id = self.processor.tokenizer.eos_token_id

        self.policy_model, self.lora_cfg = self._build_policy_model()
        self.policy_engine = self._build_policy_engine(self.policy_model)
        self.old_model = self._build_old_model(self.lora_cfg)

        self._print_trainable_params(self.policy_engine)
        self._set_safety_flags(self.policy_engine)

        log_dir = args.log_dir or os.path.join(args.output_dir, "tb_logs")
        self.writer = SummaryWriter(log_dir=log_dir) if self.rank == 0 else None
        self.eval_dataset = self._build_eval_dataset()

    def _init_runtime(self) -> torch.device:
        deepspeed, DeepSpeedCPUAdam, _ = get_deepspeed_components()
        if self.use_deepspeed:
            if deepspeed is None or DeepSpeedCPUAdam is None:
                raise ImportError("DeepSpeed is not installed but deepspeed engine was requested.")
            deepspeed.init_distributed()
            local_rank = int(os.getenv("LOCAL_RANK", "0"))
            device = torch.device(f"cuda:{local_rank}" if torch.cuda.is_available() else "cpu")
        else:
            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

        self.rank = get_global_rank()
        if self.rank == 0:
            mode = "deepspeed" if self.use_deepspeed else "python"
            print(f"[INFO] Engine mode: {mode}")
        return device

    def _build_policy_model(self):
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.args.model_path,
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
            low_cpu_mem_usage=True,
        )
        model.config.use_cache = False
        model.gradient_checkpointing_enable()

        if hasattr(model, "enable_input_require_grads"):
            model.enable_input_require_grads()

        lora_cfg = None
        if self.args.use_lora:
            lora_cfg = LoraConfig(
                r=self.args.lora_r,
                lora_alpha=self.args.lora_alpha,
                lora_dropout=self.args.lora_dropout,
                bias="none",
                task_type=TaskType.CAUSAL_LM,
                target_modules=[m.strip() for m in self.args.lora_target.split(",") if m.strip()],
            )
            model = get_peft_model(model, lora_cfg)
            self._freeze_vision_tower(model)

        return model, lora_cfg

    def _save_epoch(self, epoch: int):
        _, _, GatheredParameters = get_deepspeed_components()

        if self.use_deepspeed and is_dist_initialized():
            dist.barrier()

        save_dir = os.path.join(self.args.output_dir, "lora_adapter", f"{epoch}")
        

        peft_model = self.policy_engine.module.base_model
        adapter_state_dict = None

        if self.use_deepspeed and is_dist_initialized() and GatheredParameters is not None:
            with GatheredParameters(self.policy_engine.module.parameters(), modifier_rank=0):
                if self.rank == 0:
                    adapter_state_dict = {
                        key: value.detach().cpu()
                        for key, value in  peft_model.state_dict().items()
                    }
                    print(f"[rank{self.rank}] adapter keys:", len(adapter_state_dict) if adapter_state_dict is not None else None)
        else:
            if self.rank == 0:
                adapter_state_dict = {
                    key: value.detach().cpu()
                    for key, value in get_peft_model_state_dict(peft_model).items()
                }

        if self.use_deepspeed and is_dist_initialized():
            dist.barrier()

        if self.rank == 0:
            os.makedirs(save_dir, exist_ok=True)
            peft_model.save_pretrained(save_dir, state_dict=adapter_state_dict)
            self.processor.save_pretrained(save_dir)
            print(f"Saved LoRA adapter to {save_dir}")

        if self.use_deepspeed and is_dist_initialized():
            dist.barrier()
        
        if self.use_deepspeed:
            last_dir = os.path.join(self.args.output_dir, "latest")
            # All ranks must call this.
            ckpt_tag = f"epoch_{epoch}"
            self.policy_engine.save_checkpoint(
                save_dir=last_dir,
                tag=ckpt_tag,
                client_state={
                    "epoch": epoch,
                },
                save_latest=True,
            )
            if self.rank == 0:
                print(f"Saved DeepSpeed checkpoint to {last_dir} (tag={ckpt_tag})")

        print("Save Epoch End")

    def _resolve_deepspeed_resume(self):
        resume_path = getattr(self.args, "resume_path", None)
        if resume_path is None:
            return None

        raw_path = os.path.normpath(resume_path)
        epoch_dir = os.path.basename(raw_path)
        parent_dir = os.path.basename(os.path.dirname(raw_path))

        if parent_dir == "latest" and epoch_dir.startswith("epoch_"):
            load_dir = os.path.dirname(raw_path)
            tag = epoch_dir
            if os.path.isdir(load_dir):
                return load_dir, tag

        if self.rank == 0:
            print(f"[WARN] resume_path is not a DeepSpeed checkpoint path: {resume_path}")
        return None

    # def _resolve_lora_adapter_path(self):
    #     raw_path = os.path.normpath(self.args.lora_path)

    #     # Allow passing an adapter directory directly.
    #     adapter_config = os.path.join(raw_path, "adapter_config.json")
    #     adapter_weights = os.path.join(raw_path, "adapter_model.safetensors")
    #     if os.path.isfile(adapter_config) and os.path.isfile(adapter_weights):
    #         return raw_path

    #     # Backward-compatible behavior: pass the run root and resume epoch.
    #     legacy_path = os.path.join(raw_path, "lora_adapter", str(self.args.resume_epoch))
    #     if os.path.exists(legacy_path):
    #         return legacy_path

    #     # If a DeepSpeed checkpoint like ".../latest/epoch_2" is provided,
    #     # map it to the corresponding LoRA adapter directory ".../lora_adapter/2".
    #     epoch_dir = os.path.basename(raw_path)
    #     parent_dir = os.path.basename(os.path.dirname(raw_path))
    #     if parent_dir == "latest" and epoch_dir.startswith("epoch_"):
    #         epoch_idx = epoch_dir.split("epoch_", 1)[1]
    #         run_root = os.path.dirname(os.path.dirname(raw_path))
    #         mapped_path = os.path.join(run_root, "lora_adapter", epoch_idx)
    #         if os.path.exists(mapped_path):
    #             return mapped_path

    #     return legacy_path

    def _build_policy_engine(self, model):
        deepspeed, DeepSpeedCPUAdam, _ = get_deepspeed_components()
        policy_wrapper = PolicyModel(model)

        if self.use_deepspeed:
            with open(self.args.ds_config, "r") as f:
                ds_config = json.load(f)

            world_size = int(os.environ.get("WORLD_SIZE", "1"))
            micro = self.args.micro_batch_size_per_gpu
            gas = ds_config["gradient_accumulation_steps"]
            effective = micro * gas * world_size
            if ds_config.get("train_micro_batch_size_per_gpu") != micro and self.rank == 0:
                print(
                    "[WARN] Fixing train_micro_batch_size_per_gpu "
                    f"{ds_config.get('train_micro_batch_size_per_gpu')} -> {micro}"
                )
            ds_config["train_micro_batch_size_per_gpu"] = micro
            if ds_config["train_batch_size"] != effective and self.rank == 0:
                print(f"[WARN] Fixing train_batch_size {ds_config['train_batch_size']} -> {effective}")
            ds_config["train_batch_size"] = effective

            optimizer = DeepSpeedCPUAdam([p for p in model.parameters() if p.requires_grad], lr=self.args.lr)
            trainable_params = [p for p in model.parameters() if p.requires_grad]

            engine, _, _, _ = deepspeed.initialize(
                model=policy_wrapper,
                optimizer=optimizer,
                model_parameters=trainable_params,
                training_data=None,
                config=ds_config,
            )
            self._maybe_resume_engine(engine)
            return engine

        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=self.args.lr)
        return SimpleEngine(policy_wrapper, optimizer, self.device)

    def _maybe_resume_engine(self, engine):
        resume_spec = self._resolve_deepspeed_resume()
        if resume_spec is None:
            return

        load_dir, tag = resume_spec
        _, client_state = engine.load_checkpoint(
            load_dir=load_dir,
            tag=tag,
            load_module_strict=True,
            load_optimizer_states=True,
            load_lr_scheduler_states=True,
        )

        if self.rank == 0:
            print(
                f"[INFO] Resumed DeepSpeed checkpoint from {load_dir}/{tag} "
            )

    def _build_old_model(self, lora_cfg):
        old_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.args.model_path,
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        if self.args.use_lora and lora_cfg is not None:
            old_model = get_peft_model(old_model, lora_cfg)
            self._freeze_vision_tower(old_model)
        old_wrapper = PolicyModel(old_model).to(self.device)
        old_wrapper.eval()
        return old_wrapper

    def _freeze_vision_tower(self, model):
        visual = getattr(getattr(model, "model", model), "visual", None)
        if visual is None:
            if self.rank == 0:
                print("[WARN] vision tower not found; skip freezing")
            return
        for p in visual.parameters():
            p.requires_grad = False

    def _print_trainable_params(self, model_engine):
        if self.rank != 0:
            return
        print("############# Policy ################")
        try:
            raw_model = model_engine.module if hasattr(model_engine, "module") else model_engine
            peft_candidate = raw_model.base_model if hasattr(raw_model, "base_model") else raw_model
            if hasattr(peft_candidate, "print_trainable_parameters"):
                peft_candidate.print_trainable_parameters()
            else:
                trainable = sum(p.numel() for p in raw_model.parameters() if p.requires_grad)
                total = sum(p.numel() for p in raw_model.parameters())
                print(f"Trainable params: {trainable:,} || All params: {total:,} || Trainable%: {100*trainable/total:.4f}")
        except Exception as e:
            print("Could not print trainable parameters:", e)

    def _set_safety_flags(self, model_engine):
        base_model = model_engine.module.base_model
        base_model.config.attn_implementation = "sdpa"
        base_model.config.use_cache = False

    def _sync_old_model(self):
        _, _, GatheredParameters = get_deepspeed_components()
        source_model = self.policy_engine.module.base_model
        target_model = self.old_model.base_model

        trainable_keys = {
            name for name, param in source_model.named_parameters() if param.requires_grad
        }

        def extract_trainable_state_dict(state_dict):
            return {
                k: v.detach().cpu()
                for k, v in state_dict.items()
                if k in trainable_keys
            }

        if self.use_deepspeed and is_dist_initialized() and GatheredParameters is not None:
            with GatheredParameters(self.policy_engine.module.parameters(), modifier_rank=0):
                partial_state_dict = None
                if self.rank == 0:
                    partial_state_dict = extract_trainable_state_dict(source_model.state_dict())

            payload = [partial_state_dict]
            dist.broadcast_object_list(payload, src=0)
            target_model.load_state_dict(payload[0], strict=False)
            dist.barrier()
            return

        partial_state_dict = extract_trainable_state_dict(source_model.state_dict())
        target_model.load_state_dict(partial_state_dict, strict=False)
            

    def _should_skip_batch(self, cached: Optional[CachedBatch]) -> bool:
        local_skip = cached is None
        if self.use_deepspeed and is_dist_initialized():
            flag = torch.tensor(
                1 if local_skip else 0,
                device=self.device,
                dtype=torch.int32,
            )
            dist.all_reduce(flag, op=dist.ReduceOp.MAX)
            return bool(flag.item())
        return local_skip

    def _compute_reference_log_probs(self, cached: CachedBatch) -> torch.Tensor:
        base_model = self.policy_engine.module.base_model
        if hasattr(base_model, "disable_adapter"):
            with torch.no_grad():
                with base_model.disable_adapter():
                    reference_log_probs = compute_completion_log_probs_from_cached(self.policy_engine, cached)
            return reference_log_probs.detach()

        with torch.no_grad():
            reference_log_probs, _ = compute_completion_log_probs_from_cached(self.policy_engine, cached)
        return reference_log_probs.detach()

    def _build_epoch_dataloader(self):
        if self.use_deepspeed and is_dist_initialized():
            if self.rank == 0:
                sampled_data = build_trajectories(
                    self.args.data_root, self.args.uniform_sampling)
            else:
                sampled_data = None
            payload = [sampled_data]
            dist.broadcast_object_list(payload, src=0)
            sampled_data = payload[0]
        else:
            sampled_data = build_trajectories(
                self.args.data_root, self.args.uniform_sampling)

        dataset = GRPODataset(
            sampled_data,
            include_failed_trajectories=self.args.include_failed_trajectories,
            history_n=self.args.history_n,
            preprocessed_records_path=self.args.preprocessed_records_path,
        )

        if self.use_deepspeed and is_dist_initialized():
            sampler = DistributedSampler(dataset, shuffle=True)
            dataloader = DataLoader(
                dataset,
                batch_size=self.args.micro_batch_size_per_gpu,
                sampler=sampler,
                num_workers=self.args.num_workers,
                pin_memory=True,
                collate_fn=judge_collate_fn,
            )
        else:
            dataloader = DataLoader(
                dataset,
                batch_size=self.args.micro_batch_size_per_gpu,
                shuffle=True,
                num_workers=self.args.num_workers,
                pin_memory=True,
                collate_fn=judge_collate_fn,
            )

        if self.rank == 0:
            print("sampled_data len:", len(sampled_data))
        return dataloader  

    def _build_eval_dataset(self):
        if self.args.eval_subset_size <= 0:
            return None

        if self.use_deepspeed and is_dist_initialized():
            if self.rank == 0:
                sampled_data = build_trajectories(self.args.data_root, False)
            else:
                sampled_data = None
            payload = [sampled_data]
            dist.broadcast_object_list(payload, src=0)
            sampled_data = payload[0]
        else:
            sampled_data = build_trajectories(self.args.data_root, False)

        success_trajs = [traj for traj in sampled_data if traj.reward > 0]
        fail_trajs = [traj for traj in sampled_data if traj.reward <= 0]

        if not success_trajs and not fail_trajs:
            return None

        rng = random.Random(self.args.seed if self.args.seed is not None else 0)
        chosen = []
        if success_trajs:
            chosen.extend(rng.sample(success_trajs, min(self.args.eval_subset_size, len(success_trajs))))
        if fail_trajs:
            chosen.extend(rng.sample(fail_trajs, min(self.args.eval_subset_size, len(fail_trajs))))

        dataset = GRPODataset(
            chosen,
            include_failed_trajectories=True,
            history_n=self.args.history_n,
            preprocessed_records_path=self.args.preprocessed_records_path,
        )
        if self.rank == 0:
            print(
                "[INFO] Eval subset trajectories:"
                f" success={min(self.args.eval_subset_size, len(success_trajs))}"
                f" fail={min(self.args.eval_subset_size, len(fail_trajs))}"
                f" steps={len(dataset)}"
            )
        return dataset

    def _log_eval_subset(self, epoch: int):
        print(f"[rank{self.rank}] Before Eval epoch={epoch}", flush=True)
        if self.eval_dataset is None or len(self.eval_dataset) == 0:
            print(f"[rank{self.rank}] After Eval epoch={epoch} skipped", flush=True)
            return

        sampler = None
        if self.use_deepspeed and is_dist_initialized():
            sampler = DistributedSampler(self.eval_dataset, shuffle=False, drop_last=False)

        dataloader = DataLoader(
            self.eval_dataset,
            batch_size=self.args.micro_batch_size_per_gpu,
            shuffle=(sampler is None),
            sampler=sampler,
            num_workers=0,
            pin_memory=True,
            collate_fn=judge_collate_fn,
        )
        eval_pbar = tqdm(
            dataloader,
            disable=(self.rank != 0),
            desc=f"Eval {epoch}",
        )

        step_groups = {"success": [], "fail": []}
        traj_groups = {
            "success": defaultdict(list),
            "fail": defaultdict(list),
        }

        self.policy_engine.module.eval()
        with torch.inference_mode():
            for batch in eval_pbar:
                task = batch["task"]
                image = batch["image"]
                target = batch["model_output"]
                trajectory_ids = batch["trajectory_id"]
                rewards = batch["reward"]

                cached, _ = build_cached_batch_from_uitars(
                    self.policy_engine,
                    self.processor,
                    image,
                    task,
                    self.device,
                    target=target,
                    max_seq_len=self.args.max_seq_len,
                    history_n=self.args.history_n,
                )
                if cached is None:
                    continue

                log_probs = compute_completion_log_probs_from_cached(self.policy_engine, cached)
                completion_mask = cached.completion_token_mask()
                step_logps = (log_probs * completion_mask).sum(dim=1) / completion_mask.sum(dim=1).clamp_min(1)

                for traj_id, reward, step_logp in zip(trajectory_ids, rewards, step_logps.tolist()):
                    group = "success" if float(reward) > 0 else "fail"
                    step_groups[group].append(step_logp)
                    traj_groups[group][traj_id].append(step_logp)
        self.policy_engine.train()

        if self.use_deepspeed and is_dist_initialized():
            gathered_payloads = [None for _ in range(dist.get_world_size())]
            dist.all_gather_object(
                gathered_payloads,
                {
                    "step_groups": step_groups,
                    "traj_groups": {
                        "success": dict(traj_groups["success"]),
                        "fail": dict(traj_groups["fail"]),
                    },
                },
            )
            if self.rank == 0:
                merged_step_groups = {"success": [], "fail": []}
                merged_traj_groups = {
                    "success": defaultdict(list),
                    "fail": defaultdict(list),
                }
                for payload in gathered_payloads:
                    for group in ("success", "fail"):
                        merged_step_groups[group].extend(payload["step_groups"][group])
                        for traj_id, values in payload["traj_groups"][group].items():
                            merged_traj_groups[group][traj_id].extend(values)
                step_groups = merged_step_groups
                traj_groups = merged_traj_groups

        def _mean(values):
            if not values:
                return None
            return sum(values) / len(values)

        def _std(values, mean_value):
            if not values:
                return None
            return (sum((v - mean_value) ** 2 for v in values) / len(values)) ** 0.5

        if self.writer is not None and step_groups["success"] and step_groups["fail"]:
            step_stats = {
                "success": _mean(step_groups["success"]),
                "fail": _mean(step_groups["fail"]),
            }
            self.writer.add_scalar("eval_step/logp_success_mean", step_stats["success"], epoch)
            self.writer.add_scalar("eval_step/logp_fail_mean", step_stats["fail"], epoch)
            self.writer.add_scalar("eval_step/logp_margin", step_stats["success"] - step_stats["fail"], epoch)
            self.writer.add_scalar(
                "eval_step/logp_success_std",
                _std(step_groups["success"], step_stats["success"]),
                epoch,
            )
            self.writer.add_scalar(
                "eval_step/logp_fail_std",
                _std(step_groups["fail"], step_stats["fail"]),
                epoch,
            )

        success_traj_means = [_mean(v) for v in traj_groups["success"].values() if v]
        fail_traj_means = [_mean(v) for v in traj_groups["fail"].values() if v]
        if self.writer is not None and success_traj_means and fail_traj_means:
            success_mean = _mean(success_traj_means)
            fail_mean = _mean(fail_traj_means)
            self.writer.add_scalar("eval_traj/logp_success_mean", success_mean, epoch)
            self.writer.add_scalar("eval_traj/logp_fail_mean", fail_mean, epoch)
            self.writer.add_scalar("eval_traj/logp_margin", success_mean - fail_mean, epoch)
            self.writer.add_scalar("eval_traj/logp_success_std", _std(success_traj_means, success_mean), epoch)
            self.writer.add_scalar("eval_traj/logp_fail_std", _std(fail_traj_means, fail_mean), epoch)
        print(f"[rank{self.rank}] After Eval epoch={epoch}", flush=True)

    def _train_step(self, batch: Dict[str, Any]) -> Optional[Dict[str, torch.Tensor]]:
        task = batch["task"]
        image = batch["image"]
        target = batch["model_output"]

        print(batch["task"])
        
        cached, _ = build_cached_batch_from_uitars(
            self.policy_engine,
            self.processor,
            image,
            task,
            self.device,
            target=target,
            max_seq_len=self.args.max_seq_len,
            history_n=self.args.history_n,
        )
        if self._should_skip_batch(cached):
            return None

        with torch.no_grad():
            old_log_probs = compute_completion_log_probs_from_cached(self.old_model, cached)
            old_log_probs = old_log_probs.detach()
            reference_log_probs = self._compute_reference_log_probs(cached)

        reward = torch.as_tensor(batch["reward"], device=self.device, dtype=torch.float32)
        group_mean_reward = torch.as_tensor(batch["group_mean_reward"], device=self.device, dtype=reward.dtype)
        group_std_reward = torch.as_tensor(batch["group_std_reward"], device=self.device, dtype=reward.dtype).clamp_min(1e-6)

        adv = (reward - group_mean_reward) / group_std_reward
        completion_mask = cached.completion_token_mask()
        denom = completion_mask.sum(dim=1).clamp_min(1)
        token_denom = completion_mask.sum().clamp_min(1)

        new_log_probs = compute_completion_log_probs_from_cached(self.policy_engine, cached)
        per_token_loss, ratio = ppo_loss(old_log_probs, new_log_probs, adv, epsilon=self.args.clip_eps)
        
        kl_term = torch.exp(reference_log_probs - new_log_probs) - (reference_log_probs - new_log_probs) - 1
        kl_mean = ((kl_term * completion_mask).sum() / token_denom).detach()
        ratio_mean = ((ratio * completion_mask).sum() / token_denom).detach()
        clipped = ((ratio < (1 - self.args.clip_eps)) | (ratio > (1 + self.args.clip_eps))).to(completion_mask.dtype)
        clip_fraction = ((clipped * completion_mask).sum() / token_denom).detach()

        
        step_num = torch.as_tensor(
            batch["step_num"],
            device=per_token_loss.device,
            dtype=per_token_loss.dtype,
        )
        
        step_num = torch.clamp(step_num, min=1)

        if self.args.use_kl:
            token_loss_with_kl = per_token_loss + self.beta * kl_term
            per_sample_loss = (token_loss_with_kl * completion_mask).sum(dim=1) / denom
        else:
            per_sample_loss = (per_token_loss * completion_mask).sum(dim=1) / denom

        # Apply options.
        if self.args.div_traj_len:
            per_sample_loss = per_sample_loss / step_num

        policy_loss = per_sample_loss.mean()

        self.policy_engine.backward(policy_loss)
        self.policy_engine.step()
                
        metrics = {
            "loss_policy": policy_loss.detach(),
            "kl": kl_mean,
            "beta": torch.tensor(self.beta, device=self.device, dtype=torch.float32).detach(),
            "reward_mean": reward.mean().detach(),
            "adv_mean": adv.mean().detach(),
            "adv_std": adv.std(unbiased=False).detach(),
            "ratio_mean" : ratio_mean,
            "clip_fraction": clip_fraction,
        }
        if self.args.use_kl and self.args.use_adaptive_kl:
            if kl_mean > self.args.target_kl * 1.5:
                self.beta = min(self.beta * self.args.beta_up, self.args.max_beta)
            elif kl_mean < self.args.target_kl / 1.5:
                self.beta = max(self.beta / self.args.beta_down, self.args.min_beta)
        return metrics

    def train(self):
        self.policy_engine.train()
        if self.rank == 0:
            iter = 0

        for epoch in range(self.args.epochs):
            dataloader = self._build_epoch_dataloader()
            if self.rank == 0:
                print("[INFO]DataLoader is Ready.")
            self.old_model.to(self.device)
            print(f"[rank{self.rank}] Before Sync Old epoch={epoch}", flush=True)
            self._sync_old_model()
            print(f"[rank{self.rank}] After Sync Old epoch={epoch}", flush=True)
            self.old_model.eval()
            metric_sums = {
            "loss_policy": torch.zeros((), device=self.device),
            "kl": torch.zeros((), device=self.device),
            "beta": torch.zeros((), device=self.device),
            "reward_mean": torch.zeros((), device=self.device),
            "adv_mean": torch.zeros((), device=self.device),
            "adv_std": torch.zeros((), device=self.device),
            "ratio_mean": torch.zeros((), device=self.device),
            "clip_fraction": torch.zeros((), device=self.device)}
            count = torch.zeros((), device=self.device)
            if isinstance(dataloader.sampler, DistributedSampler):
                dataloader.sampler.set_epoch(epoch)
            pbar = tqdm(dataloader, disable=(self.rank != 0), desc=f"Epoch {epoch}")
            for batch in pbar:
                metrics = self._train_step(batch)
                if metrics is None:
                    continue
                    
                for k in metric_sums:
                    metric_sums[k] += metrics[k].detach()

                count += 1
            
                if self.writer is not None:
                    self.writer.add_scalar("iter/loss/policy", (metrics["loss_policy"]).item(), iter)
                    self.writer.add_scalar("iter/kl/divergence", (metrics["kl"]).item() , iter)
                    self.writer.add_scalar("iter/kl/beta", (metrics["beta"]).item(), iter)
                    self.writer.add_scalar("iter/reward/mean", (metrics["reward_mean"]).item(), iter)
                    self.writer.add_scalar("iter/adv/mean", (metrics["adv_mean"]).item(), iter)
                    self.writer.add_scalar("iter/adv/std", (metrics["adv_std"]).item(), iter)
                    self.writer.add_scalar("iter/ratio/mean", (metrics["ratio_mean"]).item(), iter)
                    self.writer.add_scalar("iter/policy/clip_fraction", (metrics["clip_fraction"]).item(), iter)
                    iter += 1
                
                

            if self.use_deepspeed and is_dist_initialized():
                for k in metric_sums:
                    dist.all_reduce(metric_sums[k], op=dist.ReduceOp.SUM)
                
                dist.all_reduce(count, op=dist.ReduceOp.SUM)
            
            self._save_epoch(epoch)
            if self.writer is not None and count.item() > 0:
                self.writer.add_scalar("epoch/loss/policy", (metric_sums["loss_policy"] / count).item(), epoch)
                self.writer.add_scalar("epoch/kl/divergence", (metric_sums["kl"] / count).item() , epoch)
                self.writer.add_scalar("epoch/kl/beta", (metric_sums["beta"] / count).item(), epoch)
                self.writer.add_scalar("epoch/reward/mean", (metric_sums["reward_mean"] / count).item(), epoch)
                self.writer.add_scalar("epoch/adv/mean", (metric_sums["adv_mean"] / count).item(), epoch)
                self.writer.add_scalar("epoch/adv/std", (metric_sums["adv_std"] / count).item(), epoch)
                self.writer.add_scalar("epoch/ratio/mean", (metric_sums["ratio_mean"] / count).item(), epoch)
                self.writer.add_scalar("epoch/policy/clip_fraction", (metric_sums["clip_fraction"] / count).item(), epoch)
            self._log_eval_subset(epoch)
            if self.use_deepspeed and is_dist_initialized():
                dist.barrier()

        if self.writer is not None:
            self.writer.close()
