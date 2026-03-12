"""
Server-Sent Events transport for MCP.

Used by web clients like Claude.ai.
Communication happens via HTTP with SSE for server-to-client messages.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SSEClient:
    """Represents a connected SSE client."""

    client_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    connected: bool = True


class SSETransport:
    """
    Server-Sent Events transport for MCP protocol.

    Provides HTTP endpoints for SSE connections and message handling.
    """

    def __init__(self, on_message: Callable[[dict[str, Any], str], Any]):
        """
        Initialize SSE transport.

        Args:
            on_message: Callback for handling incoming messages.
                       Receives (message, client_id) and returns response.
        """
        self.on_message = on_message
        self._clients: dict[str, SSEClient] = {}
        self._running = False

    async def start(self):
        """Start the transport."""
        self._running = True
        logger.info("SSE transport started")

    async def stop(self):
        """Stop the transport and disconnect all clients."""
        self._running = False

        # Disconnect all clients
        for client_id in list(self._clients.keys()):
            await self.disconnect_client(client_id)

        logger.info("SSE transport stopped")

    def connect_client(self) -> str:
        """
        Register a new SSE client.

        Returns:
            Client ID for the new connection
        """
        client_id = str(uuid.uuid4())
        self._clients[client_id] = SSEClient(client_id=client_id)
        logger.info(f"SSE client connected: {client_id}")
        return client_id

    async def disconnect_client(self, client_id: str):
        """Disconnect a client."""
        if client_id in self._clients:
            client = self._clients[client_id]
            client.connected = False
            del self._clients[client_id]
            logger.info(f"SSE client disconnected: {client_id}")

    async def handle_request(self, client_id: str, message: dict[str, Any]) -> dict[str, Any]:
        """
        Handle an incoming request from a client.

        Args:
            client_id: The client ID
            message: The JSON-RPC message

        Returns:
            JSON-RPC response
        """
        if client_id not in self._clients:
            return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32600, "message": "Unknown client"}}

        try:
            result = await self.on_message(message, client_id)
            return result
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": str(e)}}

    async def send_to_client(self, client_id: str, message: dict[str, Any]):
        """Send a message to a specific client."""
        if client_id in self._clients:
            client = self._clients[client_id]
            await client.queue.put(message)

    async def broadcast(self, message: dict[str, Any]):
        """Send a message to all connected clients."""
        for client in self._clients.values():
            if client.connected:
                await client.queue.put(message)

    async def event_stream(self, client_id: str):
        """
        Generate SSE events for a client.

        This is an async generator that yields SSE-formatted events.

        Usage in Django/FastAPI:
            return StreamingResponse(
                transport.event_stream(client_id),
                media_type="text/event-stream"
            )
        """
        if client_id not in self._clients:
            return

        client = self._clients[client_id]

        try:
            while client.connected and self._running:
                try:
                    # Wait for message with timeout
                    message = await asyncio.wait_for(client.queue.get(), timeout=30.0)

                    # Format as SSE event
                    data = json.dumps(message)
                    yield f"data: {data}\n\n"

                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            await self.disconnect_client(client_id)

    def get_client_count(self) -> int:
        """Get number of connected clients."""
        return len(self._clients)


class SSEDjangoView:
    """
    Django view helper for SSE transport.

    Usage:
        from django.http import StreamingHttpResponse

        def sse_endpoint(request):
            transport = get_sse_transport()
            client_id = transport.connect_client()

            response = StreamingHttpResponse(
                transport.event_stream(client_id),
                content_type='text/event-stream'
            )
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
    """

    def __init__(self, transport: SSETransport):
        self.transport = transport

    async def connect(self, request) -> str:
        """Connect a new client and return client ID."""
        return self.transport.connect_client()

    async def message(self, request, client_id: str):
        """Handle an incoming message."""
        import json

        try:
            body = json.loads(request.body)
            response = await self.transport.handle_request(client_id, body)
            return response
        except json.JSONDecodeError:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}

    def stream(self, client_id: str):
        """Get event stream for a client."""
        return self.transport.event_stream(client_id)
