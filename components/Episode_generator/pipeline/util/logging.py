import os
import json
import argparse
from datetime import datetime

def make_summary(ROOT_DIR, max_step = 100, model_path = None):
    meta_json = os.path.join(ROOT_DIR, "0_meta.json")

    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if os.path.exists(meta_json):
        with open(meta_json, "r") as f:
            result = json.load(f)
    else:
        result = {
            "Data_Generate_info":{
                "start_time" : now_time,
                "end_time" : now_time,
                "time_term" : 0,
                "model_parameter": model_path if model_path is not None else None
            },
            "Result" : {
                "success rate" : 0,
                "success rate (setup)" : 0,
                "success rate (main)" : 0,
                "average step (total)" : 0,
                "average step (success)" : 0,
                "average step (fail)" : 0,
                "max step ratio (total)" : 0,
                "max step ratio (success)" : 0,
                "max step ratio (fail)" : 0,
            },
            "Detail": {
                "total": 0,
                "total_success": 0,
                "total_failure": 0,
                "setup": 0,
                "setup_success": 0,
                "setup_fail": 0,
                "main": 0,
                "main_success": 0,
                "main_fail": 0 
            },
            "folders": {}
        }

    total_step = []
    success_step = []
    fail_step = []

    result["Detail"] = {
            "total": 0,
            "total_success": 0,
            "total_failure": 0,
            "setup": 0,
            "setup_success": 0,
            "setup_fail": 0,
            "main": 0,
            "main_success": 0,
            "main_fail": 0 
        }

    for folder_name in sorted(os.listdir(ROOT_DIR)):
        folder_path = os.path.join(ROOT_DIR, folder_name)
        if not os.path.isdir(folder_path):
            continue

        folder_total = 0
        folder_success = 0
        folder_failure = 0
        setup_total = 0
        setup_success = 0
        setup_failure = 0
        main_total = 0
        main_success = 0
        main_failure = 0

        details = {}

        json_files = sorted(
            [f for f in os.listdir(folder_path) if f.endswith(".json")]
        )
        
        for idx, json_file in enumerate(json_files, start=1):
            json_path = os.path.join(folder_path, json_file)
            print(json_path)
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                final_result = bool(data.get("final_result", False))
                details[str(idx)] = final_result

                folder_total += 1
                if final_result:
                    folder_success += 1
                else:
                    folder_failure += 1
                
                if "main" in json_file:
                    main_total += 1
                    if final_result:
                        main_success += 1
                    else:
                        main_failure += 1 

                if "setup" in json_file:
                    setup_total += 1
                    if final_result:
                        setup_success += 1
                    else:
                        setup_failure += 1 

            except Exception as e:
                print(f"[ERROR] {json_path}: {e}")
                details[str(idx)] = "error"

        step = len(data["steps"])
        result["folders"][folder_name] = {
            "step" : step,
            "total": folder_total,
            "success": folder_success,
            "failure": folder_failure,
            "details": details
        }

        total_step.append(step)
        if folder_success == 1:
            success_step.append(step)
        else:
            fail_step.append(step)

        print(success_step)

        result["Detail"]["total"] += folder_total
        result["Detail"]["total_success"] += folder_success
        result["Detail"]["total_failure"] += folder_failure
        result["Detail"]["setup"] += setup_total
        result["Detail"]["setup_success"] += setup_success
        result["Detail"]["setup_fail"] += setup_failure
        result["Detail"]["main"] += main_total
        result["Detail"]["main_success"] += main_success
        result["Detail"]["main_fail"] += main_failure

    max_total_cnt = total_step.count(max_step)
    max_success_cnt = success_step.count(max_step)
    max_fail_cnt = fail_step.count(max_step)

    max_total = max_total_cnt / len(total_step) if total_step else 0
    max_success = max_success_cnt / len(success_step) if success_step else 0
    max_fail = max_fail_cnt / len(fail_step) if fail_step else 0

    total_avg = sum(total_step) / len(total_step) if total_step else 0
    success_avg = sum(success_step) / len(success_step) if success_step else 0
    fail_avg = sum(fail_step) / len(fail_step) if fail_step else 0

    result["Result"]["success rate"] = round(
        result["Detail"]["total_success"] / result["Detail"]["total"], 2
    ) if result["Detail"]["total"] > 0 else 0.0

    result["Result"]["success rate (setup)"] = round(
        result["Detail"]["setup_success"] / result["Detail"]["setup"], 2
    ) if result["Detail"]["setup"] > 0 else 0.0

    result["Result"]["success rate (main)"] = round(
        result["Detail"]["main_success"] / result["Detail"]["main"], 2
    ) if result["Detail"]["main"] > 0 else 0.0
    
    result["Result"]["average step (total)"] = round(total_avg,2)
    result["Result"]["average step (success)"] = round(success_avg,2)
    result["Result"]["average step (fail)"] = round(fail_avg,2)
    result["Result"]["max step ratio (total)"] = round(max_total,2)
    result["Result"]["max step ratio (success)"] = round(max_success,2)
    result["Result"]["max step ratio (fail)"] = round(max_fail,2)

    result["Data_Generate_info"]["end_time"] = now_time

    start_time_str =  result["Data_Generate_info"]["start_time"]
    end_time_str   = result["Data_Generate_info"]["end_time"]

    fmt = "%Y-%m-%d %H:%M:%S"

    start_time = datetime.strptime(start_time_str, fmt)
    end_time   = datetime.strptime(end_time_str, fmt)

    time_delta = end_time - start_time
    seconds = int(time_delta.total_seconds())
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    result["Data_Generate_info"]["time_term"] = f"{h}h {m}m {s}s"
    # Save the result.
    with open(meta_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4, ensure_ascii=False)

    print(f"[DONE] Result saved to {meta_json}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build summary metrics from episode result json files."
    )
    parser.add_argument(
        "--base_dir",
        type=str,
        required=True,
        help="Root directory that contains per-task result folders.",
    )
    parser.add_argument(
        "--max_step",
        type=int,
        default=60,
        help="Max-step threshold used for max-step ratio metrics.",
    )
    parser.add_argument(
        "--model_path",
        type=str,
        default=None,
        help="Optional model path to store in summary metadata.",
    )
    args = parser.parse_args()

    make_summary(args.base_dir, max_step=args.max_step, model_path=args.model_path)
