"""
MCP Audit and session models.
"""

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from apps.accounts.models import Account

User = get_user_model()


class ProjectIntegration(models.Model):
    """
    Links a Project to a System with workspace-scoped credentials and external ID.

    Every integration defines:
    - Which system is enabled for the project
    - The external project identifier in the target system
    Credentials are always workspace-scoped (project-level AccountSystem).
    """

    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="integrations")
    system = models.ForeignKey("systems.System", on_delete=models.CASCADE, related_name="project_integrations")
    external_id = models.CharField(
        max_length=500, blank=True, help_text='External project identifier in the target system (e.g., Jira "PROJ-123")'
    )
    is_enabled = models.BooleanField(default=True)
    allowed_actions = models.JSONField(
        null=True,
        blank=True,
        help_text="List of allowed tool names (e.g. ['aiforsite_images_list']). Null = all tools allowed.",
    )
    custom_config = models.JSONField(
        default=dict, blank=True, help_text="Additional integration-specific configuration"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["system__alias"]
        verbose_name = "Project Integration"
        verbose_name_plural = "Project Integrations"

    def __str__(self):
        return f"{self.project.slug}:{self.system.alias}"


class MCPAuditLog(models.Model):
    """
    Audit log for all MCP tool calls.
    Provides traceability and compliance for agent actions.

    Enhanced with reasoning capture for "why did the AI do this" explanations.
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="mcp_audit_logs")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="mcp_audit_logs")

    # Tool call details
    tool_name = models.CharField(max_length=255, db_index=True)
    tool_type = models.CharField(
        max_length=50,
        choices=[
            ("system_read", "System Tool (Read)"),
            ("system_write", "System Tool (Write)"),
            ("resource", "Resource Access"),
            ("context", "Context Tool"),
            ("analyzer", "Analyzer Tool"),
        ],
    )
    parameters = models.JSONField(default=dict)
    result_summary = models.JSONField(default=dict)

    # Execution metrics
    duration_ms = models.IntegerField(default=0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)

    # AI Reasoning capture - "Why did the AI do this?"
    reasoning = models.TextField(
        blank=True, help_text="AI agent reasoning for this action (optional, from agent context)"
    )
    intent = models.CharField(
        max_length=500, blank=True, help_text='High-level intent of this action (e.g., "Retrieve customer data")'
    )
    context_summary = models.TextField(
        blank=True, help_text="Summary of conversation/task context leading to this action"
    )

    # Rollback support
    is_reversible = models.BooleanField(default=False, help_text="Whether this action can be rolled back")
    rollback_data = models.JSONField(default=dict, blank=True, help_text="Data needed to reverse this action")
    rolled_back = models.BooleanField(default=False, help_text="Whether this action has been rolled back")
    rolled_back_at = models.DateTimeField(null=True, blank=True, help_text="When this action was rolled back")
    rollback_audit_id = models.IntegerField(
        null=True, blank=True, help_text="ID of the audit log entry for the rollback action"
    )

    # Context
    session_id = models.CharField(max_length=100, blank=True, db_index=True)
    transport = models.CharField(
        max_length=20,
        choices=[
            ("stdio", "Standard I/O"),
            ("sse", "Server-Sent Events"),
        ],
        default="stdio",
    )
    mode = models.CharField(
        max_length=20,
        choices=[
            ("safe", "Safe Mode"),
            ("power", "Power Mode"),
        ],
        default="safe",
    )

    # Correlation for multi-step operations
    correlation_id = models.CharField(
        max_length=100, blank=True, db_index=True, help_text="Groups related audit entries together"
    )
    parent_audit_id = models.IntegerField(
        null=True, blank=True, help_text="ID of parent audit entry (for nested operations)"
    )

    # Timestamps
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["account", "tool_name"]),
            models.Index(fields=["account", "timestamp"]),
            models.Index(fields=["correlation_id"]),
        ]

    def __str__(self):
        status = "OK" if self.success else "FAILED"
        return f"{self.tool_name} [{status}] - {self.timestamp}"

    def mark_rolled_back(self, rollback_audit_id: int = None):
        """Mark this action as rolled back."""
        self.rolled_back = True
        self.rolled_back_at = timezone.now()
        if rollback_audit_id:
            self.rollback_audit_id = rollback_audit_id
        self.save(update_fields=["rolled_back", "rolled_back_at", "rollback_audit_id"])

    def get_explanation(self) -> dict:
        """
        Get a human-readable explanation of why this action was taken.

        Returns a dict with:
        - what: What action was performed
        - why: The reasoning behind it
        - context: Summary of the context
        - reversible: Whether it can be undone
        """
        return {
            "what": f"Called {self.tool_name} with {len(self.parameters)} parameters",
            "why": self.reasoning or "No reasoning captured",
            "intent": self.intent or "Unknown intent",
            "context": self.context_summary or "No context available",
            "reversible": self.is_reversible,
            "rolled_back": self.rolled_back,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
        }


class MCPSession(models.Model):
    """
    Tracks active MCP sessions for rate limiting and monitoring.
    """

    session_id = models.CharField(max_length=100, unique=True, db_index=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="mcp_sessions")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    # Session configuration
    mode = models.CharField(
        max_length=20,
        choices=[
            ("safe", "Safe Mode"),
            ("power", "Power Mode"),
        ],
        default="safe",
    )
    transport = models.CharField(
        max_length=20,
        choices=[
            ("stdio", "Standard I/O"),
            ("sse", "Server-Sent Events"),
        ],
        default="stdio",
    )

    # Session state
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)

    # Statistics
    tool_calls_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["-last_activity"]

    def __str__(self):
        status = "active" if self.is_active else "inactive"
        return f"Session {self.session_id[:8]}... ({status})"

    def record_tool_call(self):
        """Record a tool call for this session."""
        self.tool_calls_count += 1
        self.save(update_fields=["tool_calls_count", "last_activity"])


class AgentProfile(models.Model):
    """
    Reusable profile defining what tools an agent can access.
    Profiles can be assigned to multiple API keys for consistent access control.
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="agent_profiles")
    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="agent_profiles",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    # Tool access control
    include_tools = models.JSONField(
        default=list, blank=True, help_text="Allowed tool names. Empty list = all tools allowed."
    )

    # Mode setting
    mode = models.CharField(
        max_length=20,
        choices=[
            ("safe", "Safe Mode"),
            ("power", "Power Mode"),
        ],
        default="safe",
        help_text="Safe mode blocks write operations, Power mode allows all",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("project", "name")]
        verbose_name = "Agent Profile"
        verbose_name_plural = "Agent Profiles"

    def __str__(self):
        return self.name

    def is_tool_allowed(self, tool_name: str) -> bool:
        """
        Check if a tool is allowed by this profile.

        Args:
            tool_name: Name of the tool

        Returns:
            True if tool is allowed
        """
        if not self.include_tools:
            return True
        return tool_name in self.include_tools


