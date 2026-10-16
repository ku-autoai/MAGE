import os
import logging
import time
import hashlib

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:64,expandable_segments:True"
os.environ["FLASH_ATTENTION_FORCE_DISABLED"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["DEEPSPEED_LOG_LEVEL"] = "error"

from transformers.utils import logging as hf_logging

try:
    from .grpo_lib.agent import GRPOAgent
    from .grpo_lib.config import parse_args
    from .util.seed import set_seed
except ImportError:
    from grpo_lib.agent import GRPOAgent
    from grpo_lib.config import parse_args
    from util.seed import set_seed


hf_logging.set_verbosity_error()
logging.getLogger("deepspeed").setLevel(logging.ERROR)

from datetime import datetime
import json



def _build_run_sync_path(base_output_dir: str) -> str:
    sync_key = "|".join(
        [
            os.path.abspath(base_output_dir),
            os.getenv("TORCHELASTIC_RUN_ID", ""),
            os.getenv("MASTER_ADDR", ""),
            os.getenv("MASTER_PORT", ""),
            os.getenv("WORLD_SIZE", "1"),
        ]
    )
    sync_name = f".run_name_sync_{hashlib.md5(sync_key.encode('utf-8')).hexdigest()}.json"
    return os.path.join(base_output_dir, sync_name)


def _resolve_run_output_dir(base_output_dir: str, requested_run_name: str | None, rank: int) -> str:
    world_size = int(os.getenv("WORLD_SIZE", "1"))
    if world_size <= 1:
        run_name = requested_run_name or datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(base_output_dir, run_name)

    os.makedirs(base_output_dir, exist_ok=True)
    sync_path = _build_run_sync_path(base_output_dir)

    if rank == 0:
        run_name = requested_run_name or datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(sync_path, "w", encoding="utf-8") as f:
            json.dump({"run_name": run_name}, f)
        return os.path.join(base_output_dir, run_name)

    deadline = time.time() + 60
    while time.time() < deadline:
        if os.path.exists(sync_path):
            with open(sync_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            return os.path.join(base_output_dir, payload["run_name"])
        time.sleep(0.1)

    raise TimeoutError(f"Timed out waiting for rank 0 to write run name sync file: {sync_path}")


def main():
    args = parse_args()
    if not args.use_kl:
        args.beta=0.0
        args.target_kl=0.0
        args.use_adaptive_kl=False
        args.beta_up=0.0
        args.beta_down=0.0
        args.min_beta=0.0
        args.max_beta=0.0

    base_output_dir = args.output_dir
    rank = int(os.getenv("RANK", "0"))
    run_output_dir = _resolve_run_output_dir(base_output_dir, args.run_name, rank)
    os.makedirs(run_output_dir, exist_ok=True)
    args.output_dir = run_output_dir
    if rank == 0:
        with open(os.path.join(run_output_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(vars(args), f, indent=2, ensure_ascii=False)
    if args.seed is not None:
        set_seed(args.seed)
    
    agent = GRPOAgent(args)
    agent.train()


if __name__ == "__main__":
    main()
