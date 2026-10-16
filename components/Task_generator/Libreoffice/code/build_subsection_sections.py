import argparse
import json
import re
from pathlib import Path
from typing import Any
from typing import Optional

from config.config_write import PROGRAM_DIR, SECTIONS_JSON_PATH


DEFAULT_OUTPUT_PATH = PROGRAM_DIR / "section_subsections.json"

PAGE_FOOTER_RE = re.compile(
    r"^(?:\d+\s*\|\s*.*|.*\|\s*\d+|Chapter \d+, .* \| \d+|Appendix [A-Z], .* \| \d+)$"
)
FIGURE_TABLE_RE = re.compile(r"^(?:Figure|Table)\s+\d+[: ]", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"^(?:[-•]|[0-9]+[.)]|[a-zA-Z][.)])\s+")
HEADING_PREFIX_RE = re.compile(
    r"^(?:Figure|Table|Chapter|Appendix|Contents|Copyright)\b",
    re.IGNORECASE,
)
SHORT_LABEL_BLOCKLIST = {
    "note",
    "tip",
    "caution",
    "warning",
    "important",
    "notes",
    "tips",
}
EXACT_HEADING_BLOCKLIST = {
    "Command Action",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split section.json into finer-grained subsection units."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=SECTIONS_JSON_PATH,
        help="Path to an existing section.json file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to write the refined section JSON.",
    )
    parser.add_argument(
        "--min-body-lines",
        type=int,
        default=2,
        help="Minimum number of non-empty lines required under a detected subheading.",
    )
    parser.add_argument(
        "--min-intro-lines",
        type=int,
        default=3,
        help="Minimum number of non-empty lines required to keep intro text as an Overview subsection.",
    )
    return parser.parse_args()


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_page_artifact(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if PAGE_FOOTER_RE.match(stripped):
        return True
    if re.fullmatch(r"\d+", stripped):
        return True
    return False


def clean_lines(text: str) -> list[str]:
    cleaned: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned.append("")
            continue
        if is_page_artifact(line):
            cleaned.append("")
            continue
        cleaned.append(normalize_spaces(line))
    return cleaned


def find_line_index(lines: list[str], target: str) -> Optional[int]:
    normalized_target = normalize_spaces(target)
    for index, line in enumerate(lines):
        if normalize_spaces(line) == normalized_target:
            return index
    return None


def trim_to_section_window(
    lines: list[str],
    current_title: str,
    next_title: Optional[str],
) -> list[str]:
    start_index = find_line_index(lines, current_title)
    if start_index is not None:
        lines = lines[start_index:]

    if next_title:
        end_index = find_line_index(lines[1:], next_title)
        if end_index is not None:
            lines = lines[: end_index + 1]

    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def non_empty_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.strip()]


