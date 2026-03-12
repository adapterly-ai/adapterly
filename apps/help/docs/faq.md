# Frequently Asked Questions

## General

### What is Adapterly?
Adapterly is an MCP (Model Context Protocol) gateway that connects AI agents to external business systems. Create adapters for any REST or GraphQL API through the web UI, and let AI agents like Claude, ChatGPT, and Cursor query and manage your data.

### Who is Adapterly for?
- Teams using AI agents who need access to business systems
- System integrators connecting multiple APIs
- Enterprises managing data across platforms with audit and access control
- Construction, logistics, and ERP professionals

### How is Adapterly different from a regular API gateway?
Adapterly speaks the MCP protocol natively. AI agents can discover available tools, understand their parameters, and call them directly. No custom integration code needed - just connect your systems and give the agent an API key.

## Systems

### How do I connect a new system?
1. Go to **Systems** → **Create New System** or select an existing one
2. Use the **Adapter Generator** to import from OpenAPI specs, HAR files, or configure manually
3. Go to **Configure** and enter credentials (API key, OAuth, etc.)
4. Click **Test Connection** — the system becomes "confirmed" after first successful call

### What authentication methods are supported?
- OAuth 2.0 (password grant, client credentials)
- API Key (custom header)
- Bearer Token
- Basic Authentication
- DRF Token (username/password → auto-generated token)
- Session/Cookie (XHR for web apps)

### Why does my connection test fail?
Common causes:
- Incorrect credentials (wrong key, expired token)
- API endpoint is down or unreachable
- Network/firewall restrictions
- Rate limiting from the external API

Check the error message for specific details.

### Can I add a custom system?
Yes! Use the **Adapter Generator** to create adapters from OpenAPI specs, HAR files, or configure endpoints manually through the web UI. See the [Guides](/help/en/guides/) for details.

## MCP & AI Agents

### What is MCP?
Model Context Protocol (MCP) is a standard for AI assistants to use external tools. Adapterly acts as an MCP server, giving AI agents access to your connected systems via Streamable HTTP (JSON-RPC 2.0).

### Which AI agents work with Adapterly?
Any MCP-compatible client, including:
- Claude (Desktop and Code)
- ChatGPT (with MCP support)
- Cursor
- Custom agents using MCP libraries

### How do I connect Claude to Adapterly?
1. Generate an API key in MCP Gateway → API Keys
2. Add to your Claude configuration:
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
3. Ask Claude: "What Adapterly tools do you have?"

### What's the difference between Safe and Power mode?
- **Safe mode** (default): Read-only - agents can list and get data but can't create, update, or delete
- **Power mode**: Full access - agents can perform all operations including writes

### Is my data safe with AI access?
- All MCP calls are authenticated via API keys
- Access is controlled by mode, Agent Profile, and project scoping
- Every tool call is logged in the audit log with full details
- You can revoke API keys instantly
- Credentials are stored encrypted

### What can AI agents do vs. what requires manual setup?
AI agents can:
- Read data from configured systems
- Create/update/delete data (with Power mode)
- Query across multiple systems

AI agents cannot:
- Configure new systems or credentials
- Manage API keys or permissions
- Access systems without configured credentials

## Projects

### What are Projects?
Projects are scoped workspaces that control which systems are available to AI agents. Each project has its own set of system integrations and access policies.

### Do I need to create a project?
Projects are optional. If your API key isn't bound to a project, the agent can access all systems in your account. Projects are useful for:
- Restricting access to specific systems per use case
- Organizing integrations by business context
- Applying different permission policies

## Gateway Deployment

### Can I run Adapterly on my own server?
Yes. Adapterly supports a standalone gateway mode (Docker) that runs on your infrastructure. The gateway syncs adapter definitions from the control plane but keeps credentials locally.

### What's the difference between monolith and gateway mode?
- **Monolith**: Everything on one server (Django + FastAPI + PostgreSQL)
- **Control Plane + Gateway**: Central management at adapterly.ai, with standalone gateways on your servers. Credentials stay on the gateway.

### How do I deploy a standalone gateway?
1. Run `docker compose up -d` in the `adapterly-gateway/` directory
2. Open the Setup Wizard at `http://your-host:8080/setup/`
3. Register with the control plane and configure credentials
4. Point your AI agents to `http://your-host:8080/mcp/v1/`

## Account & Team

### How do I add team members?
Go to **Account Settings** → **Invite User** and enter their email address.

### What permissions can team members have?
- **Admin** - Full access including system configuration and API key management
- **User** - View projects and use assigned integrations

## Getting Help

### Where can I report bugs?
Contact support through the application or email support@adapterly.ai.

### Can I request new features or adapters?
Yes! Submit feature requests through the support channel or contribute directly on GitHub.
