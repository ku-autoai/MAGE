import os

import backoff
from openai import (
    APIConnectionError,
    APIError,
    AsyncOpenAI,
    RateLimitError,
)

from .batch_scheduler import BatchScheduler

import os
import json
from datetime import datetime

def save_messages_as_json(messages, folder_path="prompt", file_name=None):
    os.makedirs(folder_path, exist_ok=True)

    # Default file name based on the current time.
    if file_name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{timestamp}.json"

    full_path = os.path.join(folder_path, file_name)

    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

class LMMEngineAsyncOpenAI:
    def __init__(self, api_key, rate_limit=-1, **kwargs):
        self.model = "gpt-5.4"

        self.api_key = api_key
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit

        self.llm_client = AsyncOpenAI(api_key=self.api_key)

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    async def generate(self, messages, temperature=1.0, max_new_tokens=None, **kwargs):
        """Generate the next message based on previous messages"""
        # save_messages_as_json(messages, folder_path="prompt")

        response = await self.llm_client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=max_new_tokens if max_new_tokens else 4096,
            temperature=temperature,
            **kwargs,
        )
        if response.choices:
            return response.choices[0].message.content
        else:
            return ValueError("No choices returned from the API")

class GPT4oBatchScheduler(BatchScheduler):
    def __init__(self, api_key, max_batch_size=1, max_wait_time=0.05):
        super().__init__(max_batch_size, max_wait_time)
        self.model = LMMEngineAsyncOpenAI(api_key=api_key)

    async def run_batch(self, inputs):
        print("===inference LLM===")
        inputs = inputs[0]
        result = await self.model.generate(messages=inputs)
        return [result]
