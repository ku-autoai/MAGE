"""VS Code desktop client and episode reset handler."""

import argparse
import asyncio
import inspect
import io
import logging
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import time
import traceback

import pyautogui

from pipeline.aci_de import OSWorldACI
from pipeline.util.socket_session import SocketSession


CURRENT_PLATFORM = platform.system().lower()
CLIENT_ID = os.environ.get("CLIENT_ID")
HOST = os.environ.get("HOST")
PORT = os.environ.get("PORT")
EXEC_TIMEOUT = float(os.environ.get("LAM_EXEC_TIMEOUT", "30"))
WORKSPACE_DIR = Path(os.environ.get("VSCODE_WORKSPACE_DIR", "/home/headless/workspace"))
WORKSPACE_SEED_DIR = Path(
    os.environ.get("VSCODE_WORKSPACE_SEED_DIR", "/opt/vscode-workspace-seed")
)
CONFIG_DIR = Path(os.environ.get("VSCODE_CONFIG_DIR", "/home/headless/.config/Code"))
EXTENSIONS_DIR = Path(os.environ.get("VSCODE_EXTENSIONS_DIR", "/home/headless/.vscode"))
VALID_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

grounding_agent = OSWorldACI(platform=CURRENT_PLATFORM)


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _vscode_pids() -> list[int]:
    """Return VS Code PIDs owned by the current container user."""
    result = subprocess.run(
        ["pgrep", "-u", str(os.getuid()), "-x", "code"],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(pid) for pid in result.stdout.split() if pid.isdigit()]


def _process_tree(roots: list[int]) -> list[int]:
    """Return roots and all descendants, with children ordered before parents."""
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            closing_paren = stat.rfind(")")
            parent = int(stat[closing_paren + 2 :].split()[1])
            children.setdefault(parent, []).append(int(entry.name))
        except (FileNotFoundError, PermissionError, ValueError, IndexError):
            continue

    ordered: list[int] = []
    seen: set[int] = set()

    def visit(pid: int) -> None:
        if pid in seen:
            return
        seen.add(pid)
        for child in children.get(pid, []):
            visit(child)
        ordered.append(pid)

    for root in roots:
        visit(root)
    return ordered


