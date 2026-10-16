import socket
import inspect
import pyautogui
import io
import asyncio
import json
import time
import platform
import logging
import os
import signal
import argparse
import subprocess
import shutil
import re
import traceback
# from excel import list_open_workbooks

from pipeline.aci_de import OSWorldACI
from pipeline.util.socket_session import SocketSession

current_platform = platform.system().lower()
CLIENT_ID = os.environ.get("CLIENT_ID")
HOST = os.environ.get("HOST")
PORT = os.environ.get("PORT")
ONCE = False
AUTO_RESET_ON_DONE = True
SETUP_FILE_PATH = os.environ.get("SETUP_FILE_PATH", "/home/headless/sample_images")
SETUP_FILE_EXTENSION = os.environ.get("SETUP_FILE_EXTENSION", "png").lstrip(".")
WORK_DIR = os.environ.get("LAM_WORK_DIR", "/tmp/lam_data_generator/work")
EXPORT_DIR = os.environ.get("LAM_EXPORT_DIR", "/tmp/lam_data_generator/exports")
EXEC_TIMEOUT = float(os.environ.get("LAM_EXEC_TIMEOUT", "30"))

grounding_agent = OSWorldACI(platform=current_platform)

agent = grounding_agent
CURRENT_DOC_PATH = None
VALID_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _setup_source_path(idx: int) -> str:
    return os.path.join(
        SETUP_FILE_PATH, f"sample_{idx:02d}.{SETUP_FILE_EXTENSION}"
    )


def _work_file_path(idx: int) -> str:
    return os.path.join(
        _ensure_dir(WORK_DIR), f"sample_{idx:02d}.{SETUP_FILE_EXTENSION}"
    )


def _export_file_path(idx: int) -> str:
    return os.path.join(
        _ensure_dir(EXPORT_DIR), f"result_{idx:02d}.{SETUP_FILE_EXTENSION}"
    )


def _latest_image_file(search_dir: str) -> str | None:
    if not os.path.isdir(search_dir):
        return None
    candidates = [
        os.path.join(search_dir, name)
        for name in os.listdir(search_dir)
        if name.lower().endswith(f".{SETUP_FILE_EXTENSION.lower()}")
    ]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _execute_exec_code(exec_code: str):
    print("[EXEC] Starting code execution")
    print(exec_code)
    exec_globals = {
        "__builtins__": __builtins__,
        "pyautogui": pyautogui,
        "time": time,
        "subprocess": subprocess,
        "shutil": shutil,
        "os": os,
    }
    exec_locals = {}
    exec(exec_code, exec_globals, exec_locals)
    print("[EXEC] Finished code execution")
    return "SUCCESS"

def _show_desktop():
    # GNOME/Ubuntu: Super+D shows desktop (toggles). Hitting it once is usually enough.
    pyautogui.hotkey("win", "d")
    time.sleep(3)

def _terminate_other_processes() -> dict:
    """Keep the desktop/client infrastructure and terminate user applications."""
    infrastructure_names = {
        "tini", "startup.sh", "xinit", "Xvnc", "xfce4-session", "xfwm4",
        "xfsettingsd", "xfce4-panel", "xfdesktop", "dbus-launch",
        "dbus-daemon", "xfconfd", "gpg-agent",
    }
    infrastructure_cmdline_parts = (
        "/novnc_proxy", "python3 -m websockify", "/xfce4/panel/",
    )

    def process_info(pid: int) -> tuple[str, str]:
        name = ""
        cmdline = ""
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8") as status_file:
                for line in status_file:
                    if line.startswith("Name:"):
                        name = line.split(":", 1)[1].strip()
                        break
            with open(f"/proc/{pid}/cmdline", "rb") as cmdline_file:
                cmdline = cmdline_file.read().replace(b"\0", b" ").decode(
                    errors="replace"
                )
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
        return name, cmdline

    def parent_pid(pid: int) -> int | None:
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8") as status_file:
                for line in status_file:
                    if line.startswith("PPid:"):
                        return int(line.split(":", 1)[1].strip())
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            pass
        return None

    protected = {1, os.getpid()}
    pid = os.getpid()
    while pid not in (0, 1):
        pid = parent_pid(pid)
        if pid is None:
            break
        protected.add(pid)

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        candidate = int(entry)
        name, cmdline = process_info(candidate)
        if (
            name in infrastructure_names
            or any(part in cmdline for part in infrastructure_cmdline_parts)
        ):
            protected.add(candidate)

    def other_pids() -> list[int]:
        return [
            int(entry) for entry in os.listdir("/proc")
            if entry.isdigit() and int(entry) not in protected
        ]

    info = {
        "self_pid": os.getpid(),
        "protected_pids": sorted(protected),
        "term_sent": 0,
        "kill_sent": 0,
        "permission_denied": [],
    }
    for target_pid in other_pids():
        try:
            os.kill(target_pid, signal.SIGTERM)
            info["term_sent"] += 1
        except ProcessLookupError:
            pass
        except PermissionError:
            info["permission_denied"].append(target_pid)

    time.sleep(3)
    for target_pid in other_pids():
        try:
            os.kill(target_pid, signal.SIGKILL)
            info["kill_sent"] += 1
        except ProcessLookupError:
            pass
        except PermissionError:
            if target_pid not in info["permission_denied"]:
                info["permission_denied"].append(target_pid)

    print(f"[RESET] Process cleanup: {info}", flush=True)
    return info

