import os
from pathlib import Path


BASE_FOLDER = Path(os.environ.get("LIBREOFFICE_TASKGEN_ROOT", Path(__file__).resolve().parents[2]))
PROGRAM_NAME = "Writer"
PDF_PATH = BASE_FOLDER / "pdf" / "WG73-WriterGuide.pdf"

PROGRAM_DIR = BASE_FOLDER / PROGRAM_NAME
IMAGE_DIR = PROGRAM_DIR / "images"
SECTIONS_JSON_PATH = PROGRAM_DIR / "section.json"
FILTERED_SECTIONS_JSON_PATH = PROGRAM_DIR / "section_filtered_sampled.json"
TASKS_JSON_PATH = PROGRAM_DIR / "tasks_subsection.json"

MIN_START_PAGE = 0
DROP_PATH_TITLES = {"Copyright"}
# This filter matches the first entry in each section's PDF outline path (`path[0]`).
# Only chapters that should be dropped wholesale belong here.
EXCLUDE_TOP_LEVEL_CHAPTERS = [
    "Preface",
    "Chapter 1, Introducing Writer",
    "Chapter 6, Formatting Pages: Advanced",
    "Chapter 8, Introduction to Styles",
    "Chapter 9, Working with Styles",
    "Chapter 10, Working with Templates",
    "Chapter 12, Lists",
    "Chapter 14, Mail Merge",
    "Chapter 16, Master Documents",
    "Chapter 18, Forms",
    "Chapter 19, Spreadsheets, Charts, Other Objects",
    "Chapter 21, User Interface Variants",
    # Optional (CSV decision = conditional):
    # "Chapter 1, Introducing Writer",
    # "Chapter 3, Working with Text: Advanced",
]

MODEL_NAME = "gpt-5.4"
API_KEY = os.environ.get("OPENAI_API_KEY")
START_INDEX = 0
END_INDEX = None

N_SAMPLES = 60
