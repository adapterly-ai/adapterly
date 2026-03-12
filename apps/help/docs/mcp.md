# MCP Integration

Adapterly acts as an MCP (Model Context Protocol) server, giving AI agents access to your connected business systems as callable tools.

## What is MCP?

The Model Context Protocol (MCP) is a standard that allows AI assistants like Claude, ChatGPT, and Cursor to use external tools. Adapterly implements MCP via Streamable HTTP (JSON-RPC 2.0).

## How It Works

```
AI Agent (Claude, ChatGPT, etc.)
    | (MCP JSON-RPC 2.0)
    v
Adapterly MCP Gateway
    | (authenticated API calls)
    v
External Systems (any REST/GraphQL API)
```

1. AI agent connects to Adapterly's MCP endpoint
2. Agent discovers available tools via `tools/list`
3. Agent calls tools via `tools/call`
4. Adapterly authenticates, calls the external API, and returns results
5. Every call is logged in the audit log

## Available Tools

### System Tools (Auto-generated)

For each configured system, Adapterly generates MCP tools:

```
{system}_{resource}_{action}
```

**Example tools:**
- `my_system_projects_list` — List all projects
- `my_system_projects_get` — Get project details
- `my_system_items_create` — Create items
- `my_system_reports_get` — Get reports

### Management Tools

Account and session management (available based on API key permissions):

| Tool | Type | Description |
|------|------|-------------|
| `account_get` | read | Get account details |
| `admin_session_create` | write | Create federated login session |

## MCP Modes

### Safe Mode (Default)

- Read operations allowed (list, get)
- Write operations blocked (create, update, delete)

### Power Mode

- All operations allowed
- Required for write operations
- Enable via API key settings or Agent Profile

## Setting Up MCP

### 1. Generate API Key

1. Go to **MCP Gateway** → **API Keys**
2. Click **Create API Key**
3. Select an Agent Profile (optional) or set mode manually
4. Copy the key (`ak_live_xxx`) - it won't be shown again

### 2. Connection Options

#### Option A: Streamable HTTP (Recommended)

MCP Streamable HTTP - single endpoint for all JSON-RPC communication:

```
Endpoint: https://adapterly.ai/mcp/v1/
```

**Methods:**
- `POST /mcp/v1/` - Send JSON-RPC message(s)
- `GET /mcp/v1/` - Open SSE stream for server notifications (optional)
- `DELETE /mcp/v1/` - Close session

**Headers:**
- `Authorization: Bearer <api_key>`
- `Content-Type: application/json`
- `Accept: application/json` or `text/event-stream`
- `Mcp-Session-Id: <session_id>` (returned by server, use for subsequent requests)

**Example:**
```javascript
// Send JSON-RPC message
const response = await fetch('https://adapterly.ai/mcp/v1/', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer ak_live_xxx',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/list',
    params: {}
  })
});

// Get session ID from response header
const sessionId = response.headers.get('Mcp-Session-Id');
const result = await response.json();

// Use session ID for subsequent requests
const response2 = await fetch('https://adapterly.ai/mcp/v1/', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer ak_live_xxx',
    'Content-Type': 'application/json',
    'Mcp-Session-Id': sessionId
  },
  body: JSON.stringify({
    jsonrpc: '2.0',
    id: 2,
    method: 'tools/call',
    params: { name: 'my_system_projects_list', arguments: {} }
  })
});
```

#### Option B: Claude Desktop / Claude Code

Configure your MCP client to connect via Streamable HTTP:

**Claude Desktop** (`claude_desktop_config.json`):
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

**Claude Code** (`.claude/settings.json`):
```json
{
  "mcpServers": {
    "adapterly": {
      "type": "url",
      "url": "https://adapterly.ai/mcp/v1/",
      "headers": {
        "Authorization": "Bearer ak_live_xxx"
      }
    }
  }
}
```

#### Option C: Standalone Gateway

For on-premise deployments, connect to a local gateway instance:

```json
{
  "mcpServers": {
    "adapterly": {
      "url": "http://localhost:8080/mcp/v1/",
      "headers": {
        "Authorization": "Bearer ak_live_xxx"
      }
    }
  }
}
```

### 3. Verify Connection

Ask your AI agent:
> "What Adapterly tools do you have access to?"

The agent should list all available system tools.

## Tool Parameters

Each tool has specific parameters based on its action:

### List Actions
```json
{
  "page": 1,
  "pageSize": 100,
  "fetch_all_pages": true
}
```

### Get Actions
```json
{
  "id": "project-uuid-here"
}
```

### Create Actions
```json
{
  "data": {
    "name": "New Project",
    "description": "Project description"
  }
}
```

## Pagination

For list endpoints with many items, Adapterly handles pagination automatically:

```
User: "Get all items from the project"

AI calls: my_system_items_list(
    project_id="...",
    fetch_all_pages=true
)
```

**Safety limits:**
- Maximum 100 pages
- Maximum 10,000 items
- 2-minute timeout
- Stops on empty or duplicate pages

## Error Handling

When an MCP tool fails, the agent receives error details:

```json
{
  "error": true,
  "message": "Authentication failed",
  "details": "Token expired or invalid"
}
```

The agent will typically:
1. Explain the error to the user
2. Suggest remediation steps
3. Retry if appropriate

## Best Practices

### 1. Be Specific in Requests
Instead of "get project data", say "list all active projects from System X".

### 2. Provide Context
Give the agent the information it needs:
> "Using project ID abc123, create a logpoint at coordinates 60.17, 24.94"

### 3. Review Before Writing
Ask the agent to show you what it will create before actually creating it:
> "Show me the logpoint data you would create, but don't create it yet"

## Security

### API Key Permissions
API keys are scoped by mode (safe/power), project, and Agent Profile. Use the minimum access needed.

### Audit Trail
All MCP tool calls are logged and visible in MCP Gateway → Audit Log.

### Rate Limiting
MCP calls are subject to the same rate limits as direct API access.
