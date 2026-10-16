import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from config.config_impress import PROGRAM_DIR


DEFAULT_INPUT_PATH = PROGRAM_DIR / "section_subsections.json"
DEFAULT_OUTPUT_DIR = PROGRAM_DIR / "rag_chunks"

PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
SPACE_RE = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build chunk-level manual documents for RAG from Impress section data."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to section-level JSON. Defaults to section_subsections.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where chunk documents and metadata will be written.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=1800,
        help="Target maximum characters per chunk before starting a new chunk.",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=400,
        help="Minimum chunk size to avoid over-fragmenting short content.",
    )
    parser.add_argument(
        "--overlap-paragraphs",
        type=int,
        default=1,
        help="Number of trailing paragraphs to carry into the next chunk.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def dump_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def split_into_paragraphs(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    paragraphs = []
    for piece in PARAGRAPH_SPLIT_RE.split(normalized):
        compact = piece.strip()
        if not compact:
            continue
        paragraphs.append(compact)

    if paragraphs:
        return paragraphs

    fallback_lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    return fallback_lines


def compact_preview(text: str, limit: int = 160) -> str:
    compact = SPACE_RE.sub(" ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def build_chunk_text(paragraphs: list[str]) -> str:
    return "\n\n".join(paragraphs).strip()


def chunk_paragraphs(
    paragraphs: list[str],
    max_chars: int,
    min_chars: int,
    overlap_paragraphs: int,
) -> list[list[str]]:
    if not paragraphs:
        return []

    chunks: list[list[str]] = []
    current: list[str] = []

    for paragraph in paragraphs:
        if not current:
            current = [paragraph]
            continue

        candidate = build_chunk_text(current + [paragraph])
        if len(candidate) <= max_chars or len(build_chunk_text(current)) < min_chars:
            current.append(paragraph)
            continue

        chunks.append(current)
        if overlap_paragraphs > 0:
            current = current[-overlap_paragraphs:] + [paragraph]
        else:
            current = [paragraph]

    if current:
        if chunks and len(build_chunk_text(current)) < min_chars:
            chunks[-1] = chunks[-1] + current
        else:
            chunks.append(current)

    return chunks


def build_documents(
    sections: list[dict[str, Any]],
    max_chars: int,
    min_chars: int,
    overlap_paragraphs: int,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []

    for section_index, section in enumerate(sections):
        paragraphs = split_into_paragraphs(section.get("text", "") or "")
        paragraph_chunks = chunk_paragraphs(
            paragraphs=paragraphs,
            max_chars=max_chars,
            min_chars=min_chars,
            overlap_paragraphs=overlap_paragraphs,
        )

        for chunk_index, chunk_paragraphs_list in enumerate(paragraph_chunks):
            chunk_text = build_chunk_text(chunk_paragraphs_list)
            title = section.get("title") or f"section_{section_index}"
            path = list(section.get("path", []))
            doc_id = f"impress-{section_index:04d}-{chunk_index:03d}"

            documents.append(
                {
                    "doc_id": doc_id,
                    "source": "LibreOffice Impress Guide 7.6",
                    "program": "LibreOffice Impress",
                    "title": title,
                    "path": path,
                    "path_text": " > ".join(path),
                    "level": section.get("level"),
                    "start_page": section.get("start_page"),
                    "end_page": section.get("end_page"),
                    "source_section_index": section_index,
                    "source_section_title": section.get("source_section_title", section.get("title")),
                    "source_section_path": section.get("source_section_path", path[:-1]),
                    "subsection_index": section.get("subsection_index"),
                    "split_source": section.get("split_source", "section"),
                    "chunk_index": chunk_index,
                    "chunk_count_in_section": len(paragraph_chunks),
                    "paragraph_count": len(chunk_paragraphs_list),
                    "char_count": len(chunk_text),
                    "estimated_tokens": estimate_tokens(chunk_text),
                    "text": chunk_text,
                    "preview": compact_preview(chunk_text),
                }
            )

    return documents


def build_manifest(
    input_path: Path,
    output_dir: Path,
    documents: list[dict[str, Any]],
    max_chars: int,
    min_chars: int,
    overlap_paragraphs: int,
) -> dict[str, Any]:
    unique_paths = sorted({doc["path_text"] for doc in documents})
    return {
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "document_count": len(documents),
        "unique_path_count": len(unique_paths),
        "max_chars": max_chars,
        "min_chars": min_chars,
        "overlap_paragraphs": overlap_paragraphs,
        "sample_paths": unique_paths[:20],
    }


def main() -> None:
    args = parse_args()
    sections = load_json(args.input)
    documents = build_documents(
        sections=sections,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        overlap_paragraphs=args.overlap_paragraphs,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    dump_json(args.output_dir / "documents.json", documents)
    dump_jsonl(args.output_dir / "documents.jsonl", documents)
    dump_json(
        args.output_dir / "manifest.json",
        build_manifest(
            input_path=args.input,
            output_dir=args.output_dir,
            documents=documents,
            max_chars=args.max_chars,
            min_chars=args.min_chars,
            overlap_paragraphs=args.overlap_paragraphs,
        ),
    )

    print(
        f"saved: {args.output_dir} "
        f"({len(documents)} chunk documents from {len(sections)} source sections)"
    )


if __name__ == "__main__":
    main()