def _pid_exists(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def _stop_vscode() -> dict[str, object]:
    info: dict[str, object] = {"term_sent": [], "kill_sent": []}
    targets = _process_tree(_vscode_pids())
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
            info["term_sent"].append(pid)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + 5
    while any(_pid_exists(pid) for pid in targets) and time.monotonic() < deadline:
        time.sleep(0.2)

    for pid in targets:
        if not _pid_exists(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            info["kill_sent"].append(pid)
        except ProcessLookupError:
            pass
    return info


def _clear_directory(path: Path) -> int:
    """Clear one approved reset directory without removing its mount point."""
    approved = {CONFIG_DIR, EXTENSIONS_DIR, WORKSPACE_DIR}
    if path not in approved:
        raise ValueError(f"Refusing to clear unapproved path: {path}")
    if path.is_symlink():
        raise ValueError(f"Refusing to clear symlinked reset path: {path}")

    path.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def _restore_workspace_seed() -> int:
    if not WORKSPACE_SEED_DIR.is_dir():
        return 0

    restored = 0
    for source in WORKSPACE_SEED_DIR.iterdir():
        destination = WORKSPACE_DIR / source.name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        restored += 1
    return restored


def _start_vscode() -> int:
    process = subprocess.Popen(
        ["/usr/local/bin/code-container", str(WORKSPACE_DIR)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return process.pid


def reset_vscode(*, relaunch: bool = True) -> dict[str, object]:
    """Reset enabled VS Code state and optionally start a fresh process."""
    status: dict[str, object] = {"stopped": _stop_vscode()}
    reset_targets = (
        ("config", CONFIG_DIR, "VSCODE_RESET_CONFIG_ON_EX"),
        ("extensions", EXTENSIONS_DIR, "VSCODE_RESET_EXTENSIONS_ON_EX"),
        ("workspace", WORKSPACE_DIR, "VSCODE_RESET_WORKSPACE_ON_EX"),
    )
    for label, path, variable in reset_targets:
        if _env_flag(variable):
            status[label] = {"path": str(path), "removed": _clear_directory(path)}
        else:
            status[label] = "preserved"

    if _env_flag("VSCODE_RESET_WORKSPACE_ON_EX"):
        status["workspace_seed_restored"] = _restore_workspace_seed()
    if relaunch:
        status["vscode_pid"] = _start_vscode()

    print(f"[RESET] {status}", flush=True)
    return status


def _environment_description() -> str:
    descriptions = []
    for name in dir(type(grounding_agent)):
        attribute = getattr(type(grounding_agent), name)
        if callable(attribute) and hasattr(attribute, "is_agent_action"):
            descriptions.append(
                f"def {name}{inspect.signature(attribute)}:\n"
                f"    '''{attribute.__doc__}'''"
            )
    return "\n".join(descriptions)


def _execute_code(source: str) -> str:
    namespace = {
        "__builtins__": __builtins__,
        "os": os,
        "pyautogui": pyautogui,
        "shutil": shutil,
        "subprocess": subprocess,
        "time": time,
    }
    exec(source, namespace, {})
    return "SUCCESS"


async def _serve_connection() -> None:
    if not HOST:
        raise ValueError("HOST is required")
    if not PORT:
        raise ValueError("PORT is required")
    if not CLIENT_ID or not VALID_CLIENT_ID_RE.fullmatch(CLIENT_ID):
        raise ValueError(f"Invalid CLIENT_ID: {CLIENT_ID!r}")

    logger = logging.getLogger("vscode-client")
    reader, writer = await asyncio.open_connection(HOST, int(PORT))
    session = SocketSession(CLIENT_ID, logger=logger)
    session.attach(reader, writer)
    writer.write((CLIENT_ID + "\n").encode())
    await writer.drain()
    print(f"[{CLIENT_ID}] Connected to {HOST}:{PORT}", flush=True)

    try:
        while True:
            server_msg = await session.receive_request()
            print(f"[{CLIENT_ID}] Receive request: {server_msg}", flush=True)

            if server_msg == "PLATFORM":
                await session.send_message("text", CURRENT_PLATFORM)
            elif server_msg == "ENVDES":
                await session.send_message("text", _environment_description())
            elif server_msg == "NOTE":
                await session.send_message("text", grounding_agent.notes)
            elif server_msg == "SCREENSHOT":
                screenshot = pyautogui.screenshot()
                buffer = io.BytesIO()
                screenshot.save(buffer, format="PNG")
                await session.send_message("image", buffer.getvalue())
            elif server_msg == "EXEC":
                source = await session.receive_request()
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(_execute_code, source),
                        timeout=EXEC_TIMEOUT,
                    )
                except Exception:
                    traceback.print_exc()
                    result = "FAIL"
                await session.send_message("text", result)
            elif server_msg.startswith("SETUP_"):
                try:
                    int(server_msg.split("_", 1)[1])
                    reset_vscode()
                    result = "SUCCESS"
                except Exception:
                    traceback.print_exc()
                    result = "FAIL"
                await session.send_message("text", result)
            elif server_msg.startswith("END_"):
                try:
                    int(server_msg.split("_", 1)[1])
                    reset_vscode(relaunch=False)
                    result = "SUCCESS"
                except Exception:
                    traceback.print_exc()
                    result = "FAIL"
                await session.send_message("text", result)
            elif server_msg == "EX":
                print("Receive EX Signal", flush=True)
                reset_vscode()
            elif server_msg == "RESET":
                try:
                    status = f"RESET_OK {reset_vscode()}"
                except Exception as error:
                    traceback.print_exc()
                    status = f"RESET_FAIL {error}"
                await session.send_message("text", status)
            elif server_msg == "EXIT":
                break
    finally:
        writer.close()
        await writer.wait_closed()


async def _run_forever() -> None:
    while True:
        try:
            await _serve_connection()
        except Exception as error:
            print(f"[CLIENT] Connection error: {error}; retrying", flush=True)
            await asyncio.sleep(2)


def main() -> None:
    global CLIENT_ID, HOST, PORT

    parser = argparse.ArgumentParser(description="VS Code desktop client")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--client-id", default=CLIENT_ID)
    parser.add_argument("--reset-only", action="store_true")
    parser.add_argument("--no-relaunch", action="store_true")
    args = parser.parse_args()

    HOST = args.host
    PORT = args.port
    CLIENT_ID = args.client_id
    if args.reset_only:
        reset_vscode(relaunch=not args.no_relaunch)
        return
    asyncio.run(_run_forever())


if __name__ == "__main__":
    main()
