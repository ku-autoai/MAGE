import base64
import json
import os
from pathlib import Path

from config import API_KEY
from config import BASE_FOLDER
from config import END_INDEX
from config import FILTERED_SECTIONS_JSON_PATH
from config import MODEL_NAME
from config import PROGRAM_NAME
from config import START_INDEX
from config import TASKS_JSON_PATH
from openai import OpenAI
from prompt import instruciton_gen_prompt
from tqdm import tqdm


def image_path_to_base64(image_path: Path) -> str:
    with image_path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class LMMEngineOpenAI:
    def __init__(self, api_key: str, model: str = "gpt-5.4"):
        self.model = model
        self.llm_client = OpenAI(api_key=api_key)

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


def build_section_messages(section: dict) -> tuple[list[dict], list[int]]:
    title = section.get("title", "")
    path = section.get("path", [])
    text = section.get("text", "")
    start_page = int(section["start_page"])
    end_page = int(section["end_page"])

    content = [
        {"type": "text", "text": f"Program Name:\n{PROGRAM_NAME}"},
        {"type": "text", "text": f"Section Title:\n{title}"},
        {"type": "text", "text": f"Section Path:\n{' > '.join(path)}"},
        {"type": "text", "text": f"Section Page Range:\n{start_page}-{end_page}"},
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

    section_image_paths = section.get("image_paths")
    if not section_image_paths:
        raise RuntimeError("section must include non-empty image_paths")

    attached_pages = []
    selected_image_paths = section_image_paths[-3:]
    for image_path_str in selected_image_paths:
        image_path = Path(os.path.expandvars(os.path.expanduser(image_path_str)))
        if not image_path.is_absolute():
            image_path = BASE_FOLDER / image_path
        if not image_path.exists():
            raise FileNotFoundError(f"Section image does not exist: {image_path}")

        encoded_image = image_path_to_base64(image_path)
        image_url = f"data:image/png;base64,{encoded_image}"
        content.append({"type": "image_url", "image_url": {"url": image_url}})

        page_name = image_path.stem
        if page_name.startswith("page_"):
            try:
                attached_pages.append(int(page_name.split("_")[1]))
            except (IndexError, ValueError):
                pass

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
    return messages, attached_pages


def task_generate_for_section(llm: LMMEngineOpenAI, section: dict) -> dict:
    messages, attached_pages = build_section_messages(section)
    result = llm.generate(messages)

    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        parsed = {"error": "json_parse_error", "raw": result}

    return {
        "title": section.get("title"),
        "path": section.get("path"),
        "start_page": section.get("start_page"),
        "end_page": section.get("end_page"),
        "attached_image_pages": attached_pages,
        "task": parsed,
    }


def main() -> None:
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    manual_path = Path(FILTERED_SECTIONS_JSON_PATH)
    output_path = Path(TASKS_JSON_PATH)

    with manual_path.open("r", encoding="utf-8") as f:
        sections = json.load(f)

    if not isinstance(sections, list):
        raise RuntimeError("manual-json must be a list of section objects")

    end_index = END_INDEX if END_INDEX is not None else len(sections)
    start_index = max(0, START_INDEX)
    end_index = min(end_index, len(sections))

    llm = LMMEngineOpenAI(api_key=API_KEY, model=MODEL_NAME)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            all_results = json.load(f)
    else:
        all_results = []

    for idx in tqdm(range(start_index, end_index)):
        section = sections[idx]
        #print(f"Processing section {idx}: {section.get('title')}")
        result = task_generate_for_section(llm, section)
        result["section_index"] = idx
        all_results.append(result)

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
