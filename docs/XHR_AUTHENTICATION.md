# XHR Interface Authentication Guide

## Overview

XHR (XMLHttpRequest) interfaces require browser session authentication instead of API tokens. This guide explains how to configure and use XHR interfaces with session cookies and CSRF tokens.

---

## 🔐 What is XHR Authentication?

**XHR Authentication** uses:
- ✅ **Session Cookie** (e.g., `JSESSIONID`) - Maintains authenticated session
- ✅ **CSRF Token** - Prevents cross-site request forgery
- ✅ **Origin Header** - Identifies request source
- ✅ **Referer Header** - Shows where request came from
- ✅ **X-Requested-With** - Identifies AJAX requests

**Use XHR for:**
- Internal web application APIs that use session/cookie authentication
- Browser-only authenticated endpoints
- Systems without public API

---

## 📋 Setup Steps

### Step 1: Create XHR Interface

1. Go to **Systems** → Select your system
2. Click **Interfaces** → **Create Interface**
3. Fill in:
   - **Name**: `xhr` or `internal_api`
   - **Type**: **XHR**
   - **Base URL**: `https://app.example.com/api`
   - **Requires Browser**: ✅ Check this

### Step 2: Get Session Cookie

#### Option A: Copy from Browser

1. Open the target website (e.g., `https://app.example.com`)
2. **Log in** normally
3. Open **Developer Tools** (F12)
4. Go to **Application** tab (Chrome) or **Storage** tab (Firefox)
5. Click **Cookies** in the left sidebar
6. Find your session cookie (usually `JSESSIONID`, `PHPSESSID`, etc.)
7. **Copy the full cookie**:
   ```
   JSESSIONID=00C74BC43767F2D269EEF70E03A33F80
   ```

#### Option B: From Network Tab

1. Open **Developer Tools** (F12)
2. Go to **Network** tab
3. Perform any action (click something on the site)
4. Click on any request
5. Look at **Request Headers**
6. Find **Cookie** header
7. Copy the relevant session cookie

### Step 3: Get CSRF Token

#### Method 1: From Request Headers

1. In **Network** tab, click any request
2. Look at **Request Headers**
3. Find **X-CSRF-TOKEN** header
4. Copy the value

#### Method 2: From Cookie

1. In **Application** → **Cookies**
2. Look for `XSRF-TOKEN` or `csrf-token`
3. Copy the value

### Step 4: Configure in System

1. Go to **Systems** → **Configure** your system
2. Scroll to **Browser Session Authentication (XHR)**
3. Paste values:
   - **Session Cookie**: `JSESSIONID=00C74BC43767F2D269EEF70E03A33F80`
   - **CSRF Token**: `your-csrf-token-here`
   - **Session Expires At**: (Optional) When the session will expire
4. Click **Save Configuration**

---

## 🚀 Usage in Integrations

### Example: Session-Based API Call

```json
{
  "version": 3,
  "pipeline": [
    {
      "type": "read_data",
      "parameters": {
        "system_alias": "my_system",
        "interface_alias": "xhr",
        "resource_alias": "ajax_project_change",
        "action_alias": "change",
        "params": {
          "projectId": 12345
        },
        "save_as": "change_result"
      }
    },
    {
      "type": "message",
      "parameters": {
        "title": "Project Changed",
        "message": "Successfully changed to project 12345"
      }
    }
  ]
}
```

---

## 🔍 How It Works

### Backend Request Headers

When you configure XHR authentication, the backend automatically adds:

```python
headers = {
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': 'https://app.example.com',
    'Referer': 'https://app.example.com/',
    'X-CSRF-TOKEN': 'your-csrf-token',
    'Content-Type': 'application/x-www-form-urlencoded'  # For POST
}

cookies = {
    'JSESSIONID': '00C74BC43767F2D269EEF70E03A33F80'
}
```

### Why Origin is Not a Problem

**Question**: "Won't the server reject requests from a different origin?"

