import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Aggregate instruction fields from examples/*/*.json into a single JSON list."
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=script_dir / "Plan" / "libreoffice_plan",
        help="Root path containing examples/*/*.json",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=script_dir / "outputs" / "aggregated_instructions.json",
        help="Output JSON file path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input_path
    output_path = args.output_path

    instruction_list = []
    for task_path in input_path.glob("examples/*/*.json"):
        with task_path.open("r", encoding="utf-8") as file:
            json_data = json.load(file)
        instruction = json_data.get("instruction")
        if instruction is not None:
            instruction_list.append(instruction)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(instruction_list, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
