import ast
import time
import pyautogui
import subprocess
import difflib
from typing import List, Dict, Optional, Union, Tuple
# import win32com.client

class ACI:
    def __init__(self):
        self.notes: List[str] = []


def agent_action(func):
    func.is_agent_action = True
    return func


UBUNTU_APP_SETUP = """import subprocess;
import difflib;
import pyautogui;
pyautogui.press('escape');
time.sleep(0.5);
output = subprocess.check_output(['wmctrl', '-lx']);
output = output.decode('utf-8').splitlines();
window_titles = [line.split(None, 4)[2] for line in output];
closest_matches = difflib.get_close_matches('APP_NAME', window_titles, n=1, cutoff=0.1);
if closest_matches:
    closest_match = closest_matches[0];
    for line in output:
        if closest_match in line:
            window_id = line.split()[0];
            break;
subprocess.run(['wmctrl', '-ia', window_id]);
subprocess.run(['wmctrl', '-ir', window_id, '-b', 'add,maximized_vert,maximized_horz'])
"""


class OSWorldACI(ACI):
    def __init__(self, platform: str):
        super().__init__()
        self.platform = platform.lower()
        self.returned_info = None

    # -----------------------
    # === Basic Mouse Ops ===
    # -----------------------
    @agent_action
    def click(self, element_description: str, num_clicks: int = 1, button_type: str = "left", hold_keys: List[str] = []):
        """Click on the element."""

        x, y = ast.literal_eval(element_description)
        
        print(x, y)
        print("click")

        for k in hold_keys:
            pyautogui.keyDown(k)
        pyautogui.click(x=x, y=y, clicks=num_clicks, button=button_type)
        for k in hold_keys:
            pyautogui.keyUp(k)
        return f"Clicked at ({x},{y})"

    @agent_action
    def drag_and_drop(self, starting_description: str, ending_description: str, hold_keys: List = []):
        """Drag from starting to ending coordinates."""
        x1, y1 = ast.literal_eval(starting_description)
        x2, y2 = ast.literal_eval(ending_description)

        print(x1, y1)
        print(x2, y2)
        print("drag_and_drop")

        for k in hold_keys:
            pyautogui.keyDown(k)
        pyautogui.moveTo(x1, y1)
        pyautogui.dragTo(x2, y2, duration=1.0)
        pyautogui.mouseUp()
        for k in hold_keys:
            pyautogui.keyUp(k)
        return f"Dragged from ({x1},{y1}) to ({x2},{y2})"

    @agent_action
    def scroll(self, element_description: str, clicks: int, shift: bool = False):
        """Scroll vertically or horizontally."""
        x, y = ast.literal_eval(element_description)
        pyautogui.moveTo(x, y)
        pyautogui.click(x, y)
        time.sleep(0.2)
        if shift:
            pyautogui.hscroll(clicks)
        else:
            pyautogui.vscroll(clicks)
        return f"Scrolled {clicks} clicks"

    # -----------------------
    # === Keyboard Control ===
    # -----------------------
    @agent_action
    def type(self, element_description: Optional[str] = None, text: str = "", overwrite: bool = False, enter: bool = False):
        """Type text into a specific element."""
        if element_description:
            try:
                x, y = ast.literal_eval(element_description)
                pyautogui.click(x, y)
                time.sleep(0.2)
            except Exception:
                pass
        if overwrite:
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")
        pyautogui.write(text)
        if enter:
            pyautogui.press("enter")
        return f"Typed '{text}'"

    @agent_action
    def hotkey(self, keys: List[str]):
        """Press a hotkey combination."""
        pyautogui.hotkey(*keys)
        return f"Pressed hotkey {keys}"

    @agent_action
    def hold_and_press(self, hold_keys: List[str], press_keys: List[str]):
        """Hold a list of keys and press a list of keys."""
        for k in hold_keys:
            pyautogui.keyDown(k)
        for p in press_keys:
            pyautogui.press(p)
        for k in hold_keys:
            pyautogui.keyUp(k)
        return f"Held {hold_keys} and pressed {press_keys}"

    # -----------------------
    # === Application Ops ===
    # -----------------------
    @agent_action
    def open(self, app_or_filename: str):
        """Open any application or file."""
        if self.platform == "windows":
            pyautogui.hotkey("win")
            time.sleep(0.5)
            pyautogui.write(app_or_filename)
            pyautogui.press("enter")
        elif self.platform == "linux":
            pyautogui.hotkey("win")
            time.sleep(0.5)
            pyautogui.typewrite(app_or_filename)
            pyautogui.press("enter")
        else:
            pyautogui.hotkey("command", "space")
            pyautogui.typewrite(app_or_filename)
            pyautogui.press("enter")
        return f"Opened {app_or_filename}"

    @agent_action
    def switch_applications(self, app_code: str):
        """Switch to another open application."""
        if self.platform == "linux":
            cmd = UBUNTU_APP_SETUP.replace("APP_NAME", app_code)
            exec(cmd)
        elif self.platform == "windows":
            pyautogui.hotkey("alt", "tab")
        else:
            pyautogui.hotkey("command", "tab")
        return f"Switched to {app_code}"

    # -----------------------
    # === Spreadsheet Ops ===
    # -----------------------
    # @agent_action
    # def set_cell_values(self, cell_values: Dict[str, Union[str, float, int, bool]], app_name: str, sheet_name: str):
    #     """
    #     Set values into a spreadsheet (LibreOffice/Excel).
    #     """
    #     try:
    #         xl = win32com.client.Dispatch("Excel.Application")
    #         time.sleep(1)
    #         workbooks = xl.Workbooks
    #         print("Currently open workbook list:")
    #         for i in range(1, workbooks.Count + 1):
    #             try:
    #                 print(f"  {i}. {workbooks.Item(i).Name}")
    #             except Exception:
    #                 pass

    #     except Exception as e:
    #         print("Excel is not running or win32com is unavailable:", e)
    #         pass
    
    #     try:
    #         wb = xl.Workbooks(app_name)
    #         ws = wb.Worksheets(sheet_name)
    #         for cell_ref, value in cell_values.items():
    #             ws.Range(cell_ref).Value = value

    #         return f"Set cell values in {app_name}/{sheet_name}"
    #     except Exception:
    #         return "set_cell_values not supported on this OS"

    # -----------------------
    # === Text Utilities ===
    # -----------------------
    @agent_action
    def highlight_text_span(self, starting_phrase: str, ending_phrase: str):
        """Highlight text between two phrases."""
        # The actual implementation depends on the app, but simulate it with a simple ctrl+f search.
        pyautogui.hotkey("ctrl", "f")
        pyautogui.write(starting_phrase)
        time.sleep(0.5)
        pyautogui.press("enter")
        return f"Highlighted text between '{starting_phrase}' and '{ending_phrase}'"

    # -----------------------
    # === Flow Control ===
    # -----------------------
    @agent_action
    def wait(self, t: float):
        time.sleep(t)
        return f"Waited {t}s"

    @agent_action
    def done(self, return_value: Optional[Union[Dict, str, List, Tuple, int, float, bool]] = None):
        self.returned_info = return_value
        return "DONE"

    @agent_action
    def fail(self):
        return "FAIL"
