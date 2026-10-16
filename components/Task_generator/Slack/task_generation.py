import argparse
import base64
import json
import os
from pathlib import Path
import random
from openai import OpenAI
from prompt import instruciton_gen_prompt

def image_path_to_base64(image_path: Path) -> str:
    with image_path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class LMMEngineOpenAI:
    def __init__(self, api_key: str, model: str = "o3", rate_limit: int = -1):
        self.model = model
        self.api_key = api_key
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.llm_client = OpenAI(api_key=self.api_key)

    def generate(self, messages, temperature: float = 1.0, max_new_tokens: int = 4096):
        response = self.llm_client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=max_new_tokens,
            temperature=temperature,
        )
        if not response.choices:
            raise RuntimeError("No choices returned from the API")
        return response.choices[0].message.content


def build_section_messages(section: dict, image_dir: Path) -> tuple[list[dict], list[int]]:
    title = section.get("title", "")
    text = section.get("content", "")
    image_list = section.get('image',[])
    content = [
        {"type": "text", "text": "Program Name:\nSlack"},
        {"type": "text", "text": f"Section Title:\n{title}"},
        {"type": "text", "text": f"Manual Text:\n{text}"},
        {
            "type": "text",
            "text": (
                "Reference Images:\n"
                "The following images are in page order for this section. "
                "Use all provided images as context."
            ),
        },
    ]

    for image in image_list:
        img_path = image_dir / image.get("path")
        if not img_path.exists():
            continue
        encoded_image = image_path_to_base64(img_path)
        image_url = f"data:image/png;base64,{encoded_image}"
        content.append({"type": "image_url", "image_url": {"url": image_url}})

    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": instruciton_gen_prompt}],
        },
        {
            "role": "user",
            "content": content,
        },
    ]
    return messages


def task_generate_for_section(llm: LMMEngineOpenAI, section: dict, image_dir: Path) -> dict:
    messages = build_section_messages(section, image_dir)
    result = llm.generate(messages)

    print(result)

    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        parsed = {"error": "json_parse_error", "raw": result}

    return {
        "title": section.get("title"),
        "task": parsed,
    }


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Generate tasks from section-based manual JSON.")
    parser.add_argument(
        "--manual-json",
        default=str(script_dir / "box_role_all_plans" / "Slack_eng_free_all_plans_sections.json"),
        help="Section-based manual JSON path",
    )
    parser.add_argument(
        "--image-dir",
        default=str(script_dir),
        help="Directory containing page images like page_49.png",
    )
    parser.add_argument(
        "--output",
        default=str(script_dir / "Task" / "Slack_section_instruction.json"),
        help="Output JSON path",
    )
    parser.add_argument("--start-index", type=int, default=0, help="Start section index (inclusive)")
    parser.add_argument("--end-index", type=int, default=None, help="End section index (exclusive)")
    parser.add_argument("--model", default="o3", help="OpenAI model name")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    manual_path = Path(args.manual_json)
    image_dir = Path(args.image_dir)
    output_path = Path(args.output)

    with manual_path.open("r", encoding="utf-8") as f:
        info = json.load(f)

    sections = []

    for page in info:
        box_role = page.get("box_role", [])

        for section in page.get("section", []):
            section["box_role"] = box_role
            sections.append(section)

    sample_size = min(70, len(sections))
    sampled_sections = random.sample(sections, sample_size)

    print(len(sampled_sections))
    #

    llm = LMMEngineOpenAI(api_key=api_key, model=args.model)

    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            all_results = json.load(f)
    else:
        all_results = []

    for idx, section in enumerate(sampled_sections):
        try:
            result = task_generate_for_section(llm, section, image_dir)

            if result == None:
                continue

            result["section_index"] = idx
            all_results.append(result)
        except Exception as e:
            all_results.append(
                {
                    "section_index": idx,
                    "title": section.get("title"),
                    "error": str(e),
                }
            )

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)



if __name__ == "__main__":
    main()
