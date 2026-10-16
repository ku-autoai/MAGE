import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _load_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _repo_root():
    return Path(__file__).resolve().parents[3]


def _resolve_path(value: str):
    expanded = os.path.expandvars(os.path.expanduser(value))
    if "$" in expanded:
        raise ValueError(f"Unresolved environment variable in path: {value}")
    if os.path.isabs(expanded):
        return expanded
    return str((_repo_root() / expanded).resolve())


def _build_arg_list(arg_map):
    cli_args = []
    for key, value in arg_map.items():
        flag = f"--{key}"
        if isinstance(value, bool):
            if value:
                cli_args.append(flag)
            continue
        if value is None:
            continue
        cli_args.extend([flag, str(value)])
    return cli_args


def _normalize_args(arg_map):
    normalized = dict(arg_map)
    path_fields = {
        "data_root",
        "preprocessed_records_path",
        "output_dir",
        "log_dir",
        "ds_config",
        "lora_path",
        "resume_path",
    }
    for field_name in path_fields:
        field_value = normalized.get(field_name)
        if isinstance(field_value, str):
            normalized[field_name] = _resolve_path(field_value)
    return normalized


def _build_command(config):
    launcher = config.get("launcher", {})
    launcher_type = launcher.get("type", "deepspeed")

    train_args = _normalize_args(config.get("args", {}))

    if launcher_type == "deepspeed":
        command = ["deepspeed"]

        if launcher.get("master_port") is not None:
            command.extend(["--master_port", str(launcher["master_port"])])
        if launcher.get("include"):
            command.extend(["--include", str(launcher["include"])])

        command.append("Model_trainer/grpo.py")

    elif launcher_type == "python":
        command = [sys.executable, "-m", "Model_trainer.grpo"]

    else:
        raise ValueError(f"unsupported launcher type: {launcher_type}")

    command.extend(_build_arg_list(train_args))
    return command


def parse_args():
    parser = argparse.ArgumentParser(description="Run GRPO training from a JSON config.")
    parser.add_argument("--config", required=True, type=str)
    return parser.parse_args()


def main():
    args = parse_args()
    config = _load_config(args.config)
    command = _build_command(config)

    env = os.environ.copy()
    for key, value in config.get("env", {}).items():
        env[key] = str(value)

    subprocess.run(command, check=True, env=env)


if __name__ == "__main__":
    main()
