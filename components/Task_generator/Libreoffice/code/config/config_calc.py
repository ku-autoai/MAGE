import os
from pathlib import Path


BASE_FOLDER = Path(os.environ.get("LIBREOFFICE_TASKGEN_ROOT", Path(__file__).resolve().parents[2]))
PROGRAM_NAME = "calc"
PDF_PATH = BASE_FOLDER / "pdf" / "CG71-CalcGuide.pdf"
""

PROGRAM_DIR = BASE_FOLDER / PROGRAM_NAME
IMAGE_DIR = PROGRAM_DIR / "images"
SECTIONS_JSON_PATH = PROGRAM_DIR / "section.json"
FILTERED_SECTIONS_JSON_PATH = PROGRAM_DIR / "section_filtered.json"
TASKS_JSON_PATH = PROGRAM_DIR / "tasks_section.json"

MIN_START_PAGE = 0
DROP_PATH_TITLES = {"Copyright"}
EXCLUDE_TOP_LEVEL_CHAPTERS = ["Preface",
                              "Chapter 1 Introduction",
                              "Chapter 5 Using Images and Graphics", 
                              "Chapter 9 Data Analysis",
                              "Chapter 11 Sharing and Reviewing Spreadsheets",
                              "Chapter 13 Calc as a Database",
                              "Chapter 14 Setting up and Customizing",
                              "Appendix B Error Codes"]

MODEL_NAME = "gpt-5.4"
API_KEY = os.environ.get("OPENAI_API_KEY")
START_INDEX = 0
END_INDEX = None

N_SAMPLES = 60
