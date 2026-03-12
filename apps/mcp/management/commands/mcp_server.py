"""
Django management command to run the MCP server.

Usage:
    python manage.py mcp_server --account-id 123 --api-key ak_live_xxx --mode safe

This starts the MCP server with stdio transport for use with Claude Code.
"""

import asyncio
import logging
import os
import sys

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the MCP server for AI agent integration"

    def add_arguments(self, parser):
        parser.add_argument("--account-id", type=int, required=True, help="Account ID to run the server for")
        parser.add_argument(
            "--api-key",
            type=str,
            default=None,
            help="API key for authentication (can also be set via MCP_API_KEY env var)",
        )
        parser.add_argument(
            "--mode",
            type=str,
            choices=["safe", "power"],
            default="safe",
            help="Permission mode: safe (read only) or power (all operations)",
        )
        parser.add_argument("--user-id", type=int, default=None, help="User ID for audit logging")
        parser.add_argument(
            "--transport", type=str, choices=["stdio", "sse"], default="stdio", help="Transport type (default: stdio)"
        )
        parser.add_argument(
            "--log-level",
            type=str,
            choices=["DEBUG", "INFO", "WARNING", "ERROR"],
            default="WARNING",
            help="Log level for MCP server",
        )

    def handle(self, *args, **options):
        account_id = options["account_id"]
        api_key = options["api_key"] or os.getenv("MCP_API_KEY")
        mode = options["mode"]
        user_id = options["user_id"]
        transport = options["transport"]
        log_level = options["log_level"]

        # Configure logging
        logging.basicConfig(
            level=getattr(logging, log_level),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            stream=sys.stderr,  # Keep stdout for MCP protocol
        )

        # Validate account exists
        from apps.accounts.models import Account

        try:
            account = Account.objects.get(id=account_id)
        except Account.DoesNotExist:
            raise CommandError(f"Account {account_id} does not exist")

        # Log startup info to stderr
        logger.info(f"Starting MCP server for account: {account.name} (ID: {account_id})")
        logger.info(f"Mode: {mode}, Transport: {transport}")

        if transport == "stdio":
            self._run_stdio_server(account_id, api_key, mode, user_id)
        else:
            raise CommandError(f"Transport '{transport}' not yet implemented for CLI")

    def _run_stdio_server(self, account_id, api_key, mode, user_id):
        """Run the MCP server with stdio transport."""
        from apps.mcp.server import MCPServer
        from apps.mcp.transports.stdio import StdioTransportSync

        # Create server
        server = MCPServer(account_id=account_id, api_key=api_key, mode=mode, user_id=user_id, transport="stdio")

        # Create transport
        transport = StdioTransportSync()

        # Run event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Initialize server
            loop.run_until_complete(server.initialize())

            logger.info("MCP server ready, waiting for messages...")

            # Main message loop
            while True:
                message = transport.read_message()
                if message is None:
                    break

                # Handle message
                response = loop.run_until_complete(server.handle_message(message))

                if response:
                    transport.send_message(response)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)
            raise CommandError(str(e))
        finally:
            loop.run_until_complete(server.close())
            loop.close()


class AsyncCommand(Command):
    """
    Async version of the command using proper async I/O.

    Use this for production deployments with high concurrency.
    """

    def _run_stdio_server(self, account_id, api_key, mode, user_id):
        """Run the MCP server with async stdio transport."""
        from apps.mcp.server import run_stdio_server

        asyncio.run(run_stdio_server(account_id=account_id, api_key=api_key, mode=mode, user_id=user_id))
