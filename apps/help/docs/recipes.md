# Recipes

Ready-to-use MCP usage examples and AI conversation patterns.

## Listing and Filtering Data

### List All Records

```
User: "Show me all my projects"

AI calls: my_system_projects_list()

AI: "Here are your projects:
    1. Project Alpha (active)
    2. Project Beta (active)
    3. Project Gamma (archived)"
```

### Filter by Criteria

```
User: "Show me only active projects created this year"

AI calls: my_system_projects_list()
AI: [filters results by date and status]

AI: "Found 3 active projects created in 2026:
    1. Project Alpha (started Jan 15)
    2. Project Beta (started Feb 3)
    3. Project Gamma (started Mar 1)"
```

---

## Cross-System Queries

### Combine Data from Multiple Systems

```
User: "Compare the project list from System A with data from System B"

AI calls: system_a_projects_list()
AI calls: system_b_items_list(project_id="...")

AI: "Here's a summary:
    - Project Alpha: 5 open items (2 critical)
    - Project Beta: 12 items (all resolved)
    - Project Gamma: 3 open items"
```

---

## Creating and Updating Records

### Create a New Record

```
User: "Create a new item in the Alpha project with coordinates 60.17, 24.94"

AI calls: my_system_items_create(
    project_id="abc-123",
    coordinates=[60.17, 24.94],
    description="New survey point"
)

AI: "Created item at 60.17, 24.94 in Project Alpha.
    ID: item-456-789"
```

### Update Existing Data

```
User: "Update the description of item ITEM-123 to 'Resolved — issue fixed'"

AI calls: my_system_items_update(
    id="ITEM-123",
    description="Resolved — issue fixed"
)

AI: "Updated item ITEM-123 with new description."
```

> **Note:** Create and update operations require **Power mode** on your API key.

---

## Using Safe vs Power Mode

### Safe Mode (Read-Only)

Safe mode is the default. Agents can only read data:

```
User: "List all items"
AI calls: my_system_items_list()  ← Allowed

User: "Create a new item"
AI calls: my_system_items_create(...)  ← Blocked
AI: "I can't create items — my API key is in Safe mode.
    Ask your admin to switch to Power mode if you need write access."
```

### Power Mode (Full Access)

Power mode enables both read and write operations:

```
User: "Create a shipment"
AI calls: my_system_shipments_create(
    sender={...},
    receiver={...},
    packages=[{weight: 5.2, dimensions: "30x20x15"}]
)

AI: "Shipment created successfully. Tracking number: SH-2026-12345"
```

---

## Project-Scoped Access

### Working Within a Project

When your API key is bound to a project, only that project's systems are available:

```
User: "What tools do you have?"

AI: "I have access to tools for the Alpha project:
    - system_a_projects_list, system_a_projects_get
    - system_b_items_list, system_b_items_get
    - google_sheets_sheets_update"
```

### Listing Available Systems

```
User: "Which systems can I query?"

AI: "Based on my API key, I can access:
    1. System A — projects, items, reports
    2. System B — observations, inspections
    3. Google Sheets — spreadsheet data"
```

---

## Pagination and Large Datasets

### Fetching All Pages

```
User: "Get all items from the project — there might be thousands"

AI calls: my_system_items_list(
    project_id="abc-123",
    fetch_all_pages=true
)

AI: "Retrieved 2,847 items across 29 pages.
    Here's a summary by type:
    - Type A: 1,200
    - Type B: 1,647"
```

### Safety Limits

Automatic pagination has built-in safety limits:
- Maximum 100 pages per request
- Maximum 10,000 items
- 2-minute timeout
- Stops on empty or duplicate pages

---

## Audit and Monitoring

### Checking Recent Activity

```
User: "What API calls were made in the last hour?"

[Admin checks MCP Gateway → Audit Log in the UI]

Recent calls:
- my_system_projects_list (safe) — 200 OK — 12:05
- my_system_items_list (safe) — 200 OK — 12:08
- my_system_orders_create (power) — 201 Created — 12:15
```