def reset_to_desktop() -> str:
    global CURRENT_DOC_PATH
    processes = _terminate_other_processes()
    CURRENT_DOC_PATH = None
    return f"RESET_OK processes={processes}"

def get_env_desc(agent_class):
    env_desc = ""
    for attr_name in dir(agent_class):
            attr = getattr(agent_class, attr_name)
            if callable(attr) and hasattr(attr, "is_agent_action"):
                # Use inspect to get the full function signature
                signature = inspect.signature(attr)
                env_desc += f"""
    def {attr_name}{signature}:
    '''{attr.__doc__}'''
        """
    return env_desc

def setup_to_train_analysis(idx : int):
    global CURRENT_DOC_PATH
    print("Receive SETUP Signal")
    source_path = _setup_source_path(idx)
    if not os.path.exists(source_path):
        print(f"[SETUP Error] Missing file: {source_path}")
        return "FAIL"

    work_path = _work_file_path(idx)
    try:
        shutil.copy2(source_path, work_path)
        CURRENT_DOC_PATH = work_path
        subprocess.Popen(["gimp", work_path])
        time.sleep(3)
    except Exception as e:
        print(f"[SETUP Error] {e}")
        return "FAIL"

    return "SUCCESS"

async def connect_and_send():
    logger = logging.getLogger("client")
    logger.setLevel(logging.INFO)

    try:
        if CLIENT_ID is None or not VALID_CLIENT_ID_RE.fullmatch(CLIENT_ID):
            raise ValueError(f"Invalid CLIENT_ID: {CLIENT_ID!r}")

        reader, writer = await asyncio.open_connection(HOST, PORT)
        socket_session = SocketSession(CLIENT_ID, logger=logger)
        socket_session.attach(reader, writer)

        writer.write((CLIENT_ID + "\n").encode())
        await writer.drain()
        print(f"[{CLIENT_ID}] Sent handshake")
        print(f"[{CLIENT_ID}] Connected | Waiting for server request...")

        obs = {}
        #
        while True:
            # list_open_workbooks()
            server_msg = await socket_session.receive_request()
            print(f"[{CLIENT_ID}] Receive request: {server_msg}")

            if server_msg == "PLATFORM":
                await socket_session.send_message('text', current_platform)
            elif server_msg == "ENVDES":
                env_desc = get_env_desc(type(grounding_agent))
                await socket_session.send_message('text', env_desc)
            elif server_msg == "NOTE":
                # Send as list[str]. Server-side executor expects an iterable of strings.
                obs["note"] = grounding_agent.notes
                await socket_session.send_message('text', obs["note"])
            elif server_msg == "SCREENSHOT":
                screenshot = pyautogui.screenshot()
                buffered = io.BytesIO()
                screenshot.save(buffered, format="PNG")
                screenshot_bytes = buffered.getvalue()  # Get the byte value of the screenshot
                await socket_session.send_message('image', screenshot_bytes)
                obs["screenshot"] = screenshot
            elif server_msg == "EXEC":
                msg = await socket_session.receive_request()
                print(f"Received Message : {msg}")
                result = "FAIL"
                exec_code = msg
                try:
                    try:
                        print(f"[EXEC] Timeout set to {EXEC_TIMEOUT} seconds")
                        result = await asyncio.wait_for(
                            asyncio.to_thread(_execute_exec_code, exec_code),
                            timeout=EXEC_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        print(f"[EXEC Timeout] Execution exceeded {EXEC_TIMEOUT} seconds")
                        traceback.print_exc()
                        result = "FAIL"
                    except Exception:
                        print("[EXEC Error] Exception during execution")
                        traceback.print_exc()
                        result = "FAIL"

                    time.sleep(3)
                    print(f"[EXEC] Sending result: {result}")
                    await socket_session.send_message('text', result)
                except Exception:
                    print("[EXEC Fatal] Failed to send execution result")
                    traceback.print_exc()
                    await socket_session.send_message('text', 'FAIL')

                # Optional one-shot mode: exit after DONE/FAIL.
                if ONCE and ("done" in exec_code.lower() or "fail" in exec_code.lower()):
                    break
                # Auto-reset for servers that don't implement the RESET request.
                # This keeps episode boundaries cleaner even when only DONE/FAIL is sent.
                if AUTO_RESET_ON_DONE and ("done" in exec_code.lower() or "fail" in exec_code.lower()):
                    try:
                        # reset_to_desktop()
                        pass
                    except Exception:
                        pass
            elif server_msg.startswith("SETUP_"):
                # Handle the episode boundary and return a string status.
                raw_idx = server_msg.split("_", 1)[1]
                try:
                    setup_idx = int(raw_idx)
                    reset_to_desktop()
                    result = setup_to_train_analysis(setup_idx)
                    print(f"[{CLIENT_ID}] Parsed setup idx: {setup_idx}")
                    await socket_session.send_message('text', result)
                except ValueError:
                    print(f"[{CLIENT_ID}] Invalid SETUP message: {server_msg}")
                    await socket_session.send_message('text', "FAIL")

            elif server_msg.startswith("END_"):
                # Handle the episode boundary and return a string status.

                raw_idx = server_msg.split("_", 1)[1]

                try:
                    end_idx = int(raw_idx)
                    print(f"[END] Force closing task for idx={end_idx} without saving")
                    try:
                        reset_to_desktop()
                        result = "SUCCESS"
                    except Exception as e:
                        print(f"[END Error] {e}")
                        result = "FAIL"
                    print(f"[{CLIENT_ID}] Parsed end idx: {end_idx}")
                    await socket_session.send_message('text', result)
                except ValueError:
                    print(f"[{CLIENT_ID}] Invalid END message: {server_msg}")
                    await socket_session.send_message('text', "FAIL")

            elif server_msg == "EX":
                print("Recieve EX Signal")
                reset_to_desktop()

            elif server_msg == "RESET":
                # Reset environment to a clean "desktop" state for next episode.
                try:
                    status = reset_to_desktop()
                except Exception as e:
                    status = f"RESET_FAIL {e}"
                await socket_session.send_message("text", status)

            elif server_msg == "EXIT":
                break

    except Exception as e:
        print(f"[{CLIENT_ID}] Error or retrying: {e}")
        time.sleep(2)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Desktop client for LAM_data_generator")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--client_id", default=CLIENT_ID)
    parser.add_argument("--once", action="store_true", help="Exit after receiving done/fail.")
    parser.add_argument("--no-auto-reset", action="store_true", help="Disable auto reset on done/fail.")
    args = parser.parse_args()

    HOST = args.host
    PORT = args.port
    CLIENT_ID = args.client_id
    ONCE = bool(args.once)
    AUTO_RESET_ON_DONE = not bool(args.no_auto_reset)

    while True:
        asyncio.run(connect_and_send())
        if ONCE:
            break
        # time.sleep(1)  # Optional delay between rounds


# async def main_loop():
#     while True:
#         try:
#             await connect_and_send()
#         except Exception as e:
#             print(f"[{CLIENT_ID}] Connection lost or error: {e}")
#         await asyncio.sleep(2)

# if __name__ == "__main__":
#     asyncio.run(main_loop())
