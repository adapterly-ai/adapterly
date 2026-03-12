# Systems

Systems are external services that Adapterly connects to. They represent APIs, databases, and other data sources your integrations interact with.

## Overview

```
System
  └── Interface (API endpoint)
        └── Resource (data entity)
              └── Action (operation)
```

**Example:**
```
My System (System)
  └── REST API (Interface)
        └── Projects (Resource)
              ├── list (Action)
              ├── get (Action)
              └── create (Action)
```

## Connecting a System

### Method 1: Adapter Wizard (Recommended)

The Adapter Wizard automatically creates system configurations from:

1. **OpenAPI/Swagger Specification**
   - Paste a URL to your API's OpenAPI spec
   - Adapterly discovers all endpoints automatically
   - Review and select which endpoints to import

2. **HAR File**
   - Record API calls in your browser's DevTools
   - Export as HAR file
   - Upload to auto-generate adapter

3. **Manual Configuration**
   - Define endpoints one by one
   - Full control over configuration

**To use the wizard:**
1. Go to **Systems** → **Create New System**
2. Click **Adapter Wizard**
3. Select your source type
4. Follow the guided setup

## Authentication Types

### OAuth 2.0 Password Grant
For systems that use username/password to obtain tokens.

**Configuration:**
- Username (email)
- Password

Adapterly automatically:
- Obtains access tokens
- Caches tokens until expiry
- Refreshes tokens when needed

### API Key
Simple key-based authentication.

**Configuration:**
- API Key value
- Header name (default: `X-API-Key`)

### Bearer Token
Pre-generated access tokens.

**Configuration:**
- Token value

### Basic Authentication
Username and password sent with each request.

**Configuration:**
- Username
- Password

### Session/XHR
For web applications without public APIs.

**Configuration:**
- Session cookie
- CSRF token

## System Configuration

### Interface Settings

| Field | Description |
|-------|-------------|
| Base URL | API root URL (e.g., `https://api.example.com`) |
| Auth Type | Authentication method |
| Rate Limits | Requests per minute/hour |
| Headers | Default headers for all requests |

### Resource Settings

| Field | Description |
|-------|-------------|
| Name | Resource identifier (e.g., `projects`) |
| Description | Human-readable description |

### Action Settings

| Field | Description |
|-------|-------------|
| Method | HTTP method (GET, POST, PUT, DELETE) |
| Path | Endpoint path (e.g., `/v1/projects/{id}`) |
| Parameters | Input schema (JSON Schema) |
| Pagination | Auto-pagination configuration |

## Pagination

For endpoints that return paginated data, configure automatic pagination:

```json
{
  "page_param": "page",
  "size_param": "pageSize",
  "default_size": 100,
  "total_pages_field": "totalPages",
  "last_page_field": "last"
}
```

Use `fetch_all_pages: true` to automatically retrieve all pages.

**Safety limits:**
- Maximum 50 pages per request
- Maximum 10,000 items
- 2-minute timeout

## Testing Connections

1. Go to **Systems** → select your system → **Configure**
2. Enter credentials
3. Click **Test Connection**
4. Green checkmark = success

## MCP Tools

When a system is configured, Adapterly automatically generates MCP tools:

```
{system}_{resource}_{action}
```

**Examples:**
- `my_system_projects_list`
- `my_system_items_create`
- `my_system_reports_get`

These tools can be used by AI agents like Claude for intelligent automation.

## Troubleshooting

### "No interface configured"
The system doesn't have any API interfaces defined. Use the Adapter Wizard to add endpoints.

### "Authentication failed"
Check your credentials in System → Configure. For OAuth systems, ensure username and password are correct.

### "Connection timeout"
The external API is slow or unreachable. Check:
- API is online
- Network allows outbound connections
- Rate limits haven't been exceeded