class Project(models.Model):
    """
    Project model - represents a project context for MCP operations.

    Projects provide:
    - Token → Project (1:1) binding for access control
    - External system mappings (e.g., jira: "PROJ-123", github: "org/repo")
    - Category restrictions for tools available within the project
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="mcp_projects")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, db_index=True, help_text="URL-safe identifier for the project")
    description = models.TextField(blank=True)

    # External system mappings: {"jira": "PROJ-123", "github": "org/repo"}
    external_mappings = models.JSONField(
        default=dict, blank=True, help_text="Maps system aliases to external project identifiers"
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("account", "slug")]
        verbose_name = "Project"
        verbose_name_plural = "Projects"

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def get_external_id(self, system_alias: str) -> str | None:
        """Get external ID for a specific system."""
        if self.external_mappings:
            return self.external_mappings.get(system_alias)
        return None


class MCPApiKey(models.Model):
    """
    API keys for MCP authentication.
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="mcp_api_keys")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    name = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=10, db_index=True)
    key_hash = models.CharField(max_length=128)

    # Profile-based access control
    profile = models.ForeignKey(
        AgentProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="api_keys",
        help_text="Agent profile defining tool access. If set, overrides mode/allowed_tools/blocked_tools.",
    )

    # Project binding - tokens can be bound to a specific project
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_keys",
        help_text="Project this token is bound to. If set, all operations are scoped to this project.",
    )

    # Admin flag - allows using X-Project-Id header to override project
    is_admin = models.BooleanField(
        default=False, help_text="Admin tokens can use X-Project-Id header to access any project"
    )

    # Legacy permissions (used if no profile)
    mode = models.CharField(
        max_length=20,
        choices=[
            ("safe", "Safe Mode"),
            ("power", "Power Mode"),
        ],
        default="safe",
    )
    allowed_tools = models.JSONField(
        default=list, blank=True, help_text="List of allowed tool patterns (empty = all allowed for mode)"
    )
    blocked_tools = models.JSONField(default=list, blank=True, help_text="List of blocked tool patterns")

    # Status
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "MCP API Key"
        verbose_name_plural = "MCP API Keys"

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...)"

    @classmethod
    def generate_key(cls):
        """Generate a new API key."""
        import hashlib
        import secrets

        key = f"ak_live_{secrets.token_urlsafe(32)}"
        prefix = key[:10]
        key_hash = hashlib.sha256(key.encode()).hexdigest()

        return key, prefix, key_hash

    def check_key(self, key: str) -> bool:
        """Check if the provided key matches."""
        import hashlib

        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key_hash == self.key_hash

    def mark_used(self):
        """Update last used timestamp."""
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])


