import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Optional

import pdfplumber
from pdf2image import convert_from_path
from pypdf import PdfReader
from tqdm import tqdm

from config import (
    DROP_PATH_TITLES,
    EXCLUDE_TOP_LEVEL_CHAPTERS,
    FILTERED_SECTIONS_JSON_PATH,
    IMAGE_DIR,
    MIN_START_PAGE,
    PDF_PATH,
    SECTIONS_JSON_PATH,
)
# from config import EXCLUDE_TOP_LEVEL_CHAPTERS
# from config import FILTERED_SECTIONS_JSON_PATH
# from config import IMAGE_DIR
# from config import MIN_START_PAGE
# from config import PDF_PATH
# from config import SECTIONS_JSON_PATH


@dataclass
class OutlineNode:
    title: str
    level: int
    start_page: Optional[int]
    path: list[str]


def render_pdf_images(pdf_path: Path, image_dir: Path) -> dict[int, str]:
    if image_dir.exists() and any(image_dir.iterdir()):
        existing_image_paths: dict[int, str] = {}
        for image_path in sorted(image_dir.glob("page_*.png")):
            try:
                page_number = int(image_path.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            existing_image_paths[page_number] = str(image_path)
        if existing_image_paths:
            return existing_image_paths

    image_dir.mkdir(parents=True, exist_ok=True)

    images = convert_from_path(str(pdf_path), dpi=300)
    image_paths: dict[int, str] = {}
    for page_number, image in tqdm(
        enumerate(images, start=1),
        total=len(images),
        desc="Rendering PDF pages",
    ):
        image_path = image_dir / f"page_{page_number}.png"
        image.save(image_path, "PNG")
        image_paths[page_number] = str(image_path)

    return image_paths


def extract_pdf_texts(pdf_path: Path) -> dict[int, str]:
    page_texts: dict[int, str] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in tqdm(pdf.pages, total=len(pdf.pages), desc="Extracting page text"):
            page_texts[page.page_number] = page.extract_text(layout=False) or ""
    return page_texts


def walk_outline_items(
    reader: PdfReader,
    items: list[Any],
    level: int,
    path: list[str],
    out: list[OutlineNode],
) -> None:
    last_node_path: Optional[list[str]] = None
    for item in items:
        if isinstance(item, list):
            child_path = last_node_path if last_node_path is not None else path
            walk_outline_items(reader, item, level + 1, child_path, out)
            continue

        title = getattr(item, "title", str(item)).strip()
        try:
            start_page = reader.get_destination_page_number(item) + 1
        except Exception:
            start_page = None

        node_path = path + [title]
        out.append(OutlineNode(title=title, level=level, start_page=start_page, path=node_path))
        last_node_path = node_path


def compute_leaf_sections(
    pdf_path: Path,
    page_texts: dict[int, str],
    page_image_paths: dict[int, str],
) -> list[dict[str, Any]]:
    reader = PdfReader(str(pdf_path))
    flat_nodes: list[OutlineNode] = []
    walk_outline_items(reader, list(reader.outline), level=1, path=[], out=flat_nodes)

    nodes = [node for node in flat_nodes if node.start_page is not None]
    sections: list[dict[str, Any]] = []
    for index, node in tqdm(
        enumerate(nodes),
        total=len(nodes),
        desc="Building leaf sections",
    ):
        next_node = nodes[index + 1] if index + 1 < len(nodes) else None
        is_leaf = next_node is None or next_node.level <= node.level
        if not is_leaf:
            continue

        start_page = int(node.start_page)
        end_page = int(next_node.start_page) if next_node is not None else start_page
        section_pages = list(range(start_page, end_page + 1))
        text_parts = [
            page_texts.get(page_number, "")
            for page_number in section_pages
            if page_texts.get(page_number, "")
        ]
        image_paths = [
            page_image_paths[page_number]
            for page_number in section_pages
            if page_number in page_image_paths
        ]
        sections.append(
            {
                "title": node.title,
                "level": node.level,
                "path": node.path,
                "start_page": start_page,
                "end_page": end_page,
                "next_start_page": next_node.start_page if next_node is not None else None,
                "is_leaf": True,
                "text": "\n\n".join(text_parts).strip(),
                "text_page_count": max(0, end_page - start_page + 1),
                "image_paths": image_paths,
            }
        )
    return sections


def keep_section(section: dict[str, Any]) -> bool:
    if int(section.get("start_page", 0)) < MIN_START_PAGE:
        return False

    path = section.get("path", [])
    if any(title in DROP_PATH_TITLES for title in set(path)):
        return False

    top_level_chapter = path[0] if path else ""
    excluded_top_levels = {chapter.lower() for chapter in EXCLUDE_TOP_LEVEL_CHAPTERS}
    return top_level_chapter.lower() not in excluded_top_levels


def deduplicate_sections_by_text(
    sections: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    seen_texts: set[str] = set()
    deduplicated_sections: list[dict[str, Any]] = []
    duplicate_count = 0

    for section in tqdm(sections, total=len(sections), desc="Deduplicating by text"):
        text = section.get("text", "").strip()
        if text in seen_texts:
            duplicate_count += 1
            continue
        seen_texts.add(text)
        deduplicated_sections.append(section)

    return deduplicated_sections, duplicate_count


def write_json(data: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)



def build_sections(
    pdf_path: Path = PDF_PATH,
    output_path: Path = SECTIONS_JSON_PATH,
    filtered_output_path: Path = FILTERED_SECTIONS_JSON_PATH,
    image_dir: Path = IMAGE_DIR,
) -> tuple[Path, Path, int, int, int, int]:
    page_image_paths = render_pdf_images(pdf_path, image_dir)
    page_texts = extract_pdf_texts(pdf_path)
    sections = compute_leaf_sections(pdf_path, page_texts, page_image_paths)
    deduplicated_sections, section_duplicate_count = deduplicate_sections_by_text(sections)
    filtered_sections = [
        section
        for section in tqdm(
            deduplicated_sections,
            total=len(deduplicated_sections),
            desc="Filtering sections",
        )
        if keep_section(section)
    ]

    write_json(deduplicated_sections, output_path)
    write_json(filtered_sections, filtered_output_path)
    return (
        output_path,
        filtered_output_path,
        len(sections),
        len(deduplicated_sections),
        len(filtered_sections),
        section_duplicate_count,
    )


def main() -> None:
    (
        output_path,
        filtered_output_path,
        before,
        deduplicated_count,
        filtered_count,
        duplicate_count,
    ) = build_sections()
    print(
        f"saved: {output_path} ({deduplicated_count} items, "
        f"{duplicate_count} duplicate texts removed from {before} raw items), "
        f"{filtered_output_path} ({filtered_count} items after filtering)"
    )


if __name__ == "__main__":
    main()
