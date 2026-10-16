import os
import io
import re
import json
import time
import logging
import math
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from PIL import Image, ImageDraw
import base64
from io import BytesIO

from pipeline.project_generator import ProjectGenerator
from pipeline.vlm.vlm_scheduler import BatchScheduler
from pipeline.util.socket_session import SocketSession
from pipeline.mm_agents.uitars_prompt import COMPUTER_USE_DOUBAO, MOBILE_USE_DOUBAO, GROUNDING_DOUBAO, COMPUTER_USE_NO_THINKING
from pipeline.mm_agents.prompts import TASK_SUCCESS_CHECK_PROMPT, SUCCESS_CHECK_PROMPT
from pipeline.util.ui_tars_fun import UITARS_NORMAL_ACTION_SPACE, UITARS_USR_PROMPT_THOUGHT, parsing_response_to_pyautogui_code, parse_action_to_structure_output, pil_to_base64, add_box_token
import ast
import numpy as np

from pipeline.util.logging import make_summary
from pipeline.util import common_utils
from pipeline.util.ui_tars_fun import parse_action_to_structure_output, smart_resize

FINISH_WORD = "finished"
WAIT_WORD = "wait"
ENV_FAIL_WORD = "error_env"
CALL_USER = "call_user"
VALID_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_EPISODE_ROOT = Path(__file__).resolve().parents[1]


def _resolve_task_file(env_key: str, default_relative_path: str) -> str:
    raw_path = os.environ.get(env_key, default_relative_path)
    expanded = os.path.expandvars(os.path.expanduser(raw_path))
    path = Path(expanded)
    if not path.is_absolute():
        path = (_EPISODE_ROOT / path).resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Task file not found: {path}. Set environment variable {env_key} to a valid JSON path."
        )
    return str(path)


def _select_task_json(program: str, mod: str, rag: bool) -> str:
    if program == "calc":
        if mod == "val":
            return _resolve_task_file("EPG_TASK_CALC_VAL", "Task/calc_val.json")
        if mod == "train":
            return _resolve_task_file("EPG_TASK_CALC_TRAIN", "Task/calc_train.json")
        raise ValueError(f"Invalid --mod value: {mod}. Expected one of: train, val")

    if program == "impress":
        if mod == "val":
            return _resolve_task_file("EPG_TASK_IMPRESS_VAL", "Task/impress_val.json")
        if mod == "train":
            return _resolve_task_file("EPG_TASK_IMPRESS_TRAIN", "Task/impress_train.json")
        raise ValueError(f"Invalid --mod value: {mod}. Expected one of: train, val")

    if program == "writer":
        if mod == "val":
            return _resolve_task_file("EPG_TASK_WRITER_VAL", "Task/writer_val.json")
        if mod == "train":
            return _resolve_task_file("EPG_TASK_WRITER_TRAIN", "Task/writer_train.json")
        raise ValueError(f"Invalid --mod value: {mod}. Expected one of: train, val")

    if mod == "train":
        return _resolve_task_file("EPG_TASK_SLACK_TRAIN", "Task/slack_train.json")
    if mod == "val":
        return _resolve_task_file("EPG_TASK_SLACK_VAL", "Task/slack_val.json")
    raise ValueError(f"Invalid --mod value: {mod}. Expected one of: train, val")

def image_block(url):
    if url is None:
        return None
    return {
        "type": "image_url",
        "image_url": {"url": url}
    }

def setup_agent_logger(agent_id: str, log_dir: str):
    logger = logging.getLogger(agent_id)
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        for h in logger.handlers[:]:
            logger.removeHandler(h)
    fh = logging.FileHandler(os.path.join(log_dir, f"{agent_id}.log"), mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger

def parse_action(str_action: str):
    match = re.search(r"Action:\s*(.*)", str_action, re.DOTALL)
    action_full = match.group(1).strip()

    print("action_full:", action_full)

    return action_full

def draw_point_on_base64_image(b64_img, coords, color=(255, 0, 0), radius=5, idx = 0):

    print("= draw_point_on_base64_image =")
    print(coords)
    print("==============================")
    img_bytes = base64.b64decode(b64_img.split(',')[1])
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    draw = ImageDraw.Draw(img)

    for (x, y) in coords:
        x, y = int(x), int(y)

        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=color,
            outline=color
        )

    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    encoded = base64.b64encode(buffered.getvalue()).decode('utf-8')

    return f"data:image/png;base64,{encoded}"


