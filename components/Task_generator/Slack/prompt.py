instruciton_gen_prompt = """
You are an expert at generating GUI-based practice tasks for AI agents.

You will be given:
1. Program name
2. One section of manual text (may span multiple pages)
3. One or more images from the manual section (provided by the user)

Your task is to generate executable GUI practice tasks based strictly on the given manual.

Each task must be output as an Instruction pair with:
- Setup instruction (optional)
- Main instruction (required)

Each instruction must contain:
- task: a short sentence describing the goal
- steps: a list of concrete GUI actions

Rules:

1. You must generate 1 tasks.

2. The task must produce a visible result on the screen.
   ❌ Do NOT generate tasks such as:
   - opening menus only
   - checking a feature
   - saving a file
   - exploring UI
   The result must be visually observable (e.g., hidden columns, chart appears, formatted text appears).

3. The starting screen is always:
   → The program is freshly opened with a blank/default screen.
   → No files, no tables, no pre-existing content.

4. The GUI agent must NEVER be asked to make subjective or free choices.
   ❌ Do NOT generate steps such as:
   - "Choose any color"
   - "Select a preferred style"
   - "Pick an option you like"
   - "Apply a random format"
   All actions must be deterministic and explicitly specified.

5. Output format (JSON list only):

{
  "setup_task": "...",
  "setup_steps": [...],
  "main_task": "...",
  "main_steps": [...],
  "id": number
}

6. Setup instruction:
- Setup is ONLY for creating or preparing data or objects required by the main task.
- If the main task needs any pre-existing value, text, table, or object, it MUST be created in setup_steps.
- Main steps must NEVER include data creation actions such as typing initial values or creating tables.
- If the main task can be done from a blank screen without any preparation, leave setup_task as an empty string and setup_steps as an empty list.

7. Main instruction:
- Main steps must ONLY apply the manual feature to the prepared data.
- Main steps must NOT include:
  - entering initial numbers or text
  - creating tables
  - preparing sample data
- Main task must be a concrete exercise reconstructed from the manual.

8. If tables or sample data are required in setup:
   - You cannot rely only on images.
   - You must describe exactly how to create the table or data in text steps.

9. Steps must:
   - Be atomic GUI actions (click, type, select, press keys).
   - Be ordered.
   - Not include explanations.
   - Not mention “manual” or “images”.

10. Do not invent features not mentioned in the provided manual.

11. Section-based multimodal input handling:
   - The text is section-level, not single-page.
   - Multiple images may be provided for the same section.
   - Use all provided images as supporting context when they are relevant.
   - If text and images conflict, prioritize the manual text.
   - Do not assume hidden UI details not visible in text or images.

12. Output must be ONLY valid JSON.
   - No markdown
   - No explanation
   - No extra text

Here are examples of correct output:

[
  {
    "setup_task": "(Setup) Create sample data for hiding multiple columns with a keyboard shortcut",
    "setup_steps": [
      "Enter the headers “Employee”, “Age”, “Department”, “Salary”, “Start Date”, “Status” in the first row.",
      "Fill at least three rows with sample values under each header."
    ],
    "main_task": "Hide the “Age” and “Department” columns using the Ctrl + 0 shortcut",
    "main_steps": [
      "Click the column header “Age”.",
      "Drag to the right until the “Department” column header is also selected.",
      "Press Ctrl and the 0 key at the same time."
    ],
    "id": 0
  },
  {
    "setup_task": "(Setup) Create sample data for hiding a column by setting width to zero",
    "setup_steps": [
      "Enter headers “Employee”, “Age”, “Department”, “Salary”, “Start Date”, “Status” across the first row.",
      "Populate at least three rows with sample data underneath the headers."
    ],
    "main_task": "Hide the “Salary” column by setting its width to 0",
    "main_steps": [
      "Click the column header “Salary”.",
      "Right-click the highlighted header.",
      "Click Column Width.",
      "In the Column Width box, type 0.",
      "Click OK."
    ],
    "id": 1
  }
]

Now generate 1 or 2 Instruction pairs using the following input.
"""
