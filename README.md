# Adapterly

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![CI](https://github.com/adapterly-ai/adapterly/actions/workflows/ci.yml/badge.svg)](https://github.com/adapterly-ai/adapterly/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Django 5.2](https://img.shields.io/badge/django-5.2-green.svg)](https://www.djangoproject.com/)
[![MCP](https://img.shields.io/badge/MCP-compatible-purple.svg)](https://modelcontextprotocol.io/)

AI-powered MCP gateway for fragmented industries. Create adapters for any REST or GraphQL API, manage them through a web UI, and let AI agents query everything through MCP.

## Features

### Core Capabilities

- **Adapter Generator** — Create adapters from OpenAPI specs, HAR files, or manually via the web UI
- **MCP Gateway** — Native Model Context Protocol support for Claude, ChatGPT, Cursor, and other AI agents
- **Multiple Auth Methods** — OAuth2, API keys, Basic auth, Bearer token, DRF token, browser session (XHR)
- **GraphQL Support** — Native handling for GraphQL APIs alongside REST
- **Project Scoping** — Isolate integrations and credentials per project
- **Gateway Deployment** — Optional standalone gateway for on-premise or edge deployments
- **Confirmation Status** — Adapters start "unconfirmed" until first successful API call proves they work

### Industry Focus

Adapterly is designed for fragmented industries where dozens of specialized systems need to work together:

- **Construction** — Project management, BIM, quality, scheduling, machine control
- **Logistics** — Carriers, freight, multi-carrier platforms
- **ERP** — Enterprise resource planning, accounting, invoicing
- **General** — Collaboration, storage, CRM, analytics

## Architecture

```
AI Agents (Claude, ChatGPT, etc.)
       | (MCP protocol)
       v
┌──────────────────────────────────────┐
│  Adapterly MCP Gateway               │
│  ├── Streamable HTTP (JSON-RPC 2.0)  │
│  ├── System Tools (auto-generated)   │
│  ├── Project Scoping                 │
│  └── Audit Logging                   │
└──────────────────────────────────────┘
       |
       v
┌──────────────────────────────────────┐
│  Adapter Layer                       │
│  ├── REST APIs                       │
│  ├── GraphQL APIs                    │
│  └── Browser Session (XHR)           │
└──────────────────────────────────────┘
       |
       v
External Systems (any REST/GraphQL API)
```

### Deployment Modes

| Mode | Description |
|------|-------------|
| **Monolith** (default) | Django + FastAPI + PostgreSQL on single server |
| **Control Plane + Gateway** | Django control plane at adapterly.ai + standalone FastAPI gateways |

## System Confirmation Status

All adapters have a confirmation status:

| Status | Meaning |
|--------|---------|
| **Unconfirmed** | Adapter built from API docs, awaiting first real test |
| **Confirmed** | Successfully made API call with real credentials |

Confirmation happens automatically when you connect a system and make your first successful API call.

## MCP Tools

### System Tools (Auto-generated)

Tools are generated automatically from adapter definitions stored in the database:

```
{system_prefix}_{resource}_{action}
```

Examples:
- `my_system_projects_list` — List projects
- `my_system_orders_create` — Create an order
- `my_system_items_get` — Get item details

### MCP Modes

| Mode | Description |
|------|-------------|
| **Safe** (default) | Read-only access to all systems |
| **Power** | Full read/write access |

## Quick Start

### 1. Connect to MCP Gateway

Use Streamable HTTP with your API key (`ak_live_xxx`):

```json
{
  "mcpServers": {
    "adapterly": {
      "url": "https://adapterly.ai/mcp/v1/",
      "headers": {
        "Authorization": "Bearer ak_live_xxx"
      }
    }
  }
}
```

### 2. Add Systems

Systems (adapters) are created and managed through the web UI:

1. Go to **Systems** → **Create New System**
2. Use the **Adapter Generator** to import from:
   - **OpenAPI/Swagger spec** — Paste a URL to auto-discover endpoints
   - **HAR file** — Record browser API calls, upload to generate adapter
   - **Manual** — Define endpoints one by one
3. Configure credentials (OAuth, API key, etc.)
4. System becomes "confirmed" after first successful call

### 3. Query with AI

```
User: "Show me all projects"

AI: Using connected system...
    Found 5 projects.
```

## API Structure

```
System (e.g., "My API")
├── Interface (e.g., "api" — REST, GraphQL, XHR)
│   ├── Resource (e.g., "projects")
│   │   ├── Action (e.g., "list", "get", "create")
│   │   └── Action (e.g., "update", "delete")
│   └── Resource (e.g., "items")
│       └── Action (...)
└── AccountSystem (per-account credentials)
```

## Development

### Requirements

- Python 3.10+
- Django 5.2+
- PostgreSQL (or SQLite for dev)
- FastAPI (for MCP server)

### Setup

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### Deployment Modes

Set `DEPLOYMENT_MODE` environment variable:

| Value | Description |
|-------|-------------|
| `monolith` (default) | All-in-one: Django + FastAPI + PostgreSQL |
| `control_plane` | Django control plane with Gateway Sync API |
| `gateway` | Standalone FastAPI gateway (syncs from control plane) |

### Run FastAPI MCP Server

```bash
uvicorn fastapi_app.main:app --reload
```

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

This means:
- You can use, modify, and distribute this software
- If you modify and deploy it as a service, you must share your modifications under AGPL-3.0
- See [LICENSE](LICENSE) for the full license text

### Why AGPL?

We chose AGPL to ensure transparency and prevent closed-source forks while still allowing the community to use, learn from, and contribute to the codebase.