def save_base64_image(data_url: str, output_path: str):
    if not data_url.startswith("data:image/png;base64,"):
        raise ValueError("Unsupported image payload format.")
    image_bytes = base64.b64decode(data_url.split(",", 1)[1])
    with open(output_path, "wb") as f:
        f.write(image_bytes)

class Agent:
    def __init__(self, agent_id: str, llm: BatchScheduler, project_generator: ProjectGenerator,
                 data_root_dir: str = './test', lam: BatchScheduler = None, max_step: int = 50, engine=None, judvlm: BatchScheduler = None, args = None):

        if not VALID_AGENT_ID_RE.fullmatch(agent_id):
            raise ValueError(f"Invalid agent_id: {agent_id!r}")

        self.agent_id = agent_id
        self.project_generator = project_generator
        self.llm = llm
        self.lam = lam
        self.judge = judvlm
        self.engine = engine
        self.args = args

        self.data_root_dir = self.args.base_dir
        self.data_save_dir = os.path.join(self.data_root_dir, 'data')
        self.data_original_dir = os.path.join(self.data_root_dir, 'data')
        os.makedirs(self.data_save_dir, exist_ok=True)

        # Logging setup.
        log_dir = os.path.join(self.data_save_dir, agent_id, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        self.logger = setup_agent_logger(agent_id, log_dir)

        # Socket session.
        self.session = SocketSession(agent_id, logger=self.logger)
        self.connected = asyncio.Event()
        self.running_task = asyncio.create_task(self.run())

        # Environment setup.
        self.prompt_action_space = UITARS_NORMAL_ACTION_SPACE
        self.prompt_template = UITARS_USR_PROMPT_THOUGHT
        self.max_trajectory_length = 50
        self.language = "English"
        self.action_parse_res_factor = 1000
        self.model_type = "qwen25vl"
        self.max_pixels = 12845056
        self.min_pixels = 78400
        self.history_n = 5
        self.input_swap = False


        # History and internal variables.
        self.max_step = max_step
        self.thoughts = []
        self.actions = []
        self.observations = []
        self.history_images = []
        self.history_responses = []

    def attach_connection(self, reader, writer):
        self.session.attach(reader, writer)
        self.connected.set()

    def detach_connection(self):
        self.session.detach()
        self.connected.clear()

    def reset_history(self):
        self.thoughts = []
        self.actions = []
        self.observations = []
        self.history_images = []
        self.history_responses = []

    async def run(self):
        """Main loop"""
        program = self.args.program

        if self.args.program == "calc":
            program = "Libre Calc"
        elif self.args.program == "impress":
            program = "Libre Impress"
        elif self.args.program == "writer":
            program = "Libre Writer"
        else:
            program = "Slack"

        json_path = _select_task_json(self.args.program, self.args.mod, self.args.rag)

        with open(json_path, "r", encoding="utf-8") as f:
            task_data = json.load(f)

        print(f"[{self.agent_id}] Agent loop started")
        self.platform = await self.session.send_and_receive_message('text', 'PLATFORM', 'text')
        self.env_description = await self.session.send_and_receive_message('text', 'ENVDES', 'text')

        print(f"The number of tasks is {len(task_data)}")

        await self.connected.wait()
        x = self.args.start_task_idx

        if self.args.end_task_idx <= 0 :
            end_idx = len(task_data)
        else:
            end_idx = self.args.end_task_idx            
        
        for lora_epoch in self.args.lora_epochs:

            if self.args.lora_path is not None:
                lora_path = os.path.join(self.args.lora_path, f"{lora_epoch}")

                if os.path.isdir(lora_path):
                    self.judge.set_parameter(lora_path)
                    print(f"Done apply parameter : {lora_path}")
                else:
                    continue
            else :
                lora_epoch = "vanila"
                
            self.data_save_dir = os.path.join(self.data_original_dir,f"{lora_epoch}")
            self.meta_save_dir = os.path.join(self.data_save_dir, "meta_data.json")
            os.makedirs(self.data_save_dir, exist_ok=True)


            trajectory_num = self.args.trajectory_num

            print("Total Task len : ", end_idx)
            meta_data = {
                "device_id" : self.agent_id,
                "lora_path" : self.args.lora_path,
                "instrution_path" : json_path
            }

            with open(self.meta_save_dir, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=4)

            for i in range(trajectory_num):
                for num in range(x, end_idx): # len(task_data)
                # for num in [0,8,13,14,22,23]: # len(task_data)
                    print(f"[{self.agent_id}] Waiting for project in {program}...")
                    await self._run_project_loop(task_data[num], num, app_name=program, id = task_data[num]["id"])
                    # await self._run_project_loop(tasks)
                    make_summary(self.data_save_dir, model_path = self.judge.lora_path)
                
                x = 0
            
        exit()

    async def _run_project_loop(self, task_set: str = None, num: int = 0, app_name: str = "Slack", id: Optional[str] = None):
        origin_resized_height = 1080
        origin_resized_width = 1920

        """Run one project"""
        # json_path = os.path.join(root_folder, example, f"{example}.json")
        task_pair, self.project_id, is_setup = await self.project_generator.generate_project(task_set, num, app_name=app_name)
        sub_success = False


        # Task tracker implementation.
        '''
        Setup task completed -> run main task
        Setup task failed -> stop 
        '''
        for (_task, task_only) in task_pair:
            self.reset_history()

            if self.project_id == -1:
                self.logger.info(f"[{self.agent_id}] No more projects available.")
                return data_save_dir

            # Send the command to open Excel for setup tasks.
            if is_setup:

                await self.session.send_message('text', 'EX')

                print(f"[{self.agent_id}] Starting Setup task...")
                file_name = "setup"
            else:
                print(f"[{self.agent_id}] Starting Main task...")
                if len(task_pair) == 1:
                    await self.session.send_message('text', 'EX')
                if sub_success == False and len(task_pair) > 1:
                    return data_save_dir
                file_name = "main"

            # History persistence.
            timestamp = datetime.now().strftime("%y%m%d%H%M")
            data_id = f"{timestamp}_{self.project_id}_{self.agent_id}_{file_name}_{num}"
            data_save_dir = os.path.join(self.data_save_dir, data_id)
            os.makedirs(data_save_dir, exist_ok=True)
            json_save_path = os.path.join(data_save_dir, f"{data_id}.json")
            history_save_path = os.path.join(data_save_dir, f"{data_id}_history.json")
            judge_save_path = os.path.join(data_save_dir, f"{data_id}_judge.json")
            project_info = {"project": task_only,"real_input":_task, "steps": []}

            judge_trajectory = {"project": task_only,"real_input":_task, "steps": []}
            fail_count = 0

            for step_idx in range(self.max_step):
                start = time.time()
                signal = None

                print(f"[{self.agent_id}] Project {self.project_id} Step {step_idx} / {self.max_step}")

                # Receive the image.
                await self.session.send_message('text', 'ACBT')
                image_bytes = await self.session.send_and_receive_message('text', 'SCREENSHOT', 'image')
                image = Image.open(io.BytesIO(image_bytes))
                image_path = os.path.join(data_save_dir, f"{step_idx}.png")
                image.save(image_path)
                screenshot_b64 = base64.b64encode(image_bytes).decode('utf-8')
                note = await self.session.send_and_receive_message('text', 'NOTE', 'text')
                obs = {"screenshot": f"data:image/png;base64,{screenshot_b64}", "note": note}
                # obs = {"screenshot": screenshot_b64, "note": note}
                print("image received")

                # Initialize variables.
                if len(self.observations) > self.max_trajectory_length:
                    if self.max_trajectory_length == 0:
                        _observations = []
                        _actions = []
                        _thoughts = []
                    else:
                        _observations = self.observations[-self.max_trajectory_length :]
                        _actions = self.actions[-self.max_trajectory_length :]
                        _thoughts = self.thoughts[-self.max_trajectory_length :]
                else:
                    _observations = self.observations
                    _actions = self.actions
                    _thoughts = self.thoughts
                
                self.history_images.append(image_bytes)
                base64_image = screenshot_b64
                
                
                self.observations.append(
                    {"screenshot": base64_image, "accessibility_tree": None}
                )

                user_prompt = self.prompt_template.format(
                    instruction=_task,
                    action_space=self.prompt_action_space,
                    language=self.language
                )
                
                if len(self.history_images) > self.history_n:
                    self.history_images = self.history_images[-self.history_n:]
                
                messages, images = [], []
                if isinstance(self.history_images, bytes):
                    self.history_images = [self.history_images]
                elif isinstance(self.history_images, np.ndarray):
                    self.history_images = list(self.history_images)
                elif isinstance(self.history_images, list):
                    pass
                else:
                    raise TypeError(f"Unidentified images type: {type(self.history_images)}")
                
                for turn, image in enumerate(self.history_images):
                    if len(images) >= self.history_n:
                        break
                    try:
                        image = Image.open(BytesIO(image))
                    except Exception as e:
                        raise RuntimeError(f"Error opening image: {e}")

                    if image.width * image.height > self.max_pixels:
                        resize_factor = math.sqrt(self.max_pixels / (image.width * image.height))
                        width, height = int(image.width * resize_factor), int(image.height * resize_factor)
                        image = image.resize((width, height))
                    if image.width * image.height < self.min_pixels:
                        resize_factor = math.sqrt(self.min_pixels / (image.width * image.height))
                        width, height = math.ceil(image.width * resize_factor), math.ceil(image.height * resize_factor)
                        image = image.resize((width, height))

                    if image.mode != "RGB":
                        image = image.convert("RGB")

                    images.append(image)

                messages = [
                    {
                        "role": "system",
                        "content": [{"type": "text", "text": "You are a helpful assistant."}]
                    },
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": user_prompt}]
                    }
                ]
                
                image_num = 0

                if len(self.history_responses) > 0:
                    for history_idx, history_response in enumerate(self.history_responses):
                        # send at most history_n images to the model
                        if history_idx + self.history_n > len(self.history_responses):

                            cur_image = images[image_num]
                            encoded_string = pil_to_base64(cur_image)
                            messages.append({
                                "role": "user",
                                "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_string}"}}]
                            })
                            image_num += 1
                            
                        messages.append({
                            "role": "assistant",
                            "content": [{"type": "text", "text": add_box_token(history_response)}]
                        })

                    cur_image = images[image_num]
                    encoded_string = pil_to_base64(cur_image)
                    messages.append({
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_string}"}}]
                    })
                    image_num += 1
                
                else:
                    cur_image = images[image_num]
                    encoded_string = pil_to_base64(cur_image)
                    messages.append({
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_string}"}}]
                    })
                    image_num += 1
                
                try_times = 3
                origin_resized_height = images[-1].height
                origin_resized_width = images[-1].width
                
                # ============== Action Prediction ==============
                while True:
                    if try_times <= 0:
                        print(f"Reach max retry times to fetch response from client, as error flag.")
                        return "client error", ["DONE"]
                    try:
                        response = await self.judge.request(messages)
                        print("*" * 20)
                        print("Response:")
                        prediction = response.strip()
                        print(prediction)
                        print("*" * 20)
                        

                    except Exception as e:
                        logger.exception(f"Error when fetching response from client: {e}")
                        prediction = None
                        try_times -= 1

                    try:
                        parsed_responses = parse_action_to_structure_output(
                            prediction,
                            self.action_parse_res_factor,
                            origin_resized_height,
                            origin_resized_width,
                            self.model_type,
                            self.max_pixels,
                            self.min_pixels
                        )
                        break
                    except Exception as e:
                        print(f"Error when parsing response from client: {e}")
                        # If fail to parse the model response, we use sampling parameters to avoid it
                        prediction = None
                        try_times -= 1
                        temperature = 1
                        top_k = -1

                self.history_responses.append(prediction)
                self.thoughts.append(prediction)

                try:
                    parsed_responses = parse_action_to_structure_output(
                        prediction,
                        self.action_parse_res_factor,
                        origin_resized_height,
                        origin_resized_width,
                        self.model_type,
                        self.max_pixels,
                        self.min_pixels
                    )
                except Exception as e:
                    print(f"Parsing action error: {prediction}, with error:\n{e}")
                    signal = ["DONE"]

                
                actions = []
                last_image = Image.open(BytesIO(self.history_images[-1]))
                obs_image_height = last_image.height
                obs_image_width = last_image.width
                for parsed_response in parsed_responses:
                    if "action_type" in parsed_response:

                        if parsed_response["action_type"] == FINISH_WORD:
                            actions.append(FINISH_WORD)
                            self.actions.append(actions)
                            signal = ["DONE"]
                            break
                        
                        elif parsed_response["action_type"] == WAIT_WORD:
                            actions.append(WAIT_WORD)
                            self.actions.append(actions)
                            signal = ["WAIT"]
                            break
                        
                        elif parsed_response["action_type"] == ENV_FAIL_WORD:
                            actions.append(ENV_FAIL_WORD)
                            self.actions.append(actions)
                            signal = ["FAIL"]
                            break

                        elif parsed_response["action_type"] == CALL_USER:
                            if self.callusr_tolerance > self.cur_callusr_count:
                                actions.append(CALL_USER)
                                self.actions.append(actions)
                                self.cur_callusr_count += 1
                                signal = ["CALL_USER"]
                                break
                            else:
                                actions.append("FAIL")
                                self.actions.append(actions)
                                signal = ["FAIL"]
                                break
                    
                    try :
                        pyautogui_code = parsing_response_to_pyautogui_code(
                            parsed_response,
                            obs_image_height,
                            obs_image_width,
                            self.input_swap
                        )
                        actions.append(pyautogui_code)
                    except:
                        actions = []

                self.actions.append(actions)
                print(f"[{self.agent_id}] Parsed actions: {actions}")

                for i, action_str in enumerate(actions):
                    print(f"[{self.agent_id}] About to send EXEC for action {i}")
                    await self.session.send_message('text', 'EXEC')
                    print(f"Action {i}: {action_str} sent")
                    await asyncio.sleep(1)
                    print(f"[{self.agent_id}] Waiting action payload ack path for action {i}")
                    result = await self.session.send_and_receive_message('text', f'{action_str}', 'text')
                    print(f"[{self.agent_id}] Received EXEC result for action {i}: {result}")

                # === Determine success ===
                '''
                past images -> obs['screenshot']
                current image -> received from the client
                
                SUCCESS_CHECK_PROMPT: success judgment prompt
                
                1. Optionally mark action coordinates on the image
                2. Consider adding extra context
                3. Return the success label and reasoning
                '''
                coords = None

                if  len(actions) > 0:
                    if "click" in actions[0]:
                        matches = re.findall(r'pyautogui\.click\(\s*([\d\.]+)\s*,\s*([\d\.]+)', actions[0])

                        if matches:
                            coords = [(round(float(x)), round(float(y))) for x, y in matches]
                            print(coords)  # [(1894.161, 20.769)]

                    elif "drag" in parsed_responses[0]["action_type"]:
                        matches = re.findall(r"(?:moveTo|dragTo)\(\s*([\d\.]+)\s*,\s*([\d\.]+)", actions[0])
                        coords = []

                        if matches:
                            for x, y in matches:
                                coords.append((round(float(x)), round(float(y))))
                            print(coords)  # [(1894.161, 20.769)]

                if coords and getattr(self.args, "mark_coords", True):
                    obs["screenshot_with_dot"] = draw_point_on_base64_image(obs["screenshot"], coords, idx = step_idx)
                    point_image_path = os.path.join(data_save_dir, f"{step_idx}_point.png")
                    save_base64_image(obs["screenshot_with_dot"], point_image_path)
                else:
                    obs["screenshot_with_dot"] = obs['screenshot']

                is_success_reason, is_success = None, None

                project_info["steps"].append({
                    "id": step_idx,
                    "model_output" : prediction,
                    "parsed_responses" : parsed_responses,
                    "actions" : actions,
                    "signal" : signal,
                    "coords" : coords,
                    "result" : is_success if is_success is not None else None,
                    "result reason" : is_success_reason if is_success_reason is not None else None,
                })

                with open(json_save_path, "w", encoding="utf-8") as f:
                    json.dump(project_info, f, ensure_ascii=False, indent=4)

                if signal is not None:
                    if signal[0] == "DONE":
                        break
                    elif signal[0] == "WAIT":
                        pass
                    elif signal[0] == "FAIL":
                        break
                    elif signal[0] == "CALL_USER":
                        input("Please assist the agent and press Enter to continue...")

                time.sleep(1)
                end = time.time()
                print(f"step time : {end - start}")

            last_5_steps = images[-5:]  # Automatically handles fewer than 5 items.

            encoded_last_images = []
            for img in last_5_steps:
                encoded_string = pil_to_base64(img)
                encoded_last_images.append(f"data:image/png;base64,{encoded_string}")

            # Add padding based on the number of images to always keep 5 images.
            while len(encoded_last_images) < 5:
                encoded_last_images.insert(0, None)

            task_result_message = [
                {
                    "role": "system",
                    "content": [{"type": "text", "text": TASK_SUCCESS_CHECK_PROMPT}]
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Task:\n{task_only}"}
                    ]
                }
            ]

            for url in encoded_last_images:
                block = image_block(url)
                if block:
                    task_result_message[1]["content"].append(block)

            task_success_str = await self.llm.request(task_result_message)
            print(task_success_str)

            # This section can likely be copied and edited from here.
            result_dic = self.success_parsing(task_success_str)
            task_success_reason, task_success = result_dic["result_thought"], result_dic["result"]
            score_reason, score = result_dic["score_thought"], result_dic["score"]

            if task_success == "SUCCESS" and is_setup:
                sub_success = True
                project_info["final_result"] = True
                project_info["final_result_reason"] = task_success_reason
                project_info["score"] = score
                project_info["score_reason"] = score_reason
            elif task_success == "SUCCESS":
                project_info["final_result"] = True
                project_info["final_result_reason"] = task_success_reason
                project_info["score"] = score
                project_info["score_reason"] = score_reason
            else:
                project_info["final_result"] = False
                project_info["final_result_reason"] = task_success_reason
                project_info["score"] = score
                project_info["score_reason"] = score_reason

            is_setup = False

            # === End ===
            self.logger.info(f"[{self.project_id}] Project finished: {_task}")
            print(f"[{self.agent_id}] Project finished: {_task}")

            with open(json_save_path, "w", encoding="utf-8") as f:
                json.dump(project_info, f, ensure_ascii=False, indent=4)


        return data_save_dir

    def success_parsing(self, success_parsing_str : str):
        print(success_parsing_str)

        try:
            # 1. Extract only the JSON block.
            json_str = common_utils.extract_json_block(success_parsing_str)
            if not json_str:
                raise ValueError("No JSON block found in response_text.")

            # 2. Parse JSON.
            result = json.loads(json_str)

            # 3. Check required keys in the new format.
            required_keys = ["result", "result_thought", "score", "score_thought"]
            for key in required_keys:
                if key not in result:
                    raise ValueError(f"Missing required key in response JSON: {key}")

            # 4. Validate the result value.
            if result["result"] not in ["SUCCESS", "FAIL"]:
                raise ValueError("Invalid result value. Must be 'SUCCESS' or 'FAIL'.")

            # 5. Validate the score value.
            if not isinstance(result["score"], (int, float)):
                raise ValueError("Score must be a number.")
            if not (0.0 <= result["score"] <= 1.0):
                raise ValueError("Score must be between 0.0 and 1.0.")

            return {
                "result_thought": result["result_thought"],
                "result": result["result"],
                "score_thought": result["score_thought"],
                "score": result["score"],
            }

        except json.JSONDecodeError:
            print("⚠️ JSONDecodeError: invalid JSON syntax")
            return {
                "result_thought": "",
                "result": "FAIL",
                "score_thought": "",
                "score": 0.0,
            }

        except Exception as e:
            print(f"⚠️ Parsing Error: {e}")
            return {
                "result_thought": "",
                "result": "FAIL",
                "score_thought": "",
                "score": 0.0,
            }
