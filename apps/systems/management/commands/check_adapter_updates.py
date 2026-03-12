"""
Management command to check for OpenAPI spec changes (digest-only, no apply).

Usage:
    python manage.py check_adapter_updates
    python manage.py check_adapter_updates --no-notify

Cron:
    0 6 * * * cd /path && python manage.py check_adapter_updates
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from apps.systems.models import System
from apps.systems.refresh import check_for_updates


class Command(BaseCommand):
    help = "Check all systems with an OpenAPI spec URL for digest changes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-notify",
            action="store_true",
            default=False,
            help="Skip sending email notification even if changes are found",
        )

    def handle(self, *args, **options):
        systems = list(System.objects.filter(meta__openapi_spec_url__isnull=False).exclude(meta__openapi_spec_url=""))
        if not systems:
            self.stderr.write(self.style.WARNING("No systems have meta.openapi_spec_url configured."))
            return

        checked = 0
        pending = 0
        errors = 0
        changed_aliases = []

        for system in systems:
            try:
                changed = check_for_updates(system)
                checked += 1
                if changed:
                    pending += 1
                    changed_aliases.append(system.alias)
                    self.stdout.write(self.style.WARNING(f"  {system.alias}: spec changed"))
                else:
                    self.stdout.write(f"  {system.alias}: up to date")
            except Exception as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(f"  {system.alias}: {exc}"))

        summary = f"Checked {checked} system(s), {pending} have pending updates"
        if errors:
            summary += f", {errors} error(s)"
        self.stdout.write(self.style.SUCCESS(summary))

        # Send email notification
        notify_emails = getattr(settings, "ADAPTER_UPDATE_NOTIFY_EMAILS", [])
        if pending > 0 and notify_emails and not options["no_notify"]:
            subject = f"Adapterly: {pending} adapter(s) have spec changes"
            alias_list = "\n".join(f"  - {alias}" for alias in changed_aliases)
            body = (
                f"{pending} adapter(s) have detected OpenAPI spec changes:\n\n"
                f"{alias_list}\n\n"
                f"Review and apply updates:\n"
                f"  https://adapterly.io/admin/systems/pending-refreshes/\n"
            )
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                notify_emails,
                fail_silently=True,
            )
            self.stdout.write(self.style.SUCCESS(f"Notification sent to {', '.join(notify_emails)}"))
