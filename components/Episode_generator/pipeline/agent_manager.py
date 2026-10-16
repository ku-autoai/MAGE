import asyncio
import re

import socket
import threading
from typing import Dict

from util.misc import instantiate_from_config
# from pipeline.project_generator import ProjectGenerator
from pipeline.agent import Agent
from pipeline.vlm.vlm_scheduler import BatchScheduler

VALID_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def validate_agent_id(raw_handshake: bytes) -> str:
    if not raw_handshake:
        raise ValueError("[AgentManager] No handshake received.")

    try:
        agent_id = raw_handshake.decode("utf-8").strip()
    except UnicodeDecodeError as e:
        raise ValueError("[AgentManager] Invalid handshake encoding.") from e

    if not agent_id:
        raise ValueError("[AgentManager] Empty agent id.")

    if not VALID_AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError(f"[AgentManager] Invalid agent id: {agent_id!r}")

    return agent_id

class AgentManager:
    def __init__(self, host, port, api_key, config, args):
        self.host = host
        self.port = port
        self.args = args

        self.agents: dict[str, Agent] = {}

        self.lock = asyncio.Lock()

        config['llm']['params']['api_key'] = api_key
        self.llm: BatchScheduler = instantiate_from_config(config['llm'])
        asyncio.create_task(self.llm.batch_loop())
        self.lam = None

        self.judvlm: BatchScheduler = instantiate_from_config(config['judge_qwen'])
        asyncio.create_task(self.judvlm.batch_loop())
        # self.judvlm = None

        config['project_generator']['params']['args'] = self.args
        self.project_generator = instantiate_from_config(config['project_generator'])

    async def handle_connection(self, reader, writer):
        try:
            # Handshake: receive agent_id
            handshake = await asyncio.wait_for(reader.readline(), timeout=5)
            agent_id = validate_agent_id(handshake)
            print(f"[AgentManager] Handshake received: {agent_id}")

            async with self.lock:
                if agent_id not in self.agents:
                    self.agents[agent_id] = Agent(agent_id=agent_id, llm=self.llm, lam=self.lam, project_generator=self.project_generator, judvlm=self.judvlm, args=self.args) # , 
                    print(f"[AgentManager] Created new agent: {agent_id}")

                agent = self.agents[agent_id]

            agent.attach_connection(reader, writer)

        except Exception as e:
            print(f"[AgentManager] Connection handling error: {e}")
            writer.close()
            await writer.wait_closed()

    async def run_server(self):
        server = await asyncio.start_server(self.handle_connection, self.host, self.port)
        print(f"[AgentManager] Server started on: {self.host}:{self.port}")
        async with server:
            await server.serve_forever()
