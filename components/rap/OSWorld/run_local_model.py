from __future__ import annotations

import argparse
import gc
import json
import os
import re
import shutil
from pathlib import Path

from config import (
    EMBED_DEVICE_NUM,
    EMBED_MODEL_ID,
    EVALUATION_EXAMPLES_ROOT,
    FIRST_IMAGE_ROOT,
    GENERATION_BATCH_SIZE,
    GENERATION_DEVICE_NUMS,
    K,
    MANUAL_PATH,
    MAX_NEW_TOKENS,
    META_FILE_NAMES,
    OUTPUT_ROOT,
    PROGRAM_NAME,
    REWRITE_MODEL_ID,
    SYSTEM_PROMPT,
)


STEP1_IMAGE_PATTERN = re.compile(r"step[_-]?0*1(?:[_@.-]|$)", re.IGNORECASE)
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def dump_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_manual(manual_path: Path) -> list[dict]:
    manual_json = load_json(manual_path)
    return [
        {
            "section_id": index,
            "text": manual_section["text"],
            "text_full": manual_section["text"],
            "start_page": manual_section.get("start_page"),
            "end_page": manual_section.get("end_page"),
        }
        for index, manual_section in enumerate(manual_json)
    ]


def load_example_items(examples_dir: Path) -> list[dict]:
    example_items = []
    for json_path in sorted(examples_dir.glob("*.json")):
        item = load_json(json_path)
        item["_source_path"] = json_path.relative_to(examples_dir.parent.parent).as_posix()
        example_items.append(item)
    return example_items


def load_embed_model(device_num: int) -> HuggingFaceEmbeddings:
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=EMBED_MODEL_ID,
        model_kwargs={"device": f"cuda:{device_num}"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_vectorstore(manual_sections: list[dict], embed_model: HuggingFaceEmbeddings) -> FAISS:
    from langchain_community.vectorstores import FAISS
    from langchain_community.vectorstores.faiss import DistanceStrategy

    texts = [section["text"] for section in manual_sections]
    metadatas = [
        {
            "section_id": section["section_id"],
            "start_page": section.get("start_page"),
            "end_page": section.get("end_page"),
        }
        for section in manual_sections
    ]
    return FAISS.from_texts(
        texts,
        embed_model,
        metadatas=metadatas,
        normalize_L2=True,
        distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
    )


def retrieve(
    task: str,
    vectorstore: FAISS,
    manual_sections_by_id: dict[int, dict],
    k: int,
) -> tuple[list[str], list[tuple[int | None, int | None]]]:
    docs = vectorstore.similarity_search(task, k=k)
    doc_texts = [
        manual_sections_by_id[doc.metadata["section_id"]]["text_full"]
        for doc in docs
    ]
    page_ranges = [
        (doc.metadata.get("start_page"), doc.metadata.get("end_page"))
        for doc in docs
    ]
    return doc_texts, page_ranges


def get_generation_max_memory(device_nums: list[int]) -> dict[int, int]:
    import torch

    if not device_nums:
        raise ValueError("At least one generation GPU id is required.")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for generation.")
    if len(set(device_nums)) != len(device_nums):
        raise ValueError(f"Generation GPU ids must be unique: {device_nums}")

    device_count = torch.cuda.device_count()
    invalid_devices = [
        device_num
        for device_num in device_nums
        if device_num < 0 or device_num >= device_count
    ]
    if invalid_devices:
        raise ValueError(
            f"Invalid generation GPU ids {invalid_devices}; "
            f"available ids are 0 through {device_count - 1}."
        )

    reserve_bytes = 2 * 1024**3
    max_memory: dict[int, int] = {}
    for device_num in device_nums:
        free_bytes, _ = torch.cuda.mem_get_info(device_num)
        usable_bytes = free_bytes - reserve_bytes
        if usable_bytes <= 0:
            raise RuntimeError(
                f"cuda:{device_num} has less than 2 GiB of free VRAM available."
            )
        max_memory[device_num] = usable_bytes
        print(
            f"[INFO] cuda:{device_num} model-weight budget: "
            f"{usable_bytes / 1024**3:.2f} GiB "
            f"({free_bytes / 1024**3:.2f} GiB currently free)"
        )
    return max_memory


def get_rewrite_model(device_nums: list[int]):
    from transformers import AutoModelForImageTextToText, AutoProcessor

    max_memory = get_generation_max_memory(device_nums)
    model = AutoModelForImageTextToText.from_pretrained(
        REWRITE_MODEL_ID,
        torch_dtype="auto",
        device_map="balanced",
        max_memory=max_memory,
        low_cpu_mem_usage=True,
    )

    device_map = getattr(model, "hf_device_map", {})
    offloaded_devices = {
        str(device)
        for device in device_map.values()
        if str(device) in {"cpu", "disk"}
    }
    if offloaded_devices:
        raise RuntimeError(
            "The generation model did not fit entirely on the declared GPUs; "
            f"unexpected offload targets: {sorted(offloaded_devices)}"
        )

    used_devices = sorted({str(device) for device in device_map.values()})
    print(f"[INFO] Sharded generation model devices: {used_devices}")
    processor = AutoProcessor.from_pretrained(REWRITE_MODEL_ID)
    return model, processor


def get_model_input_device(model) -> torch.device:
    try:
        return model.get_input_embeddings().weight.device
    except (AttributeError, RuntimeError):
        return model.device


def build_messages(
    task: str,
    docs: list[str],
    first_screen_image_path: str | None,
) -> list[dict]:
    snippets_text = "\n\n".join(
        f"[Snippet {index + 1}]\n{doc}" for index, doc in enumerate(docs)
    )
    user_text = f"""Task:
{task}

Retrieved snippets:
{snippets_text}"""
    user_content = []
    if first_screen_image_path:
        user_content.append({"type": "image", "image": first_screen_image_path})
    user_content.append({"type": "text", "text": user_text})
    return [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]},
        {"role": "user", "content": user_content},
    ]


