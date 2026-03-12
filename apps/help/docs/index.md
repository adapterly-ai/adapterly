# Adapterly Documentation

Welcome to Adapterly - the MCP gateway that connects AI agents to your business systems.

> **New to Adapterly?** Start with the [Getting Started Tutorial](/help/en/tutorial/) for a complete introduction.

## Who is Adapterly for?

- **Teams using AI agents** - Give Claude, ChatGPT, or Cursor access to your business systems
- **System integrators** - Connect APIs and expose them as MCP tools
- **Enterprises** - Centralize system access with audit logging and project scoping

## Quick Start

1. **Add systems** — Create adapters from OpenAPI specs, HAR files, or configure manually
2. **Configure credentials** - Set up OAuth, API keys, or other auth for each system
3. **Create a project** - Scope which systems and tools are available
4. **Generate API key** - Get an `ak_live_xxx` key for MCP access
5. **Connect AI agent** - Point Claude or any MCP client to the gateway

## Concepts at a Glance

| Concept | Description |
|---------|-------------|
| **System** | External service (any REST or GraphQL API) |
| **Interface** | System's API endpoint (REST, GraphQL, XHR) |
| **Resource** | Data entity (projects, users, orders) |
| **Action** | Operation on resource (list, get, create, update) |
| **Project** | Scoped workspace with selected system integrations |
| **API Key** | MCP authentication key (`ak_live_xxx` / `ak_test_xxx`) |
| **MCP Tool** | Auto-generated function for AI agents |

## Documentation Structure

### [Core Concepts](/help/en/concepts/)
Deep dive into systems, projects, permissions, and gateway architecture.

### [Guides](/help/en/guides/)
Step-by-step instructions for adding adapters, configuring credentials, and deploying gateways.

### [Recipes](/help/en/recipes/)
MCP usage examples and AI conversation patterns.

### [MCP & Agents](/help/en/mcp/)
MCP protocol details, connection setup, and agent configuration.

### [Reference](/help/en/reference/)
Adapter data model, MCP JSON-RPC protocol, and API endpoints.

### [Troubleshooting](/help/en/troubleshooting/)
Common errors and their solutions.

---
