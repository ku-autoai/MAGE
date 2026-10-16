import os
from pathlib import Path


BASE_FOLDER = Path(os.environ.get("LIBREOFFICE_TASKGEN_ROOT", Path(__file__).resolve().parents[2]))
PROGRAM_NAME = "Impress"
PDF_PATH = BASE_FOLDER / "pdf" / "IG76-ImpressGuide.pdf"
""

PROGRAM_DIR = BASE_FOLDER / PROGRAM_NAME
IMAGE_DIR = PROGRAM_DIR / "images"
SECTIONS_JSON_PATH = PROGRAM_DIR / "section.json"
FILTERED_SECTIONS_JSON_PATH = PROGRAM_DIR / "section_filtered.json"
TASKS_JSON_PATH = PROGRAM_DIR / "tasks_section.json"

MIN_START_PAGE = 0
DROP_PATH_TITLES = {"Copyright"}
# This filter matches the first entry in each section's PDF outline path (`path[0]`).
# Only chapters that should be dropped wholesale belong here.
EXCLUDE_TOP_LEVEL_CHAPTERS = ["Preface",
                              "Chapter 1, Introducing Impress",
                              "Chapter 7, OLE, Spreadsheets, Charts, and Other Objects",
                              "Chapter 8, Adding and Formatting Slides, Notes, Comments, and Handouts",
                              "Chapter 10, Saving Slide Shows, Printing, Emailing, and Exporting",
                              "Chapter 12, User Interface Variants",
                              "Appendix A, Keyboard Shortcuts",
                              "Appendix B, Toolbars"]

MODEL_NAME = "gpt-5.4-mini"
API_KEY = os.environ.get("OPENAI_API_KEY")
START_INDEX = 0
END_INDEX = None

N_SAMPLES = 60