def build_model_inputs(processor, messages: list[dict], first_screen_image_path: str | None, device):
    try:
        text = processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        text = processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    if first_screen_image_path is None:
        return processor(
            text=[text],
            padding=True,
            return_tensors="pt",
        ).to(device)

    image_path = Path(first_screen_image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {first_screen_image_path}")

    from PIL import Image

    with Image.open(image_path) as image:
        rgb_image = image.convert("RGB")
    return processor(
        text=[text],
        images=[rgb_image],
        padding=True,
        return_tensors="pt",
    ).to(device)


def rewrite_batch(
    model,
    processor,
    batch_jobs: list[tuple[int, str, list[str], list[tuple[int | None, int | None]], str | None]],
) -> list[str]:
    responses = []
    input_device = get_model_input_device(model)
    for _, task, docs, _, first_screen_image_path in batch_jobs:
        messages = build_messages(task, docs, first_screen_image_path)
        model_inputs = build_model_inputs(
            processor,
            messages,
            first_screen_image_path,
            input_device,
        )
        generated_ids = model.generate(**model_inputs, max_new_tokens=MAX_NEW_TOKENS)
        prompt_length = model_inputs["input_ids"].shape[1]
        generated_only_ids = generated_ids[:, prompt_length:]
        decoded = processor.batch_decode(generated_only_ids, skip_special_tokens=True)
        responses.append(decoded[0] if decoded else "")
    return responses


def batched(items: list, batch_size: int):
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def find_step1_image(task_dir: Path) -> str | None:
    # For each task directory, we first look for the step1 image; if it is unavailable, we use the earliest available step image instead.
    image_files = sorted(
        file_path
        for file_path in task_dir.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    )
    if not image_files:
        return None

    step1_candidates = [
        file_path for file_path in image_files if STEP1_IMAGE_PATTERN.search(file_path.stem)
    ]
    if step1_candidates:
        return str(step1_candidates[0].resolve())

    step_candidates = [file_path for file_path in image_files if file_path.stem.lower().startswith("step")]
    if step_candidates:
        return str(step_candidates[0].resolve())
    return str(image_files[0].resolve())


def build_first_screen_image_map(first_image_root: Path, program_name: str) -> dict[str, str]:
    # We index the step1 image for each task_id by searching the entire screenshot root for the <program_name>/<task_id> directory structure.
    if not first_image_root.exists():
        return {}

    image_map: dict[str, str] = {}
    for task_dir in first_image_root.glob(f"**/{program_name}/*"):
        if not task_dir.is_dir():
            continue
        image_path = find_step1_image(task_dir)
        if image_path:
            image_map[task_dir.name] = image_path
    return image_map


def prepare_generation_jobs(
    task_items: list[dict],
    vectorstore: FAISS,
    manual_sections_by_id: dict[int, dict],
    k: int,
    first_screen_image_map: dict[str, str],
) -> list[tuple[int, str, list[str], list[tuple[int | None, int | None]], str | None]]:
    jobs = []
    for index, task_item in enumerate(task_items):
        task = task_item["instruction"]
        task_id = task_item.get("id")
        first_screen_image_path = first_screen_image_map.get(task_id)
        docs, page_ranges = retrieve(task, vectorstore, manual_sections_by_id, k)
        jobs.append((index, task, docs, page_ranges, first_screen_image_path))
    return jobs


def generate_relevant_procedures(
    device_nums: list[int],
    jobs: list[tuple[int, str, list[str], list[tuple[int | None, int | None]], str | None]],
) -> list[tuple[int, str]]:
    from tqdm import tqdm

    model, processor = get_rewrite_model(device_nums)
    indices = [index for index, *_ in jobs]
    for _, _, _, _, first_screen_image_path in jobs:
        print(first_screen_image_path)

    results = []
    job_batches = list(batched(jobs, GENERATION_BATCH_SIZE))
    total_batches = len(job_batches)
    for batch_idx, job_batch in tqdm(
        enumerate(job_batches),
        total=total_batches,
        desc=f"Sharded GPUs {device_nums}",
    ):
        index_batch = indices[
            batch_idx * GENERATION_BATCH_SIZE : (batch_idx + 1) * GENERATION_BATCH_SIZE
        ]
        responses = rewrite_batch(model, processor, job_batch)
        results.extend(zip(index_batch, responses))

    return results


def attach_relevant_procedures(
    task_items: list[dict],
    relevant_procedures: list[str],
    retrieved_page_ranges: list[list[tuple[int | None, int | None]]],
    first_screen_image_paths: list[str | None],
) -> list[dict]:
    results = []
    for item, relevant_procedure, page_ranges, first_screen_image_path in zip(
        task_items, relevant_procedures, retrieved_page_ranges, first_screen_image_paths
    ):
        result = item.copy()
        result["relevant_procedure"] = relevant_procedure
        result["retrieved_page_ranges"] = page_ranges
        # We record the path of the actual initial screenshot used in the results to ensure reproducibility of the same input during post-processing or debugging.
        result["first_screen_image_path"] = (
            Path(first_screen_image_path).resolve().relative_to(Path(FIRST_IMAGE_ROOT).resolve()).as_posix()
            if first_screen_image_path else None
        )
        results.append(result)
    return results


def append_relevant_procedure(instruction: str, relevant_procedure: str) -> str:
    return f"{instruction.rstrip()}\n\n{relevant_procedure.strip()}"


def rewrite_eval_relative_paths(value, output_root_name: str):
    if isinstance(value, dict):
        return {key: rewrite_eval_relative_paths(subvalue, output_root_name) for key, subvalue in value.items()}
    if isinstance(value, list):
        return [rewrite_eval_relative_paths(item, output_root_name) for item in value]
    if isinstance(value, str):
        return value.replace("evaluation_examples/", f"{output_root_name}/")
    return value


def collect_eval_relative_paths(value) -> set[str]:
    paths = set()
    if isinstance(value, dict):
        for subvalue in value.values():
            paths.update(collect_eval_relative_paths(subvalue))
    elif isinstance(value, list):
        for item in value:
            paths.update(collect_eval_relative_paths(item))
    elif isinstance(value, str) and value.startswith("evaluation_examples/"):
        paths.add(value)
    return paths


def build_augmented_examples(
    results: list[dict],
    output_root_name: str,
) -> list[dict]:
    augmented = []
    for item in results:
        updated = item.copy()
        updated["instruction"] = append_relevant_procedure(
            item["instruction"],
            item["relevant_procedure"],
        )
        updated = rewrite_eval_relative_paths(updated, output_root_name)
        augmented.append(updated)
    return augmented


def write_augmented_examples(
    augmented_examples: list[dict],
    output_root: Path,
    program_name: str,
) -> set[str]:
    output_examples_dir = output_root / "examples" / program_name
    output_examples_dir.mkdir(parents=True, exist_ok=True)

    referenced_paths = set()
    for item in augmented_examples:
        example_id = item["id"]
        dump_json(output_examples_dir / f"{example_id}.json", item)
        referenced_paths.update(collect_eval_relative_paths(item))
    return referenced_paths


def copy_metadata_files(
    source_root: Path,
    output_root: Path,
    program_name: str,
    selected_ids: set[str],
) -> None:
    for meta_name in META_FILE_NAMES:
        source_meta_path = source_root / meta_name
        if not source_meta_path.exists():
            continue

        meta = load_json(source_meta_path)
        if program_name not in meta:
            continue

        filtered_ids = [item_id for item_id in meta[program_name] if item_id in selected_ids]
        dump_json(output_root / meta_name, {program_name: filtered_ids})


def discover_nested_eval_paths_in_text(text: str) -> set[str]:
    return set(re.findall(r"evaluation_examples/[A-Za-z0-9_./-]+", text))


def copy_support_file(
    relative_path: str,
    source_root: Path,
    output_root: Path,
    seen_paths: set[str],
) -> None:
    if relative_path in seen_paths:
        return
    seen_paths.add(relative_path)

    source_path = source_root.parent / relative_path
    target_path = output_root / Path(relative_path).relative_to("evaluation_examples")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if not source_path.exists():
        return

    if source_path.suffix in {".json", ".yml", ".yaml"}:
        text = source_path.read_text(encoding="utf-8")
        nested_paths = discover_nested_eval_paths_in_text(text)
        output_reference = Path(os.path.relpath(output_root, source_root.parent)).as_posix()
        rewritten_text = text.replace("evaluation_examples/", f"{output_reference}/")
        target_path.write_text(rewritten_text, encoding="utf-8")
        for nested_path in nested_paths:
            copy_support_file(nested_path, source_root, output_root, seen_paths)
        return

    shutil.copy2(source_path, target_path)


def copy_support_files(
    referenced_paths: set[str],
    source_root: Path,
    output_root: Path,
) -> None:
    seen_paths = set()
    for relative_path in sorted(referenced_paths):
        copy_support_file(relative_path, source_root, output_root, seen_paths)


def run_image_input_smoke_test(smoke_example_index: int) -> int:
    from transformers import AutoProcessor

    source_root = Path(EVALUATION_EXAMPLES_ROOT).resolve()
    first_image_root = Path(FIRST_IMAGE_ROOT).resolve()
    examples_dir = source_root / "examples" / PROGRAM_NAME

    if not examples_dir.exists():
        raise FileNotFoundError(f"Examples directory not found: {examples_dir}")

    example_items = load_example_items(examples_dir)
    if not example_items:
        raise ValueError(f"No examples found in: {examples_dir}")
    if smoke_example_index < 0 or smoke_example_index >= len(example_items):
        raise IndexError(
            f"--smoke_example_index must be in [0, {len(example_items) - 1}], "
            f"got {smoke_example_index}"
        )

    first_screen_image_map = build_first_screen_image_map(first_image_root, PROGRAM_NAME)
    task_item = example_items[smoke_example_index]
    task = task_item["instruction"]
    task_id = task_item.get("id")
    first_screen_image_path = first_screen_image_map.get(task_id)
    image_exists = bool(first_screen_image_path and Path(first_screen_image_path).exists())

    processor = AutoProcessor.from_pretrained(REWRITE_MODEL_ID)

    smoke_docs = ["Smoke test snippet."]
    messages_with_image = build_messages(task, smoke_docs, first_screen_image_path)
    messages_without_image = build_messages(task, smoke_docs, None)

    model_inputs_with_image = build_model_inputs(
        processor,
        messages_with_image,
        first_screen_image_path,
        "cpu",
    )
    model_inputs_without_image = build_model_inputs(
        processor,
        messages_without_image,
        None,
        "cpu",
    )

    model_input_keys = sorted(model_inputs_with_image.keys())
    vision_like_keys = [
        key
        for key in model_input_keys
        if ("image" in key.lower()) or ("pixel" in key.lower()) or ("vision" in key.lower())
    ]
    token_count_with_image = int(model_inputs_with_image["input_ids"].shape[-1])
    token_count_without_image = int(model_inputs_without_image["input_ids"].shape[-1])

    print("[SMOKE] Image input smoke test")
    print(f"[SMOKE] Program: {PROGRAM_NAME}")
    print(f"[SMOKE] Example index: {smoke_example_index}")
    print(f"[SMOKE] Task id: {task_id}")
    print(f"[SMOKE] first_screen_image_path: {first_screen_image_path}")
    print(f"[SMOKE] first_screen_image_exists: {image_exists}")
    print("[SMOKE] model_class: AutoModelForImageTextToText (configured)")
    print(f"[SMOKE] processor_class: {processor.__class__.__name__}")
    print(f"[SMOKE] model_input_keys: {model_input_keys}")
    print(f"[SMOKE] vision_like_input_keys: {vision_like_keys}")
    print(
        f"[SMOKE] token_count_with_image_path={token_count_with_image}, "
        f"token_count_without_image_path={token_count_without_image}"
    )

    if vision_like_keys:
        print("[SMOKE][RESULT] PASS: Vision-like tensor keys detected in model inputs.")
        return 0

    print("[SMOKE][RESULT] FAIL: No vision-like tensor keys detected.")
    print(
        "[SMOKE][DETAIL] Current pipeline passes image path text in prompt, "
        "but does not pass image pixels/tensors to the model."
    )
    return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate local inputs without loading models or writing output.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Replace an existing output directory after successful generation.")
    parser.add_argument(
        "--smoke_test_image",
        action="store_true",
        help=(
            "Run a quick check to verify whether image data is actually passed "
            "as model input tensors."
        ),
    )
    parser.add_argument(
        "--smoke_example_index",
        type=int,
        default=0,
        help="Example index to use for --smoke_test_image.",
    )
    parser.add_argument(
        "--max_examples",
        type=int,
        default=None,
        help="Process only the first N examples for a quick real-run check.",
    )
    args = parser.parse_args()

    if args.smoke_test_image:
        raise SystemExit(run_image_input_smoke_test(args.smoke_example_index))

    manual_path = Path(MANUAL_PATH).resolve()
    source_root = Path(EVALUATION_EXAMPLES_ROOT).resolve()
    output_root = Path(OUTPUT_ROOT).resolve()
    first_image_root = Path(FIRST_IMAGE_ROOT).resolve()
    examples_dir = source_root / "examples" / PROGRAM_NAME
    embed_device_num = EMBED_DEVICE_NUM
    generation_device_nums = GENERATION_DEVICE_NUMS
    k = K

    if not examples_dir.exists():
        raise FileNotFoundError(f"Examples directory not found: {examples_dir}")
    # Never delete source data, code, manuals, or screenshot inputs via an output override.
    protected = [source_root, Path(__file__).resolve().parent, manual_path, first_image_root]
    if any(output_root == path or output_root in path.parents for path in protected):
        raise ValueError("Output must not contain source data, code, manual, or screenshots.")
    if source_root in output_root.parents:
        raise ValueError("Output must be outside the source task directory.")
    if output_root.exists() and not args.overwrite and not args.dry_run:
        raise FileExistsError(f"Output already exists: {output_root}; choose a new path or use --overwrite")
    if not generation_device_nums:
        raise ValueError("GENERATION_DEVICE_NUMS must contain at least one GPU id.")

    manual_sections = load_manual(manual_path)
    manual_sections_by_id = {
        section["section_id"]: section for section in manual_sections
    }
    example_items = load_example_items(examples_dir)
    if args.max_examples is not None:
        if args.max_examples <= 0:
            raise ValueError("--max_examples must be a positive integer.")
        example_items = example_items[: args.max_examples]
        print(f"[INFO] Limiting examples to {len(example_items)} item(s) for this run.")
    first_screen_image_map = build_first_screen_image_map(first_image_root, PROGRAM_NAME)

    if not manual_sections or not example_items:
        raise ValueError("Manual sections and task examples must not be empty.")
    if args.dry_run:
        matched = sum(item.get("id") in first_screen_image_map for item in example_items)
        print(f"[DRY RUN] program={PROGRAM_NAME}, sections={len(manual_sections)}, tasks={len(example_items)}, screenshots={matched}")
        print("[DRY RUN] Inputs validated; no models loaded and no output written.")
        return

    import torch

    print("[INFO] Loading embedding model...")
    embed_model = load_embed_model(embed_device_num)
    print("[INFO] Building vector store...")
    vectorstore = get_vectorstore(manual_sections, embed_model)

    print("[INFO] Preparing retrieval results...")
    jobs = prepare_generation_jobs(
        example_items,
        vectorstore,
        manual_sections_by_id,
        k,
        first_screen_image_map,
    )
    # FAISS keeps the embedding object as embedding_function, so both references
    # must be released before loading the sharded generation model.
    del vectorstore
    del embed_model
    gc.collect()
    with torch.cuda.device(embed_device_num):
        torch.cuda.empty_cache()

    print(
        "[INFO] Loading one generation model sharded across GPUs: "
        f"{generation_device_nums}"
    )
    indexed_relevant_procedures = generate_relevant_procedures(
        generation_device_nums,
        jobs,
    )

    indexed_relevant_procedures.sort(key=lambda item: item[0])
    relevant_procedures = [procedure for _, procedure in indexed_relevant_procedures]
    retrieved_page_ranges = [page_ranges for _, _, _, page_ranges, _ in jobs]
    first_screen_image_paths = [image_path for _, _, _, _, image_path in jobs]

    results = attach_relevant_procedures(
        example_items,
        relevant_procedures,
        retrieved_page_ranges,
        first_screen_image_paths,
    )
    referenced_paths = collect_eval_relative_paths(results)
    output_reference = Path(os.path.relpath(output_root, source_root.parent)).as_posix()
    augmented_examples = build_augmented_examples(results, output_reference)

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    write_augmented_examples(
        augmented_examples,
        output_root,
        PROGRAM_NAME,
    )
    copy_metadata_files(
        source_root,
        output_root,
        PROGRAM_NAME,
        {item["id"] for item in augmented_examples},
    )
    copy_support_files(referenced_paths, source_root, output_root)

    print(f"[INFO] Saved {len(augmented_examples)} examples to {output_root / 'examples' / PROGRAM_NAME}")
    print(f"[INFO] Copied metadata files under {output_root}")


if __name__ == "__main__":
    main()
