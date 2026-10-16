import argparse
import csv
import json
from pathlib import Path


DEFAULT_BASE_DIR = Path("./results")
DEFAULT_DENOMINATOR = 23


def load_results(results_path: Path) -> list[dict]:
    with results_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"Expected a list in {results_path}, but got {type(data).__name__}")
    return data


def count_success(results: list[dict]) -> float:
    success = 0
    for item in results:
        score = item.get("score", 0)
        try:
            score_value = float(score)
            if score_value:
                success += score_value
        except (TypeError, ValueError):
            continue
    return round(success, 3)


def iter_result_dirs(base_dir: Path) -> list[Path]:
    return sorted(path for path in base_dir.iterdir() if path.is_dir())


def build_summary_rows(base_dir: Path, denominator: int) -> list[dict]:
    rows = []

    for experiment_dir in iter_result_dirs(base_dir):
        results_path = experiment_dir / "summary" / "results.json"
        if not results_path.exists():
            continue

        results = load_results(results_path)
        total = denominator
        success = count_success(results)
        percent = (success / total * 100.0) if total else 0.0

        rows.append(
            {
                "folder": experiment_dir.name,
                "sr": f"{percent:.2f}% [{success}/{total}]",
                "total_count": total,
            }
        )

    return rows


def write_csv(csv_path: Path, rows: list[dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "folder",
                "sr",
                "total_count",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print SR summary from summary/results.json for each experiment directory."
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=DEFAULT_BASE_DIR,
        help=f"Base directory that contains experiment folders. Default: {DEFAULT_BASE_DIR}",
    )
    parser.add_argument(
        "--denominator",
        type=int,
        default=DEFAULT_DENOMINATOR,
        help=f"Denominator to show in [a/N]. Default: {DEFAULT_DENOMINATOR}",
    )
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=None,
        help="Optional CSV output path. If omitted, a CSV is saved under the base directory.",
    )
    args = parser.parse_args()

    base_dir = args.base_dir.expanduser().resolve()
    if not base_dir.exists():
        raise FileNotFoundError(f"Base directory does not exist: {base_dir}")

    rows = build_summary_rows(base_dir, args.denominator)
    for row in rows:
        print(f'{row["folder"]}: {row["sr"]} total count {row["total_count"]}')

    csv_path = args.csv_path.expanduser().resolve() if args.csv_path else base_dir / "sr_summary.csv"
    write_csv(csv_path, rows)

    print(f"CSV saved to: {csv_path}")


if __name__ == "__main__":
    main()
