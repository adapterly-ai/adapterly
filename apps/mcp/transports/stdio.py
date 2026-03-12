"""
Standard I/O transport for MCP.

Used by CLI clients like Claude Code.
Communication happens via stdin/stdout with JSON-RPC messages.
"""

import asyncio
import json
import logging
import sys
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class StdioTransport:
    """
    Standard I/O transport for MCP protocol.

    Handles JSON-RPC messages over stdin/stdout.
    """

    def __init__(self, on_message: Callable[[dict[str, Any]], Any]):
        """
        Initialize stdio transport.

        Args:
            on_message: Callback for handling incoming messages
        """
        self.on_message = on_message
        self._running = False
        self._read_task: asyncio.Task | None = None

    async def start(self):
        """Start the transport."""
        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())
        logger.info("Stdio transport started")

    async def stop(self):
        """Stop the transport."""
        self._running = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        logger.info("Stdio transport stopped")

    async def _read_loop(self):
        """Read messages from stdin."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        loop = asyncio.get_event_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        _buffer = b""

        while self._running:
            try:
                # Read Content-Length header
                line = await reader.readline()
                if not line:
                    break

                line = line.decode("utf-8").strip()

                # Parse Content-Length
                if line.startswith("Content-Length:"):
                    length = int(line.split(":")[1].strip())

                    # Read empty line separator
                    await reader.readline()

                    # Read content
                    content = await reader.read(length)
                    message = json.loads(content.decode("utf-8"))

                    # Process message
                    response = await self._handle_message(message)

                    if response:
                        await self._send_message(response)

            except asyncio.CancelledError:
                break
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
            except Exception as e:
                logger.error(f"Error reading message: {e}")

    async def _handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle incoming message."""
        try:
            result = await self.on_message(message)
            return result
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": str(e)}}

    async def _send_message(self, message: dict[str, Any]):
        """Send message to stdout."""
        content = json.dumps(message)
        content_bytes = content.encode("utf-8")

        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"

        sys.stdout.buffer.write(header.encode("utf-8"))
        sys.stdout.buffer.write(content_bytes)
        sys.stdout.buffer.flush()

    async def send(self, message: dict[str, Any]):
        """Send a message."""
        await self._send_message(message)

    async def send_notification(self, method: str, params: dict[str, Any] | None = None):
        """Send a notification (no response expected)."""
        message = {"jsonrpc": "2.0", "method": method}
        if params:
            message["params"] = params

        await self._send_message(message)


class StdioTransportSync:
    """
    Synchronous version of stdio transport for simpler usage.
    """

    def __init__(self):
        self._buffer = ""

    def read_message(self) -> dict[str, Any] | None:
        """Read a message from stdin (blocking)."""
        try:
            # Read Content-Length header
            line = sys.stdin.readline()
            if not line:
                return None

            line = line.strip()

            if line.startswith("Content-Length:"):
                length = int(line.split(":")[1].strip())

                # Read empty line
                sys.stdin.readline()

                # Read content
                content = sys.stdin.read(length)
                return json.loads(content)

            return None

        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None

    def send_message(self, message: dict[str, Any]):
        """Send a message to stdout."""
        content = json.dumps(message)
        content_bytes = content.encode("utf-8")

        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"

        sys.stdout.write(header)
        sys.stdout.write(content)
        sys.stdout.flush()

    def send_response(self, id: Any, result: Any):
        """Send a successful response."""
        self.send_message({"jsonrpc": "2.0", "id": id, "result": result})

    def send_error(self, id: Any, code: int, message: str, data: Any = None):
        """Send an error response."""
        error = {"code": code, "message": message}
        if data:
            error["data"] = data

        self.send_message({"jsonrpc": "2.0", "id": id, "error": error})