def is_heading_like(line: str, next_line: Optional[str], current_title: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if normalize_spaces(stripped) == normalize_spaces(current_title):
        return False
    if stripped.lower() in SHORT_LABEL_BLOCKLIST:
        return False
    if stripped in EXACT_HEADING_BLOCKLIST:
        return False
    if HEADING_PREFIX_RE.match(stripped):
        return False
    if FIGURE_TABLE_RE.match(stripped):
        return False
    if LIST_ITEM_RE.match(stripped):
        return False
    if stripped.endswith("."):
        return False
    if len(stripped) < 3 or len(stripped) > 72:
        return False

    words = stripped.split()
    if len(words) > 9:
        return False

    alpha_chars = sum(char.isalpha() for char in stripped)
    if alpha_chars < max(3, len(stripped) // 3):
        return False

    lowered_words = [word.strip("()[],:;") for word in words]
    if next_line is None or not next_line.strip():
        return False
    if FIGURE_TABLE_RE.match(next_line.strip()):
        return False
    if len(words) <= 4 and stripped[0].isupper() and len(next_line.strip()) >= 30:
        return True

    capitalized = sum(
        1
        for word in lowered_words
        if word and (word[0].isupper() or word.lower() in {"and", "or", "of", "for", "to", "in", "on", "with"})
    )
    if capitalized / max(1, len(lowered_words)) < 0.30:
        return False

    return True


def collect_heading_ranges(
    lines: list[str],
    current_title: str,
    min_body_lines: int,
) -> list[tuple[str, int, int]]:
    candidates: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        next_line = None
        for probe in lines[index + 1 :]:
            if probe.strip():
                next_line = probe
                break
        if is_heading_like(line, next_line, current_title):
            candidates.append((line, index))

    heading_ranges: list[tuple[str, int, int]] = []
    for candidate_index, (heading, start_index) in enumerate(candidates):
        end_index = (
            candidates[candidate_index + 1][1]
            if candidate_index + 1 < len(candidates)
            else len(lines)
        )
        body = non_empty_lines(lines[start_index + 1 : end_index])
        if len(body) < min_body_lines:
            continue
        heading_ranges.append((heading, start_index, end_index))
    return heading_ranges


def build_child_section(
    parent: dict[str, Any],
    title: str,
    segment_lines: list[str],
    subsection_index: int,
) -> dict[str, Any]:
    normalized_title = title.rstrip(":").strip()
    child = dict(parent)
    child["title"] = normalized_title
    child["level"] = int(parent.get("level", 0)) + 1
    child["path"] = list(parent.get("path", [])) + [normalized_title]
    child["text"] = "\n".join(segment_lines).strip()
    child["source_section_title"] = parent.get("title")
    child["source_section_path"] = list(parent.get("path", []))
    child["subsection_index"] = subsection_index
    child["split_source"] = "subheading"
    return child


def split_section(
    section: dict[str, Any],
    next_section: Optional[dict[str, Any]],
    min_body_lines: int,
    min_intro_lines: int,
) -> list[dict[str, Any]]:
    raw_text = section.get("text", "") or ""
    lines = clean_lines(raw_text)
    if not non_empty_lines(lines):
        return [section]

    next_title = next_section.get("title") if next_section else None
    windowed_lines = trim_to_section_window(lines, section.get("title", ""), next_title)
    if not non_empty_lines(windowed_lines):
        return [section]

    heading_ranges = collect_heading_ranges(
        lines=windowed_lines,
        current_title=section.get("title", ""),
        min_body_lines=min_body_lines,
    )
    if not heading_ranges:
        updated = dict(section)
        updated["text"] = "\n".join(windowed_lines).strip()
        return [updated]

    refined_sections: list[dict[str, Any]] = []
    first_heading_start = heading_ranges[0][1]
    intro_lines = non_empty_lines(windowed_lines[:first_heading_start])
    subsection_index = 0

    if len(intro_lines) >= min_intro_lines:
        refined_sections.append(
            build_child_section(
                parent=section,
                title="Overview",
                segment_lines=intro_lines,
                subsection_index=subsection_index,
            )
        )
        subsection_index += 1

    for heading, start_index, end_index in heading_ranges:
        segment_lines = non_empty_lines(windowed_lines[start_index:end_index])
        if len(segment_lines) <= 1:
            continue
        refined_sections.append(
            build_child_section(
                parent=section,
                title=heading,
                segment_lines=segment_lines,
                subsection_index=subsection_index,
            )
        )
        subsection_index += 1

    return refined_sections or [section]


def refine_sections(
    sections: list[dict[str, Any]],
    min_body_lines: int,
    min_intro_lines: int,
) -> list[dict[str, Any]]:
    refined: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        next_section = sections[index + 1] if index + 1 < len(sections) else None
        refined.extend(
            split_section(
                section=section,
                next_section=next_section,
                min_body_lines=min_body_lines,
                min_intro_lines=min_intro_lines,
            )
        )
    return refined


def write_json(data: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def main() -> None:
    args = parse_args()
    with args.input.open("r", encoding="utf-8") as file:
        sections = json.load(file)

    refined_sections = refine_sections(
        sections=sections,
        min_body_lines=args.min_body_lines,
        min_intro_lines=args.min_intro_lines,
    )
    write_json(refined_sections, args.output)

    print(
        f"saved: {args.output} "
        f"({len(refined_sections)} items from {len(sections)} original sections)"
    )


if __name__ == "__main__":
    main()
