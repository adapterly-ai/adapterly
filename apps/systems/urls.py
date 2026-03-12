from django.urls import path

from . import views, wizard_views

urlpatterns = [
    path("", views.systems_dashboard, name="systems_dashboard"),
    path("configure/<int:system_id>/", views.configure_system, name="configure_system"),
    path("test/<int:system_id>/", views.test_system_connection, name="test_system_connection"),
    path("toggle/<int:system_id>/", views.toggle_system_status, name="toggle_system_status"),
    path("delete/<int:system_id>/", views.delete_system_config, name="delete_system_config"),
    # Adapter Generator (legacy)
    path("generate/", views.adapter_generator, name="adapter_generator"),
    path("api/generate-adapter/", views.adapter_generator_api, name="adapter_generator_api"),
    # Adapter Generator Wizard
    path("wizard/", wizard_views.wizard_start, name="wizard_start"),
    path("wizard/step1/submit/", wizard_views.wizard_step1_submit, name="wizard_step1_submit"),
    path("wizard/step2/", wizard_views.wizard_step2, name="wizard_step2"),
    path("wizard/step2/stream/", wizard_views.wizard_discover_stream, name="wizard_discover_stream"),
    path("wizard/step2/submit/", wizard_views.wizard_step2_submit, name="wizard_step2_submit"),
    path("wizard/step3/", wizard_views.wizard_step3, name="wizard_step3"),
    path("wizard/step3/submit/", wizard_views.wizard_step3_submit, name="wizard_step3_submit"),
    path("wizard/step4/", wizard_views.wizard_step4, name="wizard_step4"),
    path("wizard/save/", wizard_views.wizard_save, name="wizard_save"),
    # Wizard AJAX endpoints
    path("wizard/api/endpoint/", wizard_views.wizard_get_endpoint, name="wizard_get_endpoint"),
    path("wizard/api/endpoint/update/", wizard_views.wizard_update_endpoint, name="wizard_update_endpoint"),
    path("wizard/api/endpoint/add/", wizard_views.wizard_add_endpoint, name="wizard_add_endpoint"),
    path("wizard/api/endpoint/delete/", wizard_views.wizard_delete_endpoint, name="wizard_delete_endpoint"),
    path("wizard/api/resource/add/", wizard_views.wizard_add_resource, name="wizard_add_resource"),
    path("wizard/api/test-connection/", wizard_views.wizard_test_connection, name="wizard_test_connection"),
    # Interface CRUD
    path("<int:system_id>/interfaces/", views.interfaces_list, name="interfaces_list"),
    path("<int:system_id>/interfaces/create/", views.interface_create, name="interface_create"),
    path("interfaces/<int:interface_id>/edit/", views.interface_edit, name="interface_edit"),
    path("interfaces/<int:interface_id>/delete/", views.interface_delete, name="interface_delete"),
    # Resource CRUD
    path("<int:system_id>/resources/", views.resources_list, name="resources_list"),
    path("<int:system_id>/resources/create/", views.resource_create, name="resource_create"),
    path("resources/<int:resource_id>/edit/", views.resource_edit, name="resource_edit"),
    path("resources/<int:resource_id>/delete/", views.resource_delete, name="resource_delete"),
    # Action CRUD
    path("resources/<int:resource_id>/actions/", views.actions_list, name="actions_list"),
    path("resources/<int:resource_id>/actions/create/", views.action_create, name="action_create"),
    path("actions/<int:action_id>/edit/", views.action_edit, name="action_edit"),
    path("actions/<int:action_id>/delete/", views.action_delete, name="action_delete"),
    path("actions/<int:action_id>/test/", views.test_action, name="test_action"),
    path("actions/<int:action_id>/toggle-mcp/", views.toggle_action_mcp, name="toggle_action_mcp"),
    # MCP Tool Configuration
    path("<int:system_id>/mcp-tools/", views.mcp_tools_config, name="mcp_tools_config"),
    path("<int:system_id>/mcp-tools/bulk/", views.bulk_toggle_actions_mcp, name="bulk_toggle_actions_mcp"),
]
