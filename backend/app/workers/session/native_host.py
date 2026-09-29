"""Chrome native messaging bridge. stdout is exclusively framed protocol data."""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
from pathlib import Path
from typing import Any, BinaryIO

import httpx
from app.workers.session.chrome_source import (
    CONNECT_PATH,
    DISCONNECT_PATH,
    POLL_PATH,
    REPLY_PATH,
)
from app.workers.session.rpc import RpcError, SignedClient
from pydantic import BaseModel, ConfigDict

HOST_NAME = "com.framefetch.chrome_source"
MAX_MESSAGE_BYTES = 1024 * 1024


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    prefix = stream.read(4)
    if not prefix:
        return None
    if len(prefix) != 4:
        raise ValueError("invalid_frame")
    size = struct.unpack("=I", prefix)[0]
    if not 0 < size <= MAX_MESSAGE_BYTES:
        raise ValueError("invalid_frame")
    raw = bytearray()
    while len(raw) < size:
        piece = stream.read(size - len(raw))
        if not piece:
            raise ValueError("invalid_frame")
        raw.extend(piece)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("invalid_frame")
    return value


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode()
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("invalid_frame")
    stream.write(struct.pack("=I", len(payload)) + payload)
    stream.flush()


async def run(secret: bytes, *, port: int = 19250) -> None:
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
    ) as http:
        client = SignedClient(http, secret)
        connection: str | None = None

        async def poll() -> None:
            nonlocal connection
            while True:
                try:
                    if connection is None:
                        reply = await client.post(CONNECT_PATH, Message(), Message)
                        connection = str(reply.model_dump()["connection"])
                        write_message(sys.stdout.buffer, {"command": "connected"})
                    command = await client.post(
                        POLL_PATH,
                        Message.model_validate({"connection": connection}),
                        Message,
                    )
                    value = command.model_dump()
                    if value.get("command") != "idle":
                        write_message(sys.stdout.buffer, value)
                except RpcError:
                    if connection is not None:
                        write_message(sys.stdout.buffer, {"command": "disconnected"})
                    connection = None
                    await asyncio.sleep(2)

        async def receive() -> None:
            while True:
                value = await asyncio.to_thread(read_message, sys.stdin.buffer)
                if value is None:
                    return
                if connection is None:
                    continue
                # The connection identity comes from the source, never Chrome.
                value["connection"] = connection
                try:
                    await client.post(REPLY_PATH, Message(**value), Message)
                except RpcError:
                    pass

        worker = asyncio.create_task(poll())
        try:
            await receive()
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            if connection is not None:
                try:
                    await client.post(
                        DISCONNECT_PATH,
                        Message.model_validate({"connection": connection}),
                        Message,
                    )
                except RpcError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("origin")
    args = parser.parse_args()
    try:
        if args.config.stat().st_mode & 0o077:
            return 2
        config = json.loads(args.config.read_text())
        if args.origin != config["origin"]:
            return 2
        asyncio.run(run(config["secret"].encode()))
    except (Exception, KeyboardInterrupt):
        # Exceptions may contain received private material. Do not print them.
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
