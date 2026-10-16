import asyncio
import json
from typing import Optional, Any


class SocketSession:
    def __init__(self, agent_id: str, logger):
        self.agent_id = agent_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

        self.logger = logger

    # --- Connection Management ---

    def attach(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer

    def detach(self):
        self.reader = None
        self.writer = None

    def is_connected(self) -> bool:
        return self.reader is not None and self.writer is not None and not self.writer.is_closing()

    # --- Low-Level Communication ---

    async def _send_line(self, line: str):
        if not self.is_connected():
            raise ConnectionError(f"[{self.agent_id}] Socket is not connected")
        self.writer.write((line + "\n").encode())
        await self.writer.drain()

    async def _receive_line(self) -> str:
        if self.reader is None:
            raise ConnectionError(f"[{self.agent_id}] Reader not available")
        data = await self.reader.readline()
        if not data:
            raise ConnectionError(f"[{self.agent_id}] Connection closed by peer")
        message = data.decode().strip()
        return message

    # --- Public Messaging API ---

    async def send_message(self, type_: str, data: Any):
        if type_ == "image":
            await self._send_image(data)
        elif type_ in {"json", "text"}:
            message = json.dumps({"type": type_, "data": data})
            await self._send_line(message)
            self.logger.info(f"[{self.agent_id}] Sent type: {type_}")
            self.logger.info(f"[{self.agent_id}] Data preview: {str(data)[:50]}")
        else:
            raise ValueError(f"Unsupported message type: {type_}")

    async def receive_message(self, expected_type: str) -> Any:
        if expected_type == "image":
            return await self._receive_image()
        line = await self._receive_line()
        try:
            parsed = json.loads(line)
            type_ = parsed.get("type")
            data = parsed.get("data")
            if type_ != expected_type:
                raise TypeError(f"[{self.agent_id}] Expected {expected_type}, got {type_}")
            self.logger.info(f"Received type: {type_}")
            self.logger.info(f"Data preview: {str(data)[:50]}")
            return data
        except Exception as e:
            raise ValueError(f"[{self.agent_id}] Failed to parse message: {e}")

    async def receive_any_message(self) -> tuple[str, Any]:
        line = await self._receive_line()
        try:
            parsed = json.loads(line)
            return parsed["type"], parsed["data"]
        except Exception as e:
            raise ValueError(f"[{self.agent_id}] Failed to parse message: {e}")
    
    async def receive_request(self) -> str:
        line = await self._receive_line()
        parsed = json.loads(line)
        type_ = parsed.get("type")
        data = parsed.get("data")

        return data

    async def send_and_receive_message(
        self,
        send_type: str,
        data: Any,
        expected_response_type: Optional[str] = None
    ) -> Any:
        await self.send_message(send_type, data)
        if expected_response_type:
            return await self.receive_message(expected_response_type)
        else:
            return await self.receive_any_message()

    # --- Image Transmission ---

    async def _send_image(self, image_bytes: bytes):
        if not isinstance(image_bytes, bytes):
            raise ValueError("Image data must be bytes")
        header = {"type": "image", "length": len(image_bytes)}
        await self._send_line(json.dumps(header))
        if not self.is_connected():
            raise ConnectionError("Socket not connected")
        self.writer.write(image_bytes)
        await self.writer.drain()
        self.logger.info(f"Sent image ({len(image_bytes)} bytes)")

    async def _receive_image(self) -> bytes:
        header_line = await self._receive_line()
        try:
            header = json.loads(header_line)
            if header.get("type") != "image":
                raise ValueError(f"Expected image header, got: {header}")
            length = int(header["length"])
        except Exception as e:
            raise ValueError(f"[{self.agent_id}] Failed to parse image header: {e}")

        if self.reader is None:
            raise ConnectionError("Reader is None")

        image_data = await self.reader.readexactly(length)
        self.logger.info(f"Received image ({length} bytes)")
        return image_data
