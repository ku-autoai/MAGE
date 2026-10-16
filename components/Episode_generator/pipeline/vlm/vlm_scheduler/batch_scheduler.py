from abc import ABC, abstractmethod

import asyncio
from collections import deque

class BatchScheduler(ABC):
    def __init__(self, max_batch_size=5, max_wait_time=0.05):
        self.queue = deque()
        self.lock = asyncio.Lock()
        self.max_batch_size = max_batch_size
        self.max_wait_time = max_wait_time
        self.new_request_event = asyncio.Event()

    async def request(self, input_data):
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        async with self.lock:
            self.queue.append((input_data, fut))
            self.new_request_event.set()  # Trigger the event.
        return await fut

    async def batch_loop(self):
        while True:
            try:
                # Wait until the maximum wait time elapses or an event occurs.
                try:
                    await asyncio.wait_for(self.new_request_event.wait(), timeout=self.max_wait_time)
                except asyncio.TimeoutError:
                    pass  # Continue if it times out.

                async with self.lock:
                    if not self.queue:
                        self.new_request_event.clear()
                        continue

                    batch = [self.queue.popleft() for _ in range(min(self.max_batch_size, len(self.queue)))]

                    # Clear the event if the queue is empty.
                    if not self.queue:
                        self.new_request_event.clear()

                inputs, futures = zip(*batch)
                results = await self.run_batch(inputs)
                for fut, res in zip(futures, results):
                    fut.set_result(res)
            except Exception as e:
                print(f"[batch_loop ERROR] {e}")

    @abstractmethod
    async def run_batch(self, inputs):
        pass
