from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
from typing import Any

from config import (
    EMBED_DEVICE,
    EMBED_MODEL_ID,
    GENERATION_DEVICE,
    GENERATION_MODEL_ID,
    MANUAL_PATH,
    MAX_NEW_TOKENS,
    OUTPUT_PATH,
    SYSTEM_PROMPT,
    TASK_PATH,
    TOP_K,
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def concat_section_context(page: dict, section: dict) -> str:
    """Concatenate all textual context belonging to one manual section."""
    content = section.get("content", [])
    if isinstance(content, list):
        content_text = "\n".join(
            normalize_text(item) for item in content if normalize_text(item)
        )
    else:
        content_text = normalize_text(content)

    fields = [
        ("Page", page.get("page")),
        ("URL", page.get("url")),
        ("Section", section.get("title")),
        ("Content", content_text),
    ]
    return "\n".join(
        f"{label}: {normalize_text(value)}"
        for label, value in fields
        if normalize_text(value)
    )


def flatten_manual(manual_pages: list[dict]) -> list[dict]:
    sections = []
    for page_index, page in enumerate(manual_pages):
        page_sections = page.get("section", [])
        if not isinstance(page_sections, list):
            raise TypeError(f"manual[{page_index}].section must be a list")

        for section_index, section in enumerate(page_sections):
            context = concat_section_context(page, section)
            if not context:
                continue
            sections.append(
                {
                    "section_id": len(sections),
                    "page_index": page_index,
                    "section_index": section_index,
                    "page": normalize_text(page.get("page")),
                    "url": normalize_text(page.get("url")),
                    "title": normalize_text(section.get("title")),
                    "context": context,
                }
            )
    return sections


def concat_task_context(task: dict) -> str:
    """Use setup state and the main task together as the retrieval query."""
    setup_steps = task.get("setup_steps", [])
    if not isinstance(setup_steps, list):
        raise TypeError("setup_steps must be a list")

    fields = []
    setup_task = normalize_text(task.get("setup_task"))
    if setup_task:
        fields.append(f"Setup task: {setup_task}")
    if setup_steps:
        fields.append(
            "Completed setup steps:\n"
            + "\n".join(
                f"{index}. {normalize_text(step)}"
                for index, step in enumerate(setup_steps, start=1)
                if normalize_text(step)
            )
        )
    fields.append(f"Main task: {normalize_text(task.get('main_task'))}")
    return "\n".join(fields)


def validate_tasks(tasks: Any) -> list[dict]:
    if not isinstance(tasks, list):
        raise TypeError("Task JSON must contain a list")
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise TypeError(f"tasks[{index}] must be an object")
        if not normalize_text(task.get("main_task")):
            raise ValueError(f"tasks[{index}].main_task is empty")
        concat_task_context(task)
    return tasks


def load_embedding_model(model_id: str, device: str):
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=model_id,
        model_kwargs={"device": device},
        encode_kwargs={
            "normalize_embeddings": True,
            "batch_size": 8,
        },
    )


def build_vector_index(section_contexts: list[str], embedding_model):
    import faiss
    import numpy as np

    embeddings = np.asarray(
        embedding_model.embed_documents(section_contexts),
        dtype="float32",
    )
    if embeddings.ndim != 2 or embeddings.shape[0] != len(section_contexts):
        raise ValueError(
            "Embedding model returned an unexpected shape: "
            f"{embeddings.shape}"
        )
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    return index


def retrieve_sections(
    query: str,
    embedding_model,
    vector_index,
    manual_sections: list[dict],
    top_k: int,
) -> list[dict]:
    import faiss
    import numpy as np

    query_embedding = np.asarray(
        [embedding_model.embed_query(query)],
        dtype="float32",
    )
    faiss.normalize_L2(query_embedding)
    scores, indices = vector_index.search(
        query_embedding,
        min(top_k, len(manual_sections)),
    )

    retrieved = []
    for rank, (section_index, score) in enumerate(
        zip(indices[0], scores[0]),
        start=1,
    ):
        if section_index < 0:
            continue
        section = manual_sections[int(section_index)]
        retrieved.append(
            {
                "rank": rank,
                "score": float(score),
                **section,
            }
        )
    return retrieved


