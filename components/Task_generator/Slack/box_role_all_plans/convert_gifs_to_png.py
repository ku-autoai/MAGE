import json
from pathlib import Path

from PIL import Image


BASE_DIR = Path(__file__).resolve().parent.parent
TARGET_JSONS = [
    "Slack_eng_all_plans_sections.json",
    "Slack_eng_free_all_plans_sections.json",
    "Slack_kor_all_plans_sections.json",
    "Slack_kor_free_all_plans_sections.json",
]


def convert_gif_to_png(image_path):
    png_path = image_path.with_suffix(".png")

    if not png_path.exists():
        with Image.open(image_path) as img:
            img.seek(0)
            frame = img.convert("RGBA")
            frame.save(png_path, "PNG")

    return png_path


def update_image_paths(data):
    converted_count = 0

    for page in data:
        for section in page.get("section", []):
            for image in section.get("images", []):
                rel_path = image.get("path")
                if not rel_path or not rel_path.lower().endswith(".gif"):
                    continue

                gif_path = BASE_DIR / rel_path
                if not gif_path.exists():
                    continue

                png_path = convert_gif_to_png(gif_path)
                image["path"] = str(png_path.relative_to(BASE_DIR))
                converted_count += 1

    return converted_count


def process_json(json_name):
    json_path = Path(__file__).resolve().parent / json_name
    if not json_path.exists():
        return

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    converted_count = update_image_paths(data)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"{json_name}: converted {converted_count} gif paths")


def main():
    for json_name in TARGET_JSONS:
        process_json(json_name)


if __name__ == "__main__":
    main()