class ErrorDiagnostic(models.Model):
    """
    Stores error diagnoses from failed adapter calls (API, OAuth, etc.).
    Provides categorized error analysis with optional fix suggestions.
    Fixes always require manual approval.
    """

    CATEGORY_CHOICES = [
        ("auth_expired", "Auth Expired"),
        ("auth_invalid", "Auth Invalid"),
        ("auth_permissions", "Auth Permissions"),
        ("not_found_mapping", "Not Found (Mapping)"),
        ("not_found_path", "Not Found (Path)"),
        ("validation_missing", "Validation (Missing Fields)"),
        ("validation_type", "Validation (Type Error)"),
        ("rate_limit", "Rate Limit"),
        ("server_error", "Server Error"),
        ("timeout", "Timeout"),
        ("connection", "Connection Error"),
        ("unknown", "Unknown"),
    ]

    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("dismissed", "Dismissed"),
        ("applied", "Applied"),
        ("expired", "Expired"),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="error_diagnostics")
    system_alias = models.CharField(max_length=100, db_index=True)
    tool_name = models.CharField(max_length=255, db_index=True)
    action_name = models.CharField(max_length=255, blank=True)

    # Error details
    status_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField()
    error_data = models.JSONField(default=dict, blank=True)

    # Diagnosis
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, db_index=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="medium")
    diagnosis_summary = models.CharField(max_length=500)
    diagnosis_detail = models.TextField(blank=True)

    # Fix suggestion
    has_fix = models.BooleanField(default=False)
    fix_description = models.TextField(blank=True)
    fix_action = models.JSONField(default=dict, blank=True)

    # Review workflow
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    # Occurrence tracking (deduplication)
    occurrence_count = models.IntegerField(default=1)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["account", "system_alias", "category", "status"]),
            models.Index(fields=["account", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.category}] {self.system_alias}/{self.tool_name} - {self.status}"


class CapabilityPack(models.Model):
    """
    A collection of business-level tools organized by domain/vertical.

    Capability Packs provide semantic business-level abstractions over raw API
    endpoints. For example, instead of 'salesforce_contact_create', a pack might
    expose 'create_sales_lead' with simplified, domain-specific parameters.

    This enables:
    - AI-friendly tool names and descriptions
    - Field mapping and defaults
    - Vertical-specific customization
    - Better permission granularity
    """

    VERTICAL_CHOICES = [
        ("general", "General"),
        ("sales", "Sales Operations"),
        ("marketing", "Marketing"),
        ("finance", "Finance Operations"),
        ("hr", "Human Resources"),
        ("construction", "Construction"),
        ("healthcare", "Healthcare"),
        ("legal", "Legal"),
        ("custom", "Custom"),
    ]

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="capability_packs",
        null=True,
        blank=True,
        help_text="If null, this is a global pack available to all accounts",
    )
    name = models.CharField(max_length=200, help_text='Display name (e.g., "Sales Operations Pack")')
    alias = models.SlugField(max_length=100, help_text='Unique identifier (e.g., "sales-ops")')
    description = models.TextField(blank=True, help_text="Description of what this pack provides")
    vertical = models.CharField(max_length=50, choices=VERTICAL_CHOICES, default="general")

    # LLM-optimized metadata
    llm_description = models.CharField(
        max_length=500, blank=True, help_text="Short description optimized for AI agents"
    )
    use_cases = models.JSONField(default=list, blank=True, help_text="List of example use cases for AI context")

    # Configuration
    is_active = models.BooleanField(default=True)
    is_global = models.BooleanField(default=False, help_text="If true, available to all accounts")
    requires_systems = models.JSONField(
        default=list, blank=True, help_text="List of system aliases required for this pack"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("account", "alias")]
        verbose_name = "Capability Pack"
        verbose_name_plural = "Capability Packs"

    def __str__(self):
        scope = "Global" if self.is_global else f"Account {self.account_id}"
        return f"{self.name} ({scope})"

    def get_available_tools(self, account_id: int) -> list:
        """Get all business tools available for an account."""
        return list(self.business_tools.filter(is_active=True))


