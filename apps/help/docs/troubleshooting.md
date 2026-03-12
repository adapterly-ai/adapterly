# Troubleshooting

Common errors and their solutions.

## MCP Connection Errors

### "Tool not found"

**Cause:** MCP tool not registered or no permissions.

**Fix:**
1. Check that the system is configured in Adapterly
2. Verify the system has resources with `is_mcp_enabled: true`
3. Check that the system is included in the project's integrations
4. Verify the API key has access (check mode and Agent Profile)
5. Restart your AI agent / MCP client to refresh the tool list

### "Authentication failed" (401)

**Cause:** Invalid or expired API key.

**Fix:**
1. Verify your API key starts with `ak_live_` or `ak_test_`
2. Check the key hasn't been revoked in MCP Gateway → API Keys
3. Ensure the `Authorization: Bearer` header is correctly set
4. Generate a new key if needed

### "Permission denied" (403)

**Cause:** API key doesn't have permission for this operation.

**Fix:**
1. Check the API key **mode**: Safe mode blocks write operations
2. Check the **Agent Profile** attached to the key
3. Check **Project policies** if the key is project-scoped
4. Switch to Power mode for create/update/delete operations

### "System credentials not configured"

**Cause:** No credentials set for the target system in this account.

**Fix:**
1. Go to **Systems** → select the system → **Configure**
2. Enter credentials (API key, OAuth, Bearer token, etc.)
3. Click **Test Connection** to verify
4. The system becomes "confirmed" after first successful call

---

## External API Errors

### "Timeout"

**Cause:** External API not responding in time.

**Fix:**
1. Check the target API's status page
2. Try a smaller request (reduce `pageSize`, don't use `fetch_all_pages`)
3. Check network connectivity
4. Retry after a brief wait

### "Rate limit exceeded" (429)

**Cause:** Too many requests to external API in short time.

**Fix:**
1. Wait before retrying
2. Reduce request frequency
3. Use pagination with smaller page sizes

### External API returns error (400, 404, 500)

**Cause:** Issue with the request parameters or the external service.

**Fix:**
1. Check the error message in the MCP tool response
2. Verify the parameters (IDs, formats) are correct
3. Check if the external API has changed (new version, deprecated endpoints)
4. View details in MCP Gateway → Audit Log

---

## MCP JSON-RPC Errors

| Code | Name | Cause | Fix |
|------|------|-------|-----|
| `-32700` | Parse error | Invalid JSON in request | Check JSON syntax |
| `-32600` | Invalid request | Missing `jsonrpc`, `method`, or `id` | Include all required fields |
| `-32601` | Method not found | Unknown MCP method | Use: `initialize`, `tools/list`, `tools/call`, `ping` |
| `-32602` | Invalid params | Wrong parameter types | Check tool's `inputSchema` |
| `-32603` | Internal error | Server error during execution | Check audit log, retry |

---

## HTTP Error Reference

| Code | Meaning | Action |
|------|---------|--------|
| 400 | Bad request | Check request parameters |
| 401 | Unauthorized | Check API key / credentials |
| 403 | Forbidden | Check permissions and mode |
| 404 | Not found | Check resource ID or path |
| 429 | Rate limit | Wait and retry |
| 500 | Server error | Retry later |
| 502/503 | Service unavailable | Check API status |
| 504 | Gateway timeout | External API slow, retry |

---

## Debugging Checklist

### 1. Check Audit Log

1. Go to **MCP Gateway** → **Audit Log**
2. Find the failed call by timestamp
3. Review request parameters and response details
4. Check the error message and HTTP status code

### 2. Verify System Credentials

1. Go to **Systems** → select system → **Configure**
2. Click **Test Connection**
3. If failed, update credentials and retry

### 3. Check API Key Configuration

1. Go to **MCP Gateway** → **API Keys**
2. Verify the key is active (not revoked)
3. Check mode (Safe/Power)
4. Check project binding and Agent Profile

### 4. Check Project Integrations

1. Go to **Projects** → select project
2. Verify the system is listed in Project Integrations
3. Check allowed categories

### 5. Gateway Logs (Standalone Gateway)

For Docker gateway deployments:
```bash
docker compose logs -f gateway
```

---

## Contact Support

If issue persists:

1. Gather information:
   - API key ID (not the key itself)
   - Audit log entry / request ID
   - Complete error message
   - What you tried to do
   - When issue started

2. Contact:
   - In-app support
   - Email: support@adapterly.ai
