"""
Forms for systems app with proper validation.
"""

import json

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, URLValidator

from .models import HTTP_METHODS, INTERFACE_TYPES, AccountSystem, Action, Interface, Resource


class JSONField(forms.CharField):
    """Custom form field for JSON input with validation."""

    def __init__(self, *args, expect_type="dict", **kwargs):
        kwargs.setdefault("widget", forms.Textarea(attrs={"rows": 3}))
        kwargs.setdefault("required", False)
        self.expect_type = expect_type  # 'dict' or 'list'
        super().__init__(*args, **kwargs)

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return {} if self.expect_type == "dict" else []
        try:
            parsed = json.loads(value)
            if self.expect_type == "dict" and not isinstance(parsed, dict):
                raise ValidationError("Must be a JSON object (not array or primitive)")
            if self.expect_type == "list" and not isinstance(parsed, list):
                raise ValidationError("Must be a JSON array")
            return parsed
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON: {e}")


class AccountSystemForm(forms.ModelForm):
    """Form for configuring system credentials."""

    username = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    password = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    api_key = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    token = forms.CharField(
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    client_id = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    client_secret = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    session_cookie = forms.CharField(
        max_length=5000,
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    csrf_token = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    session_expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"],
    )
    is_enabled = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    class Meta:
        model = AccountSystem
        fields = [
            "username",
            "password",
            "api_key",
            "token",
            "client_id",
            "client_secret",
            "session_cookie",
            "csrf_token",
            "session_expires_at",
            "is_enabled",
        ]

    def clean_username(self):
        value = self.cleaned_data.get("username", "")
        # Prevent potential injection in username
        if value and any(c in value for c in ["<", ">", '"', "'"]):
            raise ValidationError("Username contains invalid characters")
        return value.strip() if value else ""

    def clean_api_key(self):
        value = self.cleaned_data.get("api_key", "")
        if value:
            # Basic sanity check - API keys are usually alphanumeric with some special chars
            if len(value) > 500:
                raise ValidationError("API key is too long (max 500 characters)")
        return value.strip() if value else ""


# Regex for valid slug/name fields
slug_validator = RegexValidator(
    regex=r"^[a-zA-Z][a-zA-Z0-9_-]*$",
    message="Must start with a letter and contain only letters, numbers, underscores, and hyphens",
)


class InterfaceForm(forms.ModelForm):
    """Form for creating/editing interfaces."""

    name = forms.CharField(
        max_length=120,
        validators=[slug_validator],
        widget=forms.TextInput(attrs={"class": "form-control"}),
        help_text="Slug format: letters, numbers, underscores, hyphens. Must start with letter.",
    )
    alias = forms.CharField(
        max_length=120,
        required=False,
        validators=[slug_validator],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    type = forms.ChoiceField(
        choices=INTERFACE_TYPES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    base_url = forms.CharField(
        max_length=300,
        required=False,
        widget=forms.URLInput(attrs={"class": "form-control"}),
    )
    requires_browser = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    auth = JSONField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        help_text="JSON object for auth configuration",
    )
    browser = JSONField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        help_text="JSON object for browser settings",
    )
    rate_limits = JSONField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        help_text="JSON object for rate limits",
    )

    class Meta:
        model = Interface
        fields = ["name", "alias", "type", "base_url", "requires_browser", "auth", "browser", "rate_limits"]

    def clean_base_url(self):
        value = self.cleaned_data.get("base_url", "")
        if value:
            # Validate URL format
            validator = URLValidator()
            try:
                validator(value)
            except ValidationError:
                raise ValidationError("Enter a valid URL")
        return value

    def clean_alias(self):
        value = self.cleaned_data.get("alias", "")
        if not value:
            # Default to name if alias not provided
            return self.cleaned_data.get("name", "")
        return value


class ResourceForm(forms.ModelForm):
    """Form for creating/editing resources."""

    name = forms.CharField(
        max_length=120,
        validators=[slug_validator],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    alias = forms.CharField(
        max_length=120,
        required=False,
        validators=[slug_validator],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    description = forms.CharField(
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    interface = forms.ModelChoiceField(
        queryset=Interface.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Resource
        fields = ["interface", "name", "alias", "description"]

    def __init__(self, *args, system=None, **kwargs):
        super().__init__(*args, **kwargs)
        if system:
            self.fields["interface"].queryset = Interface.objects.filter(system=system)

    def clean_alias(self):
        value = self.cleaned_data.get("alias", "")
        if not value:
            return self.cleaned_data.get("name", "")
        return value


class ActionForm(forms.ModelForm):
    """Form for creating/editing actions."""

    name = forms.CharField(
        max_length=120,
        validators=[slug_validator],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    alias = forms.CharField(
        max_length=120,
        required=False,
        validators=[slug_validator],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    description = forms.CharField(
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    method = forms.ChoiceField(
        choices=HTTP_METHODS,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    path = forms.CharField(
        max_length=400,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        help_text="URL path, e.g. /api/v1/users/{id}",
    )
    headers = JSONField(
        required=False,
        help_text="JSON object for HTTP headers",
    )
    parameters_schema = JSONField(
        required=False,
        help_text="JSON Schema for parameters",
    )
    output_schema = JSONField(
        required=False,
        help_text="JSON Schema for output",
    )
    pagination = JSONField(
        required=False,
        help_text="Pagination configuration",
    )
    errors = JSONField(
        required=False,
        help_text="Error handling configuration",
    )
    examples = JSONField(
        required=False,
        expect_type="list",
        help_text="JSON array of example requests/responses",
    )
    resource = forms.ModelChoiceField(
        queryset=Resource.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Action
        fields = [
            "resource",
            "name",
            "alias",
            "description",
            "method",
            "path",
            "headers",
            "parameters_schema",
            "output_schema",
            "pagination",
            "errors",
            "examples",
        ]

    def __init__(self, *args, system=None, **kwargs):
        super().__init__(*args, **kwargs)
        if system:
            self.fields["resource"].queryset = Resource.objects.filter(interface__system=system).select_related(
                "interface"
            )

    def clean_alias(self):
        value = self.cleaned_data.get("alias", "")
        if not value:
            return self.cleaned_data.get("name", "")
        return value

    def clean_path(self):
        value = self.cleaned_data.get("path", "")
        if value and not value.startswith("/"):
            raise ValidationError("Path must start with /")
        return value
