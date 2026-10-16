import math

import torch
from PIL import Image
from torchvision import transforms

from transformers import Qwen2_5_VLForConditionalGeneration

from qwen_vl_utils import process_vision_info
from transformers.models.qwen2_vl.image_processing_qwen2_vl_fast import smart_resize

try:
    from ..util.ui_tars_fun import (
        UITARS_NORMAL_ACTION_SPACE,
        UITARS_USR_PROMPT_THOUGHT,
        add_box_token,
    )
except ImportError:
    from util.ui_tars_fun import (
        UITARS_NORMAL_ACTION_SPACE,
        UITARS_USR_PROMPT_THOUGHT,
        add_box_token,
    )

to_pil = transforms.ToPILImage()
to_tensor = transforms.ToTensor()


def _create_prompt_messages(task, response: list, images, history_n = 5):

    """
    Creates the structured message for the Qwen2.5-VL chat template.
    The <|image_1|> token is a placeholder that the processor will replace.
    """
    response_histories = response[:-1]
    image_history = images

    if len(image_history) > history_n:
        image_history = image_history[-history_n:]

    user_prompt = UITARS_USR_PROMPT_THOUGHT.format(
        instruction=task,
        action_space=UITARS_NORMAL_ACTION_SPACE,
        language="English"
    )

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
    action_num = 0

    if len(response_histories) > 0:
        for history_idx, history_response in enumerate(response_histories):
            if history_idx + history_n > len(response_histories):
                cur_image = image_history[image_num]
                messages.append({
                    "role": "user",
                    "content": [{"type": "image", "image": cur_image}]
                })

                image_num += 1

            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": add_box_token(history_response)}]
            })
            action_num += 1

        cur_image = images[image_num]

        messages.append({
            "role": "user",
            "content": [{"type": "image", "image": cur_image}]
        })
        image_num += 1

    else:
        cur_image = images[image_num]
        messages.append({
            "role": "user",
            "content": [{"type": "image", "image": cur_image}]
        })
        image_num += 1

    print(f"Total images used in prompt: {image_num}, total history responses used in prompt: {action_num}")
    return messages


def unwrap_for_generate(model):
    """
    model: possibly wrapped by DeepSpeedEngine → PeftModel → base_model
    goal: get to Qwen2_5_VLForConditionalGeneration
    """

    if hasattr(model, "module"):
        model = model.module
    if hasattr(model, "get_base_model"):  # preferred PEFT API
        model = model.get_base_model()
    elif hasattr(model, "base_model"):
        model = model.base_model

    # now, check class name
    if not isinstance(model, Qwen2_5_VLForConditionalGeneration):
        raise TypeError(f"`generate()` must be called on `Qwen2_5_VLForConditionalGeneration`, but got {type(model)}")

    return model


def calc_reward(gt_bbox, generated_point):
    try:
        x, y = int(generated_point[0]), int(generated_point[1])
    except ValueError:
        x, y = 0, 0
    if gt_bbox[0] <= x <= gt_bbox[2] and gt_bbox[1] <= y <= gt_bbox[3]:
        result = 1
    else:
        result = 0

    gt_center_x, gt_center_y = (gt_bbox[0]+gt_bbox[2])/2, (gt_bbox[1]+gt_bbox[3])/2
    distance = math.sqrt((x - gt_center_x)**2 + (y- gt_center_y)**2)

    return result, distance


def create_input_uitars(
    raw_images,
    tasks,
    model,
    processor,
    device,
    target=None,  # history & response
    use_model_output=False,
    return_prompt_inputs=False,
    history_n = 5
):

    # assert (not use_model_output and target_positions != None), "use_model_output or target_positions must be used."

    ###############################################################
    # 1. Resize the image using the model's recommended `smart_resize`
    # image = Image.open(image_path).convert("RGB")

    images = []
    for images_per_batch in raw_images:
        tmp_img = []
        for image_path in images_per_batch:
            image = to_tensor(Image.open(image_path).convert("RGB"))
            image = to_pil(image)
            resized_height, resized_width = smart_resize(image.height, image.width)
            resized_image = image.resize((resized_width, resized_height))

            # Ensure minimum dimensions of 28 pixels and maximum dimensions under max pixels.
            w, h = resized_image.size
            if w < 28 or h < 28:
                # Calculate new dimensions maintaining aspect ratio
                if w < h:
                    new_w = 28
                    new_h = int(h * (28/w))
                else:
                    new_h = 28
                    new_w = int(w * (28/h))
                resized_image = resized_image.resize((new_w, new_h), Image.Resampling.LANCZOS)

            resized_height, resized_width = resized_image.size
            tmp_img.append(resized_image)
        images.append(tmp_img)
    ###############################################################
    # 2. Create the prompt message structure

    prompt_texts = []
    image_inputs_batch = []

    for idx, task in enumerate(tasks):
        image_batch = images[idx]
        target_batch = target[idx]

        messages = _create_prompt_messages(task, target_batch, image_batch, history_n=history_n)

        # 3. Apply the chat template and prepare for forced decoding
        # We'll guide the model to generate a specific JSON structure for a tool call.
        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        
        prompt_texts.append(text)

        ###############################################################
        # 3. Prepare inputs for the model

        image_inputs, _ = process_vision_info(messages)
        image_inputs_batch.append(image_inputs)

    prompt_inputs = processor(
        text=prompt_texts,
        max_length=10000,
        images=image_inputs_batch,
        padding=True,
        return_tensors="pt",
        padding_side="left",
        add_special_tokens=False
    ).to(device)

    prompt_ids, prompt_mask = prompt_inputs["input_ids"], prompt_inputs["attention_mask"]
    prompt_length = prompt_ids.size(1)
    try:
        pixel_values = prompt_inputs["pixel_values"]
        image_grid_thw = prompt_inputs["image_grid_thw"]
    except Exception:
        pixel_values = None
        image_grid_thw = None

    ###################################################################
    # 4. Create target
    completions = None
    
    target_texts = []
    for target_batch in target:
        target_texts.append(target_batch[-1])

    targets = processor(
        text=target_texts,
        padding=True,
        return_tensors="pt",
        padding_side="right",
        add_special_tokens=False
    ).to(device)
    completion_ids = targets["input_ids"]
    
    special_ids = processor.tokenizer.all_special_ids
    special_ids_tensor = torch.tensor(special_ids, device=completion_ids.device)

    is_special = torch.isin(completion_ids, special_ids_tensor)
    completion_mask = (~is_special).int()

    out = {
        "prompt_ids": prompt_ids,
        "prompt_mask": prompt_mask,
        "completion_ids": completion_ids,
        "completion_mask": completion_mask,
        "pixel_values": pixel_values,
        "image_grid_thw": image_grid_thw,
        "prompt_length": prompt_length,
        "output_result": completions
    }

    if return_prompt_inputs:
        return out, prompt_inputs

    return out, None