def build_messages(task: dict, retrieved_sections: list[dict]) -> list[dict]:
    setup_task = normalize_text(task.get("setup_task")) or "(none)"
    setup_steps = task.get("setup_steps", [])
    setup_steps_text = (
        "\n".join(
            f"{index}. {normalize_text(step)}"
            for index, step in enumerate(setup_steps, start=1)
        )
        if setup_steps
        else "(none)"
    )
    snippets = "\n\n".join(
        f"[Retrieved Section {item['rank']} | cosine score={item['score']:.6f}]\n"
        f"{item['context']}"
        for item in retrieved_sections
    )
    user_prompt = f"""Setup task (already completed):
{setup_task}

Setup steps (already completed):
{setup_steps_text}

Main task (generate a plan for this only):
{normalize_text(task.get("main_task"))}

Retrieved Slack manual sections:
{snippets}
"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def load_generation_model(model_id: str, device: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device_map = "auto" if device == "auto" else {"": device}
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype="auto",
        device_map=device_map,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    return model, tokenizer


def generate_plan(
    model,
    tokenizer,
    task: dict,
    retrieved_sections: list[dict],
    max_new_tokens: int,
) -> str:
    messages = build_messages(task, retrieved_sections)
    try:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    model_inputs = tokenizer(
        [prompt],
        padding=True,
        return_tensors="pt",
    ).to(model.device)
    generated_ids = model.generate(
        **model_inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    prompt_length = model_inputs["input_ids"].shape[1]
    generated_only = generated_ids[:, prompt_length:]
    decoded = tokenizer.batch_decode(generated_only, skip_special_tokens=True)
    return decoded[0].strip() if decoded else ""


def manual_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Retrieve Slack manual sections with Qwen embeddings and generate "
            "main-task-only plans with Qwen."
        )
    )
    parser.add_argument("--manual", type=Path, default=MANUAL_PATH)
    parser.add_argument("--tasks", type=Path, default=TASK_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--embed-model", default=EMBED_MODEL_ID)
    parser.add_argument("--generation-model", default=GENERATION_MODEL_ID)
    parser.add_argument("--embed-device", default=EMBED_DEVICE)
    parser.add_argument("--generation-device", default=GENERATION_DEVICE)
    parser.add_argument("--max-new-tokens", type=int, default=MAX_NEW_TOKENS)
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="Process only the first N tasks.",
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Run retrieval and save results without loading the generation model.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and concatenation without loading any model.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise ValueError("--top-k must be positive")
    if args.max_tasks is not None and args.max_tasks <= 0:
        raise ValueError("--max-tasks must be positive")

    manual_path = args.manual.resolve()
    task_path = args.tasks.resolve()
    output_path = args.output.resolve()

    manual_pages = load_json(manual_path)
    if not isinstance(manual_pages, list):
        raise TypeError("Manual JSON must contain a list")
    manual_sections = flatten_manual(manual_pages)
    if not manual_sections:
        raise ValueError("No manual sections were found")

    tasks = validate_tasks(load_json(task_path))
    if args.max_tasks is not None:
        tasks = tasks[: args.max_tasks]

    print(
        f"[INFO] Loaded {len(manual_pages)} pages, "
        f"{len(manual_sections)} sections, and {len(tasks)} tasks."
    )
    print("[INFO] Every section embeds page + URL + title + all textual content.")
    print("[INFO] Every retrieval query concatenates setup task + setup steps + main task.")

    if args.dry_run:
        print("[DRY RUN] First section context:")
        print(manual_sections[0]["context"])
        print("[DRY RUN] First task query:")
        print(concat_task_context(tasks[0]))
        return

    print(f"[INFO] Loading embedding model: {args.embed_model}")
    embedding_model = load_embedding_model(args.embed_model, args.embed_device)
    print("[INFO] Embedding all concatenated section contexts and building FAISS index...")
    vector_index = build_vector_index(
        [section["context"] for section in manual_sections],
        embedding_model,
    )

    task_results = []
    for index, task in enumerate(tasks, start=1):
        query = concat_task_context(task)
        retrieved = retrieve_sections(
            query,
            embedding_model,
            vector_index,
            manual_sections,
            args.top_k,
        )
        task_results.append(
            {
                **task,
                "retrieval_query": query,
                "retrieved_sections": retrieved,
                "main_task_plan": None,
            }
        )
        print(
            f"[RETRIEVAL {index}/{len(tasks)}] "
            f"{task['main_task']} -> "
            + ", ".join(item["title"] for item in retrieved)
        )

    del vector_index
    del embedding_model
    gc.collect()

    if not args.retrieval_only:
        print(f"[INFO] Loading generation model: {args.generation_model}")
        model, tokenizer = load_generation_model(
            args.generation_model,
            args.generation_device,
        )
        for index, result in enumerate(task_results, start=1):
            result["main_task_plan"] = generate_plan(
                model,
                tokenizer,
                result,
                result["retrieved_sections"],
                args.max_new_tokens,
            )
            print(f"[GENERATION {index}/{len(task_results)}] {result['main_task']}")

    output = {
        "metadata": {
            "manual_path": manual_path.name,
            "manual_sha256": manual_fingerprint(manual_path),
            "task_path": task_path.name,
            "embedding_model": args.embed_model,
            "generation_model": None if args.retrieval_only else args.generation_model,
            "top_k": args.top_k,
            "section_context_fields": [
                "page",
                "url",
                "section title",
                "all content items",
            ],
            "task_query_fields": [
                "setup_task",
                "all setup_steps",
                "main_task",
            ],
        },
        "tasks": task_results,
    }
    dump_json(output_path, output)
    print(f"[INFO] Saved {len(task_results)} task results to {output_path}")


if __name__ == "__main__":
    main()
