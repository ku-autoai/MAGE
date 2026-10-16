import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(__file__).resolve().parent
KEYWORD = "Available on all plans"
INPUT_FILES = [
    "Slack_eng.json",
    "Slack_eng_free.json",
]


def has_keyword_in_box_role(box_role, keyword):
    for role_box in box_role:
        for role_text in role_box.get("roles", []):
            if keyword in role_text:
                return True
    return False


def collect_matching_sections(items, keyword):
    matched = []

    for item in items:
        if not has_keyword_in_box_role(item.get("box_role", []), keyword):
            continue

        matched.append({
            "page": item.get("page"),
            "url": item.get("url"),
            "box_role": item.get("box_role", []),
            "section": item.get("section", []),
        })

    return matched


def write_filtered_json(input_name):
    input_path = BASE_DIR / input_name
    output_name = input_name.replace(".json", "_all_plans_sections.json")
    output_path = OUTPUT_DIR / output_name

    with input_path.open("r", encoding="utf-8") as f:
        items = json.load(f)

    matched = collect_matching_sections(items, KEYWORD)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=4)

    print(f"{input_name}: {len(matched)} entries -> {output_path.name}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for input_name in INPUT_FILES:
        write_filtered_json(input_name)


if __name__ == "__main__":
    main()
