import os
import socket
import inspect
import pyautogui
import io
import asyncio
import json
import time
import platform
import logging

from pipeline.aci import OSWorldACI
from pipeline.util.socket_session import SocketSession

current_platform = platform.system().lower()

CLIENT_ID = "local"  # Change for each client
HOST = os.environ.get("GUI_AGENT_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("GUI_AGENT_SERVER_PORT", "3816"))

grounding_agent = OSWorldACI(platform=current_platform)

agent = grounding_agent

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

async def connect_and_send():
    logger = logging.getLogger("client")
    logger.setLevel(logging.INFO)

    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)
        socket_session = SocketSession(CLIENT_ID, logger=logger)
        socket_session.attach(reader, writer)

        writer.write((CLIENT_ID + "\n").encode())
        await writer.drain()
        print(f"[{CLIENT_ID}] Sent handshake")
        print(f"[{CLIENT_ID}] Connected | Waiting for server request...")

        obs = {}
        setup_idx = None
        end_idx = None

        # obs["accessibility_tree"] = UIElement.systemWideElement()

        while True:
            server_msg = await socket_session.receive_request()
            print(f"[{CLIENT_ID}] Receive request: {server_msg}")

            if server_msg == "PLATFORM":
                await socket_session.send_message('text', current_platform)
            elif server_msg == "ENVDES":
                env_desc = get_env_desc(type(grounding_agent))
                await socket_session.send_message('text', env_desc)
            elif server_msg == "NOTE":
                obs["note"] = ','.join(grounding_agent.notes)
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
                try:
                    exec_code = eval(msg)
                    if "done" in exec_code.lower() or "fail" in exec_code.lower() or "next" in exec_code.lower():
                        pass
                    elif "wait" in exec_code.lower():
                        time.sleep(5)
                    else:
                        exec(exec_code)
                    await socket_session.send_message('text', 'SUCCESS')
                except:
                    await socket_session.send_message('text', 'FAIL')
            elif server_msg.startswith("SETUP_"):
                raw_idx = server_msg.split("_", 1)[1]
                try:
                    setup_idx = int(raw_idx)
                    obs["setup_idx"] = setup_idx
                    print(f"[{CLIENT_ID}] Parsed setup idx: {setup_idx}")
                except ValueError:
                    print(f"[{CLIENT_ID}] Invalid SETUP message: {server_msg}")
            elif server_msg.startswith("END_"):
                raw_idx = server_msg.split("_", 1)[1]
                try:
                    end_idx = int(raw_idx)
                    obs["end_idx"] = end_idx
                    print(f"[{CLIENT_ID}] Parsed end idx: {end_idx}")
                except ValueError:
                    print(f"[{CLIENT_ID}] Invalid END message: {server_msg}")


            elif server_msg == "EXIT":
                break

    except Exception as e:
        print(f"[{CLIENT_ID}] Error or retrying: {e}")
        time.sleep(2)

if __name__ == "__main__":
    while True:
        asyncio.run(connect_and_send())
        time.sleep(1)  # Optional delay between rounds
