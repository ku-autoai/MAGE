import os
import traceback
import argparse
import asyncio

from util.io import load_yaml_config
from pipeline.agent_manager import AgentManager

def parse_args():

    parser = argparse.ArgumentParser(description="Data generator: Server")
    parser.add_argument("--config", default='./config/config.yaml', type=str, help="path of config file")
    parser.add_argument("--api_key", default=None, type=str, help="api key for gpt")
    parser.add_argument("--port", default=1357, type=int)
    parser.add_argument("--host", default="0.0.0.0", type=str)
    parser.add_argument("--lora_path", default=None)
    parser.add_argument("--base_dir", default="./test")
    parser.add_argument("--lora_epochs", nargs="+", type=int, default=[0])
    parser.add_argument("--start_task_idx", default=0, type=int)
    parser.add_argument("--trajectory_num", default=1, type=int)
    parser.add_argument("--end_task_idx", default=-1, type=int)
    parser.add_argument("--with_step", action="store_true")
    parser.add_argument("--rag", action="store_true", help="Whether to use RAG for retrieval during episode generation.")
    parser.add_argument("--max_step", default=50, type=int)
    parser.add_argument(
        "--program",
        type=str,
        choices=["calc", "slack", "impress", "writer"],
        required=True,
        help="program to generate episodes for: calc | slack | impress | writer",
    )
    parser.add_argument(
        "--mark-coords",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether to render coordinate markers on screenshots for click/drag actions.",
    )
    parser.add_argument(
        "--mod",
        type=str,
        choices=["train", "val"],
        required=True,
        help="run mode: train | val",
    )
    

    args = parser.parse_args()
    return args

async def main():
    try:
        args = parse_args()
        config = load_yaml_config(args.config) 

        api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Pass --api_key or export OPENAI_API_KEY.")

        os.environ["OPENAI_API_KEY"] = api_key
        manager = AgentManager(args.host, args.port, api_key, config, args)
        await manager.run_server()
    except Exception as e:
        print("[!] Uncaught exception in main():")
        traceback.print_exc()
        raise

if __name__ == "__main__":

    asyncio.run(main())
