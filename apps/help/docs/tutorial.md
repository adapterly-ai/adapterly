# Getting Started with Adapterly

Welcome to Adapterly! This tutorial will help you understand what Adapterly is, how it works, and how to connect your first system.

---

## What is Adapterly?

**Adapterly** is an MCP (Model Context Protocol) gateway that connects AI agents to external business systems. It turns REST APIs, GraphQL endpoints, and web services into MCP tools that AI agents like Claude, ChatGPT, and Cursor can use directly.

### Key Benefits

| Benefit | Description |
|---------|-------------|
| **Adapter Generator** | Create adapters from OpenAPI specs, HAR files, or manually |
| **MCP native** | Standard protocol supported by Claude, ChatGPT, Cursor, and others |
| **Project scoping** | Isolate integrations and control access per project |
| **Audit logging** | Every tool call is logged with full request/response details |
| **Secure** | Credentials stored encrypted, category-based access control |

### Common Use Cases

- **Cross-system queries** — Ask AI to combine data from multiple systems
- **Data entry automation** — Let AI create records in connected systems
- **Project management** — Query project data through natural language
- **Logistics tracking** — Check shipments and orders via AI

---

## How Adapterly Works

Adapterly follows a simple architecture:

```
System (e.g., My API)
  └── Interface (e.g., REST API)
        └── Resource (e.g., "projects")
              └── Action (e.g., "list", "get", "create")
                    └── MCP Tool (e.g., "my_api_projects_list")
```

Each system's resources and actions are automatically converted into MCP tools that AI agents can discover and call.

### Tool Naming

Tools follow the pattern: `{system_prefix}_{resource_alias}_{action_alias}`

Examples:
- `my_system_projects_list` — List all projects
- `my_system_items_get` — Get a specific item
- `my_system_orders_create` — Create an order

---

## Quick Start Guide

### Step 1: Create Adapters

Systems are created and managed through the web UI:

1. Go to **Systems** → **Create New System**
2. Use the **Adapter Generator** to import from:
   - **OpenAPI/Swagger spec** — Auto-discover all endpoints
   - **HAR file** — Record browser API calls, upload to generate adapter
   - **Manual** — Define endpoints one by one
3. Review and enable the endpoints you need

### Step 2: Configure Credentials

1. Go to **Systems** → select your system → **Configure**
2. Enter credentials based on the system's auth type:
   - **OAuth 2.0** — Client ID, secret, token URL
   - **API Key** — Key value and header name
   - **Bearer Token** — Pre-generated access token
   - **DRF Token** — Username and password (token auto-generated)
3. Click **Test Connection** to verify

### Step 3: Create a Project

1. Go to **Projects** → **Create New**
2. Give the project a name
3. Add **Project Integrations** — select which systems this project can access
4. Optionally restrict by tool categories

### Step 4: Generate an API Key

1. Go to **MCP Gateway** → **API Keys**
2. Click **Create API Key**
3. Choose mode:
   - **Safe** (default) — Read-only access
   - **Power** — Full read/write access
4. Optionally bind to a specific project
5. Copy the key (`ak_live_xxx`) — it won't be shown again

### Step 5: Connect Your AI Agent

Configure your MCP client with the Streamable HTTP endpoint:

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

Ask your AI agent: *"What Adapterly tools do you have access to?"*

---

## Example: Using System Tools

Here's what a typical interaction looks like:

```
User: "Show me all my projects"

AI calls: my_system_projects_list()

AI: "Here are your 5 projects:
    1. Project Alpha (active)
    2. Project Beta (active)
    3. Project Gamma (archived)
    ..."
```

```
User: "Get the details for Project Alpha"

AI calls: my_system_projects_get(id="abc-123")

AI: "Project Alpha:
    - Status: Active
    - Created: 2026-01-15
    - Members: 8
    ..."
```

---

## Security

- **API keys** control access — each key can be scoped to a project and mode
- **Agent Profiles** define reusable permission sets (allowed categories, included/excluded tools)
- **Audit logging** records every MCP tool call with timestamps, parameters, and results
- **Category-based access control** — tools are grouped into categories, policies restrict access at agent, project, and user levels

---

## Best Practices

1. **Start with Safe mode** — Use read-only access until you're confident in the setup
2. **Scope projects tightly** — Only include the systems each project actually needs
3. **Use Agent Profiles** — Create reusable profiles instead of configuring each key individually
4. **Monitor audit logs** — Review tool calls regularly for unexpected activity
5. **Rotate keys** — Regenerate API keys periodically

---

## Next Steps

1. **[Core Concepts](/help/en/concepts/)** — Understand projects, permissions, and gateway architecture
2. **[Guides](/help/en/guides/)** — Step-by-step instructions for specific tasks
3. **[Recipes](/help/en/recipes/)** — MCP usage examples and conversation patterns
4. **[MCP & Agents](/help/en/mcp/)** — Protocol details and connection setup