**Answer**: **No!** Because:
1. **CORS is a browser security feature** - Browsers enforce it, not servers
2. **Backend requests can set any Origin header** - We set it to match the expected value
3. **Server only checks the header value** - Not the actual IP or domain
4. **Cookies + CSRF token authenticate the request** - Server trusts these

---

## ⚠️ Important Notes

### Session Expiry

Session cookies **expire** after:
- ❌ User logs out
- ❌ Session timeout (usually 30-60 minutes of inactivity)
- ❌ Server restart (sometimes)

**Solution**: When session expires, you need to:
1. Log in to the site again in your browser
2. Copy the new session cookie
3. Update the configuration in **Systems → Configure**

### Security

- 🔒 **Session cookies are sensitive** - Don't share them
- 🔒 **Anyone with your cookie can impersonate you** - Keep it secure
- 🔒 **Set expiry date** - Track when you need to refresh
- 🔒 **Use in safe environments only** - Don't use on public servers

### Multiple Cookies

If the site uses multiple cookies, include them all:

```
JSESSIONID=ABC123; _lfa=XYZ789; user_prefs=DEF456
```

---

## 🧪 Testing

Use the **Action Testing** feature to test XHR endpoints:

1. Go to **Systems** → **Resources** → **Actions**
2. Click **🎯 Test** on your XHR action
3. Enter test parameters:
   ```json
   {
     "projectId": 12345
   }
   ```
4. Click **Run Test**

**Expected Result**: ✅ Success with response data

**If it fails:**
- ❌ Check session cookie is valid (not expired)
- ❌ Check CSRF token is correct
- ❌ Try logging in again and getting fresh cookies

---

## 📝 Action Configuration

### POST Request Example

For `ajax_change_project.json`:

- **Method**: `POST`
- **Path**: `/ajax_change_project.json`
- **Headers**:
  ```json
  {
    "Content-Type": "application/x-www-form-urlencoded"
  }
  ```
- **Parameters Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "projectId": {
        "type": "integer"
      }
    }
  }
  ```

### GET Request Example

For `ajax_get_data.json`:

- **Method**: `GET`
- **Path**: `/ajax_get_data.json`
- **Parameters**: Added to query string automatically

---

## 🛠️ Troubleshooting

### "401 Unauthorized"

**Cause**: Session expired or invalid cookie

**Fix**:
1. Log in to the site in your browser
2. Copy fresh session cookie
3. Update configuration

### "403 Forbidden"

**Cause**: CSRF token mismatch

**Fix**:
1. Get fresh CSRF token from browser
2. Update configuration

### "Origin header mismatch"

**Cause**: Interface base URL is incorrect

**Fix**:
1. Verify base URL matches exactly (including protocol)
2. Update interface configuration

### "CORS error"

**This should NOT happen** - CORS is a browser restriction. Backend requests don't have CORS issues.

If you see this, it means you're testing from browser JavaScript, not from the backend.

---

## 💡 Best Practices

1. **Use a dedicated test account** - Don't use your personal session
2. **Monitor session expiry** - Set reminders to refresh
3. **Test first** - Use Action Testing before using in integrations
4. **Document which cookies are needed** - Add notes in system description
5. **Check expiry regularly** - Failed integrations might mean expired sessions

---

## 🆚 XHR vs API

| Feature | XHR | API |
|---------|-----|-----|
| Authentication | Session Cookie | Bearer Token |
| CSRF Protection | Required | Not needed |
| Expiry | Minutes/Hours | Days/Weeks |
| Setup | Copy from browser | Get from system settings |
| Maintenance | Refresh often | Rarely |
| Security | User-specific | Service-level |

**Rule of thumb**: Use API when available. Use XHR only when no API exists.

---

## 🎓 Advanced: Multiple Sessions

If you need multiple user sessions (different users):

1. Create separate `AccountSystem` configurations
2. Each with different session cookies
3. Use in different integrations

---

## Related Documentation

- [System Configuration](./SYSTEM_CONFIGURATION.md)
- [Action Testing](./ACTION_TESTING.md)

