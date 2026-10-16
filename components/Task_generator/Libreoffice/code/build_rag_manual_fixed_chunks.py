import argparse
import json
import math
import re
from pathlib import Path
from typing import Any
from typing import Optional

import pdfplumber

from config.config_impress import PDF_PATH, PROGRAM_DIR


DEFAULT_OUTPUT_DIR = PROGRAM_DIR / "rag_manual_fixed_chunks"
SPACE_RE = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build fixed-size RAG chunks directly from the Impress manual PDF."
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=PDF_PATH,
        help="Path to the source PDF manual.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where fixed-size chunk docs will be written.",
    )
    parser.add_argument(
        "--target-chars",
        type=int,
        default=1800,
        help="Target character budget per chunk.",
    )
    parser.add_argument(
        "--overlap-chars",
        type=int,
        default=250,
        help="Character overlap between adjacent chunks.",
    )
    parser.add_argument(
        "--min-page",
        type=int,
        default=1,
        help="First page number to include.",
    )
    return parser.parse_args()


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def dump_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_page_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line.strip())
    return cleaned.strip()


def load_pdf_pages(pdf_path: Path, min_page: int) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            if page.page_number < min_page:
                continue
            text = normalize_page_text(page.extract_text(layout=False) or "")
            if not text:
                continue
            pages.append(
                {
                    "page": page.page_number,
                    "text": text,
                }
            )
    return pages


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def compact_preview(text: str, limit: int = 160) -> str:
    compact = SPACE_RE.sub(" ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def build_full_text(pages: list[dict[str, Any]]) -> tuple[str, list[dict[str, int]]]:
    parts: list[str] = []
    page_spans: list[dict[str, int]] = []
    cursor = 0

    for index, page in enumerate(pages):
        if index > 0:
            parts.append("\n\n")
            cursor += 2

        start = cursor
        parts.append(page["text"])
        cursor += len(page["text"])
        end = cursor
        page_spans.append(
            {
                "page": page["page"],
                "start": start,
                "end": end,
            }
        )

    return "".join(parts), page_spans


def find_page_range(
    span_start: int,
    span_end: int,
    page_spans: list[dict[str, int]],
) -> tuple[Optional[int], Optional[int]]:
    covered_pages = []
    for page_span in page_spans:
        if page_span["end"] <= span_start:
            continue
        if page_span["start"] >= span_end:
            break
        covered_pages.append(page_span["page"])

    if not covered_pages:
        return None, None
    return covered_pages[0], covered_pages[-1]


def next_boundary(text: str, target_end: int) -> int:
    if target_end >= len(text):
        return len(text)

    for boundary in ("\n\n", "\n", ". ", "? ", "! "):
        pos = text.find(boundary, target_end)
        if pos != -1 and pos - target_end <= 200:
            return pos + len(boundary.strip())

    return min(len(text), target_end)


def previous_boundary(text: str, target_start: int) -> int:
    if target_start <= 0:
        return 0

    window_start = max(0, target_start - 200)
    window = text[window_start:target_start]
    candidates = []
    for boundary in ("\n\n", "\n", ". ", "? ", "! "):
        pos = window.rfind(boundary)
        if pos != -1:
            candidates.append(window_start + pos + len(boundary))

    if candidates:
        return max(candidates)
    return target_start


def chunk_text(
    full_text: str,
    page_spans: list[dict[str, int]],
    target_chars: int,
    overlap_chars: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    start = 0
    chunk_index = 0

    while start < len(full_text):
        raw_end = min(len(full_text), start + target_chars)
        end = next_boundary(full_text, raw_end)
        text = full_text[start:end].strip()
        if not text:
            break

        start_page, end_page = find_page_range(start, end, page_spans)
        chunks.append(
            {
                "doc_id": f"impress-manual-{chunk_index:04d}",
                "source": "LibreOffice Impress Guide 7.6",
                "program": "LibreOffice Impress",
                "chunk_index": chunk_index,
                "start_char": start,
                "end_char": end,
                "char_count": len(text),
                "estimated_tokens": estimate_tokens(text),
                "start_page": start_page,
                "end_page": end_page,
                "text": text,
                "preview": compact_preview(text),
            }
        )
        chunk_index += 1

        if end >= len(full_text):
            break

        next_start = max(0, end - overlap_chars)
        start = previous_boundary(full_text, next_start)
        if start >= end:
            start = end

    return chunks


def build_manifest(
    pdf_path: Path,
    output_dir: Path,
    pages: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    target_chars: int,
    overlap_chars: int,
    min_page: int,
) -> dict[str, Any]:
    return {
        "pdf_path": str(pdf_path),
        "output_dir": str(output_dir),
        "page_count": len(pages),
        "chunk_count": len(chunks),
        "target_chars": target_chars,
        "overlap_chars": overlap_chars,
        "min_page": min_page,
        "first_page": pages[0]["page"] if pages else None,
        "last_page": pages[-1]["page"] if pages else None,
        "sample_ranges": [
            {
                "doc_id": chunk["doc_id"],
                "start_page": chunk["start_page"],
                "end_page": chunk["end_page"],
                "char_count": chunk["char_count"],
            }
            for chunk in chunks[:20]
        ],
    }


def main() -> None:
    args = parse_args()
    pages = load_pdf_pages(args.pdf, args.min_page)
    full_text, page_spans = build_full_text(pages)
    chunks = chunk_text(
        full_text=full_text,
        page_spans=page_spans,
        target_chars=args.target_chars,
        overlap_chars=args.overlap_chars,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    dump_json(args.output_dir / "documents.json", chunks)
    dump_jsonl(args.output_dir / "documents.jsonl", chunks)
    dump_json(
        args.output_dir / "manifest.json",
        build_manifest(
            pdf_path=args.pdf,
            output_dir=args.output_dir,
            pages=pages,
            chunks=chunks,
            target_chars=args.target_chars,
            overlap_chars=args.overlap_chars,
            min_page=args.min_page,
        ),
    )

    print(
        f"saved: {args.output_dir} "
        f"({len(chunks)} fixed-size chunks from {len(pages)} pages)"
    )


if __name__ == "__main__":
    main()
