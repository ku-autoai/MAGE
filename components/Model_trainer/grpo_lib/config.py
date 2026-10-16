import argparse
import os


def parse_args():
    parser = argparse.ArgumentParser("GRPO (offline rollouts) + LoRA with optional DeepSpeed")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--model_path", type=str, default="ByteDance-Seed/UI-TARS-1.5-7B")
    parser.add_argument("--data_root", type=str, required=True)
    parser.add_argument("--preprocessed_records_path", type=str, default=None)
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--run_name", type=str, default=None)
    parser.add_argument("--log_dir", type=str, default=None)
    parser.add_argument("--ds_config", type=str, default="config/ds_config.json")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument(
        "--include_failed_trajectories",
        "--use_false",
        dest="include_failed_trajectories",
        action="store_true",
        help="Include failed trajectories in training data.",
    )
    parser.add_argument("--use_lora", action="store_true")
    parser.add_argument("--lora_path", type=str, default=None)
    parser.add_argument("--resume_path", type=str, default=None)
    parser.add_argument("--lora_r", type=int, default=16)
    parser.add_argument("--lora_alpha", type=int, default=32)
    parser.add_argument("--lora_dropout", type=float, default=0.05)
    parser.add_argument("--lora_target", type=str, default="q_proj,v_proj,o_proj")
    parser.add_argument("--clip_eps", type=float, default=0.2)
    parser.add_argument("--beta", type=float, default=0.05)
    parser.add_argument(
        "--micro_batch_size_per_gpu",
        "--batch_size",
        dest="micro_batch_size_per_gpu",
        type=int,
        default=4,
        help="Per-GPU micro batch size. '--batch_size' is kept as a compatibility alias.",
    )
    parser.add_argument("--num_workers", type=int, default=4)
    parser.add_argument("--history_n", type=int, default=5)
    parser.add_argument("--max_seq_len", type=int, default=None)
    parser.add_argument("--local_rank", type=int, default=-1)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument(
        "--eval_subset_size",
        type=int,
        default=1,
        help="Number of success and fail trajectories to keep in the fixed eval subset. Set 0 to disable.",
    )

    parser.add_argument("--use_kl", action="store_true")
    parser.add_argument("--uniform_sampling", action="store_true")
    parser.add_argument("--target_kl", type=float, default=0.2)
    parser.add_argument("--use_adaptive_kl", action="store_true")
    parser.add_argument("--beta_up", type=float, default=1.5)
    parser.add_argument("--beta_down", type=float, default=1.5)
    parser.add_argument("--min_beta", type=float, default=1e-4)
    parser.add_argument("--max_beta", type=float, default=1e4)
    parser.add_argument("--normalize_adv", action="store_true")
    parser.add_argument("--engine", choices=["auto", "deepspeed", "python"], default="auto")
    parser.add_argument(
        "--div_traj_len",
        action="store_true",
        help="divide loss by trajectory length"
    )
    
    args = parser.parse_args()
    return args
