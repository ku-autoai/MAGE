import torch
import re
import tempfile
import ast
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor
from qwen_vl_utils import process_vision_info
from peft import PeftModel
from transformers import LogitsProcessor, LogitsProcessorList


class UITARSBatchScheduler_vlm():
    def __init__(self):
        super().__init__()
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

    def run_batch(self, inputs):
        torch.cuda.empty_cache()
        print("=== UI-TARS inference start ===")

        messages = inputs

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

        generated_ids = self.model.generate(
            **inputs, 
            max_new_tokens=1000,
            do_sample=False
            # logits_processor=logits_processor,
            )
        
        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]

        results = self.processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )

        print(results)

        return results[0]
