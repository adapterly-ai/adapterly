# Core Concepts

This page covers Adapterly's core concepts in depth.

## Systems

A system represents an external service that Adapterly connects to. The hierarchy is:

```
System
  └── Interface (API endpoint)
        └── Resource (data entity)
              └── Action (operation)
```

**Example:**
```
My System
  └── REST API
        └── projects
              ├── list
              ├── get
              └── create
```

### Interface

An interface defines the API basics:
- **Base URL** - API root address
- **Authentication** - How to authenticate
- **Rate limit** - Request limits

### Resource

A resource is an API data entity, such as `projects`, `users`, or `orders`.

### Action

An action is an operation on a resource:
- `list` - List all
- `get` - Get single
- `create` - Create new
- `update` - Update
- `delete` - Delete

Each action with `is_mcp_enabled = true` becomes an MCP tool.

---

## Projects and Project Integrations

### Projects

A **Project** is a scoped workspace that controls which systems and tools are available to AI agents.

- Projects belong to an Account
- Each project has a name, slug, and optional description
- API keys can be bound to a specific project

### Project Integrations

A **ProjectIntegration** links a system to a project:

- Controls which systems are accessible within a project
- Each integration references a specific System
- AI agents with a project-scoped API key can only access systems linked via ProjectIntegration

**Example:**
```
"My Project"
  ├── ProjectIntegration → System A
  ├── ProjectIntegration → System B
  └── ProjectIntegration → Google Sheets
```

---

## API Keys and Modes

### API Keys

MCP API keys authenticate AI agents. Key format: `ak_live_xxx` (production) or `ak_test_xxx` (test).

Each key has:
- **Mode** - Safe (read-only) or Power (read/write)
- **Project** (optional) - Restricts access to a specific project's systems
- **Agent Profile** (optional) - Applies a reusable permission profile
- **is_admin** - Can switch projects via header

### Modes

| Mode | Description |
|------|-------------|
| **Safe** (default) | Only read actions (list, get) are allowed |
| **Power** | All actions allowed (list, get, create, update, delete) |

---

## Permissions and Access Control

### Permission Layers

Access is controlled at multiple levels, intersected together:

```
Effective permissions = Agent policies ∩ Project policies ∩ User policies
```

### Tool Categories

Tools are organized into categories (e.g., `construction.read`, `logistics.write`). Categories are mapped to tools via fnmatch patterns in `ToolCategoryMapping`.

### Agent Profiles

Reusable permission profiles that can be attached to API keys:
- **allowed_categories** - Which tool categories are permitted
- **include_tools** - Explicitly included tools (override categories)
- **exclude_tools** - Explicitly excluded tools
- **mode** - Safe or Power

### User Roles

| Role | Permissions |
|------|-------------|
| **Admin** | Full access: systems, projects, API keys, user management |
| **User** | View projects and systems assigned to them |

---

## Audit Logging

### What is Logged

Every MCP tool call is recorded in the audit log with:
- Timestamp
- API key used
- Tool name and parameters
- Response status and data
- Duration
- Account and project context

### Viewing Logs

- **UI**: MCP Gateway → Audit Log
- **API**: `GET /api/mcp/audit-logs/`

---

## Gateway Architecture

Adapterly supports two deployment modes:

### Monolith (Default)

Everything runs on a single server:
- Django handles UI and REST API
- FastAPI handles MCP protocol (Streamable HTTP)
- PostgreSQL stores all data

### Control Plane + Gateway

For distributed or on-premise deployments:

**Control Plane** (Django at adapterly.ai):
- Manages accounts, systems, adapter definitions
- Provides Gateway Sync API for gateways to pull configuration

**Gateway** (standalone FastAPI + SQLite):
- Runs independently (e.g., on-premise, Docker)
- Syncs adapter specs and API keys from control plane
- Credentials stay on the gateway (never sent to control plane)
- Provides MCP endpoint for AI agents

The `gateway_core` shared package contains executor, crypto, models, auth, and diagnostics code used by both deployment modes.
