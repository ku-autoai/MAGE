import torch
import re
import tempfile
import ast
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor
from qwen_vl_utils import process_vision_info
from peft import PeftModel
from transformers import LogitsProcessor, LogitsProcessorList

from .batch_scheduler import BatchScheduler
# from batch_scheduler import BatchScheduler

class FrequencyPenaltyLogitsProcessor(LogitsProcessor):
    def __init__(self, penalty: float):
        self.penalty = penalty

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor) -> torch.FloatTensor:
    # Return without processing if the penalty is less than or equal to 0.
        if self.penalty <= 0:
            return scores

        # Iterate over each sequence in the batch.
        for i in range(input_ids.shape[0]):
            # Count how many times each generated token has appeared so far.
            # bincount counts frequencies from 0 to max(input_ids[i]).
            counts = torch.bincount(input_ids[i], minlength=scores.shape[1])
            
            # Match the length because counts can be shorter than scores; vocab size is usually large.
            if counts.shape[0] < scores.shape[1]:
                # Extend counts to the length of scores, padding the tail with zeros.
                padding = torch.zeros(scores.shape[1] - counts.shape[0], device=scores.device)
                counts = torch.cat([counts.float(), padding])
            else:
                counts = counts[:scores.shape[1]].float()

            # Subtract occurrence count * penalty from the logits (scores).
            # Tokens that have already appeared receive lower scores and are less likely to be selected.
            scores[i] = scores[i] - (counts * self.penalty)

        return scores
    
class UITARSBatchScheduler_vlm(BatchScheduler):
    def __init__(self, api_key=None, max_batch_size=5, max_wait_time=0.05):
        super().__init__(max_batch_size, max_wait_time)
        model_name_or_path = "ByteDance-Seed/UI-TARS-1.5-7B"

        self.lora_path = None

        # Always keep only the pure base model.
        self.base_model = AutoModelForImageTextToText.from_pretrained(
            model_name_or_path,
            device_map="auto",
            torch_dtype=torch.float16
        ).eval()

        # Model used for actual inference, initially the base model.
        self.model = self.base_model

        self.processor = AutoProcessor.from_pretrained(model_name_or_path)

    def set_parameter(self, lora_path: str):
        self.lora_path = lora_path

        # Attach LoRA only to base_model.
        self.model = PeftModel.from_pretrained(self.base_model, self.lora_path).eval()

        self.processor = AutoProcessor.from_pretrained(self.lora_path)

        print(f"UI-TARS model initialized with LoRA: {self.lora_path}")

    def safe_for_literal_eval(self, text: str) -> str:
        text = text.replace("\\'", "'")
        text = text.replace("'s", "’s")
        return text

    async def run_batch(self, inputs):
        torch.cuda.empty_cache()
        print("=== UI-TARS inference start ===")

        messages = inputs[0]

        for msg in messages:
            if "content" in msg:
                new_content = []
                for item in msg["content"]:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        new_content.append({
                            "type": "image",
                            "image": item["image_url"]["url"]
                        })
                    else:
                        new_content.append(item)
                    msg["content"] = new_content

        image_inputs, video_inputs = process_vision_info(messages)


        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        inputs = self.processor(
            text=[text],
            images=image_inputs,
            return_tensors="pt",
            padding=True
        ).to("cuda")

        frequency_penalty_val = 1.0  
        logits_processor = LogitsProcessorList([
            FrequencyPenaltyLogitsProcessor(penalty=frequency_penalty_val)
        ])

        generated_ids = self.model.generate(
            **inputs, 
            max_new_tokens=500,
            temperature=1.0,
            # logits_processor=logits_processor,
            )
        
        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]

        results = self.processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )

        print(results)

        return results


# if __name__ == "__main__":
#     import asyncio
#     import base64

#     async def main():
#         model = UITARSBatchScheduler_vlm()

#         GTA1_JUDGE_SYSTEM_PROMPT = "You are an expert visual scene understanding AI. Analyze the provided screenshot and text carefully."
#         judge_text = "Describe what you see in this image and provide a structured summary."
#         image_path = "/home/<user>/LAM_data_generator/image_with_dot.png"

#         with open(image_path, "rb") as f:
#             screenshot_b64 = base64.b64encode(f.read()).decode("utf-8")

#         obs = {"screenshot": f"data:image/png;base64,{screenshot_b64}", "note": "sample observation"}

#         messages = [
#             {
#                 "role": "system",
#                 "content": [
#                     {"type": "text", "text": GTA1_JUDGE_SYSTEM_PROMPT}
#                 ]
#             },
#             {
#                 "role": "user",
#                 "content": [
#                     {"type": "text", "text": judge_text},
#                     {"type": "image_url", "image_url": {"url": obs["screenshot"]}}
#                 ]
#             }
#         ]

#         results = await model.run_batch([messages])
#         print("\n=== Final result ===")
#         print(results[0])

#     asyncio.run(main())