class BusinessTool(models.Model):
    """
    A semantic business-level tool that maps to underlying system actions.

    Business tools provide AI-friendly interfaces to complex operations:
    - Simplified parameters with sensible defaults
    - Clear, action-oriented names (create_sales_lead vs salesforce_contact_create)
    - Field mapping between business concepts and API fields
    - Automatic data transformation

    Example:
        BusinessTool(
            name='create_sales_lead',
            description='Add a new sales lead to the CRM',
            maps_to_system='salesforce',
            maps_to_action='contact_create',
            field_mapping={'name': 'FirstName + LastName', 'company': 'Account.Name'},
            defaults={'LeadSource': 'AI Agent'}
        )
    """

    TOOL_TYPE_CHOICES = [
        ("read", "Read (Safe)"),
        ("write", "Write (Requires Power)"),
        ("action", "Action (Transactional)"),
    ]

    pack = models.ForeignKey(CapabilityPack, on_delete=models.CASCADE, related_name="business_tools")
    name = models.CharField(max_length=100, help_text='Tool name (e.g., "create_sales_lead")')
    description = models.TextField(help_text="Human-readable description")

    # LLM-optimized metadata
    llm_description = models.CharField(
        max_length=300, blank=True, help_text="Short description optimized for AI agents"
    )
    tool_hints = models.TextField(blank=True, help_text="Usage hints for AI agents")
    examples = models.JSONField(default=list, blank=True, help_text="Example inputs and outputs for LLM context")

    # Mapping to underlying system action
    maps_to_system = models.CharField(max_length=100, help_text='System alias (e.g., "salesforce")')
    maps_to_action = models.CharField(
        max_length=200, help_text='Full action path (e.g., "contact_create" or "rest.contact.create")'
    )

    # Input/Output schema
    input_schema = models.JSONField(default=dict, help_text="JSON Schema for business-level input parameters")
    output_schema = models.JSONField(default=dict, blank=True, help_text="JSON Schema for output (optional)")

    # Field mapping and transformation
    field_mapping = models.JSONField(
        default=dict, help_text="Maps business fields to API fields. Values can be field names or expressions."
    )
    defaults = models.JSONField(
        default=dict, blank=True, help_text="Default values for API fields not exposed to business tool"
    )
    output_mapping = models.JSONField(
        default=dict, blank=True, help_text="Maps API response fields to business-level output"
    )

    # Configuration
    tool_type = models.CharField(max_length=20, choices=TOOL_TYPE_CHOICES, default="read")
    is_active = models.BooleanField(default=True)
    requires_confirmation = models.BooleanField(
        default=False, help_text="If true, agent should confirm before executing"
    )

    # For rollback support
    supports_rollback = models.BooleanField(default=False, help_text="If true, this action can be undone")
    rollback_action = models.CharField(
        max_length=200, blank=True, help_text="Action to call for rollback (if different from inverse)"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("pack", "name")]
        verbose_name = "Business Tool"
        verbose_name_plural = "Business Tools"

    def __str__(self):
        return f"{self.pack.alias}:{self.name}"

    def get_mcp_tool_type(self) -> str:
        """Get MCP-compatible tool type."""
        if self.tool_type == "read":
            return "system_read"
        return "system_write"

    def transform_input(self, business_input: dict) -> dict:
        """
        Transform business-level input to API-level input.

        Applies field mapping and defaults.
        """
        api_input = dict(self.defaults)

        for business_field, value in business_input.items():
            if business_field in self.field_mapping:
                mapping = self.field_mapping[business_field]

                # Simple field rename
                if isinstance(mapping, str) and not any(c in mapping for c in ["+", "."]):
                    api_input[mapping] = value
                # Expression (for future: support templates/expressions)
                else:
                    # For now, treat as direct mapping
                    api_input[mapping] = value
            else:
                # Pass through unmapped fields
                api_input[business_field] = value

        return api_input

    def transform_output(self, api_output: dict) -> dict:
        """
        Transform API-level output to business-level output.

        Applies output mapping.
        """
        if not self.output_mapping:
            return api_output

        business_output = {}
        for business_field, api_field in self.output_mapping.items():
            # Handle nested field access with dots
            if "." in api_field:
                parts = api_field.split(".")
                value = api_output
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = None
                        break
                business_output[business_field] = value
            else:
                business_output[business_field] = api_output.get(api_field)

        return business_output
