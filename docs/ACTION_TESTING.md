# Action Testing Guide

## Overview

The Action Testing feature allows administrators to test system actions directly from the UI before using them in integrations. This helps verify credentials, test API endpoints, and debug integration issues.

## Features

✅ **Test any action** with custom parameters  
✅ **View real API responses** in formatted JSON  
✅ **Load example parameters** for quick testing  
✅ **See detailed error messages** with tracebacks  
✅ **Parameter schema reference** displayed on the side  
✅ **Response metadata** (count, type) for quick validation  

---

## How to Test an Action

### 1. Navigate to Actions List

1. Go to **Systems** → **Dashboard**
2. Click on a configured system
3. Go to **Resources** → Select a resource
4. Click **Actions** to see the action list

### 2. Click "Test" Button

Each action now has a **🎯 Test** button next to the Edit button.

### 3. Enter Test Parameters

On the test page, you'll see:

- **Action details**: Name, alias, method, path
- **Parameters textarea**: Enter JSON parameters
- **Examples**: Click to load pre-defined examples
- **Parameter schema**: Reference for required fields (right sidebar)

**Example parameters:**

```json
{
  "projectId": 12345,
  "limit": 10,
  "status": "active"
}
```

### 4. Run the Test

Click **🎯 Run Test** to execute the action.

### 5. View Results

**On Success:**
- ✅ Success message
- Result count (for lists)
- Result type (list, dict, etc.)
- Formatted JSON response (first 5 items for large lists)

**On Error:**
- ❌ Error message
- Error type
- Full traceback (expandable)

---

## Use Cases

### 1. **Verify System Configuration**

Test basic actions (e.g., "list projects") to ensure:
- API credentials are correct
- Base URL is accessible
- Authentication works

### 2. **Debug Integration Issues**

If an integration fails on a specific action:
- Test the action with the same parameters
- See the actual API response
- Identify parameter format issues

### 3. **Explore API Capabilities**

Before building integrations:
- Test different parameters
- See what data is returned
- Understand API structure

### 4. **Validate Action Configuration**

After configuring a new action:
- Test it immediately
- Verify path interpolation works
- Check parameter schema is correct

---

## Technical Details

### How It Works

1. **Test endpoint**: `/systems/actions/<action_id>/test/`
2. **Method**: GET (show form) | POST (execute test)
3. **Execution**: Uses `read_data` from `apps.runs.libraries.tools`
4. **Context**: Creates a minimal fake run context
5. **Response**: JSON with result, errors, and metadata

### Response Format

**Success:**

```json
{
  "success": true,
  "message": "Action executed successfully",
  "result": [...],
  "result_count": 6,
  "result_type": "list"
}
```

**Error:**

```json
{
  "success": false,
  "error": "Connection timeout",
  "error_type": "TimeoutError",
  "traceback": "Full Python traceback..."
}
```

### Security

- ✅ Only **admin users** can test actions
- ✅ System must be **configured** for the account
- ✅ System must be **enabled**
- ✅ Real credentials are used (test in safe environment)

---

## Tips

### 1. Start with Examples

If the action has examples, click **"Example 1"** to load pre-configured parameters.

### 2. Use the Schema

Check the **Parameter Schema** in the right sidebar for:
- Required fields
- Data types
- Valid values

### 3. Test with Small Datasets

For list actions, add `"limit": 5` to avoid huge responses.

### 4. Check Credentials First

If tests fail:
1. Go to **Systems** → **Configure**
2. Verify API key/token is correct
3. Test connection first

### 5. Copy Parameters to Integrations

Once you find working parameters, copy them directly to your integration configuration:

```json
{
  "system_alias": "my_system",
  "resource_alias": "project",
  "action_alias": "list",
  "params": {
    "status": "active",
    "limit": 10
  }
}
```

---

## Troubleshooting

### "System not configured"

**Problem**: Action test page redirects to configuration.  
**Solution**: Configure the system first in **Systems → Configure**.

### "Invalid JSON parameters"

**Problem**: JSON syntax error in parameters.  
**Solution**: Use a JSON validator or click an example to load valid JSON.

### "Connection timeout"

**Problem**: API is slow or unreachable.  
**Solution**: 
- Check base URL in interface configuration
- Verify network connectivity
- Increase timeout in interface settings

### "Authentication failed"

**Problem**: API credentials are invalid.  
**Solution**: 
- Re-enter credentials in **Systems → Configure**
- Check if API key has expired
- Verify permissions in the external system

---

## Examples

### Example 1: Test Project List Action

1. Go to **Systems → [Your System] → Resources → project → Actions**
2. Click **Test** on "list" action
3. Enter parameters:
   ```json
   {
     "archived": false
   }
   ```
4. Click **Run Test**
5. See all non-archived projects

### Example 2: Test with Pagination

```json
{
  "limit": 5,
  "offset": 0
}
```

### Example 3: Test with Filters

```json
{
  "projectId": 12345,
  "status": "active",
  "from_date": "2024-01-01"
}
```

---

## Benefits

- 🚀 **Faster Development**: Test integrations before deploying them
- 🐛 **Better Debugging**: See exact API responses and errors
- ✅ **Validation**: Verify system configuration works
- 📚 **Learning Tool**: Explore API capabilities interactively
- 🔒 **Safe Testing**: Test with real data without affecting live integrations

---

## Related Documentation

- [System Configuration](./SYSTEM_CONFIGURATION.md)
- [API Integration Guide](./API_INTEGRATION.md)

