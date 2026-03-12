# Reference

Official Adapterly technical reference documentation.

## Adapter Data Model

Adapters are stored in the database and managed through the web UI or Adapter Generator.

### System

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name |
| `alias` | string | URL-safe identifier used in tool names |
| `mcp_prefix` | string | Optional short prefix for tool names (falls back to alias) |
| `industry` | string | Category: construction, logistics, erp, general |
| `website` | string | System's website URL |
| `description` | string | Brief description |
| `confirmation_status` | string | "unconfirmed" (default) or "confirmed" |

### Interface

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name (e.g., "REST API") |
| `alias` | string | Identifier (e.g., "api") |
| `base_url` | string | API root URL |
| `auth_type` | string | api_key, bearer, oauth2_password, basic, drf_token, xhr |
| `rate_limit` | integer | Requests per minute (optional) |

### Resource

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name (e.g., "Projects") |
| `alias` | string | Identifier used in tool names (e.g., "projects") |
| `description` | string | Brief description |

### Action

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name (e.g., "List Projects") |
| `alias` | string | Identifier (e.g., "list") |
| `method` | string | HTTP method: GET, POST, PUT, PATCH, DELETE |
| `path` | string | URL path (e.g., "/projects") |
| `is_mcp_enabled` | boolean | true = exposed as MCP tool |
| `mcp_mode` | string | "safe" (read) or "power" (write) |
| `description` | string | Tool description shown to AI agents |
| `parameters_schema` | JSON | JSON Schema for tool input parameters |
| `output_schema` | JSON | JSON Schema for tool output (optional) |

### Tool Name Generation

```
{mcp_prefix or alias}_{resource_alias}_{action_alias}
```

Example: System with alias `example` generates tools like `example_items_list` (safe) and `example_items_create` (power).

---

## MCP JSON-RPC 2.0 Protocol

Adapterly implements the MCP specification via Streamable HTTP.

### Endpoint

```
POST https://adapterly.ai/mcp/v1/
```

### Authentication

```
Authorization: Bearer ak_live_xxx
```

### Methods

| Method | Description |
|--------|-------------|
| `initialize` | Initialize MCP session, receive capabilities |
| `tools/list` | List all available tools |
| `tools/call` | Call a specific tool |
| `ping` | Health check |

### Initialize

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {
      "name": "my-client",
      "version": "1.0.0"
    }
  }
}
```

### Tools List

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "my_system_projects_list",
        "description": "List all projects",
        "inputSchema": {
          "type": "object",
          "properties": {
            "page": {"type": "integer"},
            "pageSize": {"type": "integer"}
          }
        }
      }
    ]
  }
}
```

### Tools Call

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "my_system_projects_list",
    "arguments": {
      "page": 1,
      "pageSize": 50
    }
  }
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"data\": [...], \"meta\": {\"count\": 5}}"
      }
    ]
  }
}
```

---

## HTTP Endpoints

### MCP Streamable HTTP

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mcp/v1/` | Send JSON-RPC message(s) |
| `GET` | `/mcp/v1/` | Open SSE stream for notifications |
| `DELETE` | `/mcp/v1/` | Close session |

### REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/systems/` | List systems |
| `GET` | `/api/systems/{id}/` | Get system details |
| `POST` | `/api/systems/{id}/test/` | Test system connection |
| `GET` | `/api/mcp/api-keys/` | List API keys |
| `POST` | `/api/mcp/api-keys/` | Create API key |
| `GET` | `/api/mcp/audit-logs/` | List audit logs |
| `GET` | `/api/mcp/agent-profiles/` | List agent profiles |

### Gateway Sync API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/gateway-sync/v1/register` | Register a gateway |
| `GET` | `/gateway-sync/v1/specs` | Sync adapter specs |
| `GET` | `/gateway-sync/v1/keys` | Sync API keys |
| `POST` | `/gateway-sync/v1/audit` | Push audit logs |
| `POST` | `/gateway-sync/v1/health` | Push health status |

---

## Error Codes

### MCP JSON-RPC Errors

| Code | Name | Description |
|------|------|-------------|
| `-32700` | Parse error | Invalid JSON |
| `-32600` | Invalid request | Missing required fields |
| `-32601` | Method not found | Unknown MCP method |
| `-32602` | Invalid params | Wrong parameter types or missing required params |
| `-32603` | Internal error | Server error during tool execution |

### HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| `400` | Bad request | Check parameters |
| `401` | Unauthorized | Check API key |
| `403` | Forbidden | Check permissions / mode |
| `404` | Not found | Check resource ID/path |
| `429` | Rate limit | Wait and retry |
| `500` | Server error | Retry later |
