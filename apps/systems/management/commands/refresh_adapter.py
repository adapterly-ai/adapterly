"""
Management command to refresh adapter definitions from OpenAPI specs.

Usage:
    python manage.py refresh_adapter --system my_system               # one system
    python manage.py refresh_adapter --system my_system --dry-run     # diff only
    python manage.py refresh_adapter --all                           # all with spec URL
    python manage.py refresh_adapter --system my_system --spec-url https://...
"""

from django.core.management.base import BaseCommand, CommandError

from apps.systems.models import System
from apps.systems.refresh import refresh_adapter


class Command(BaseCommand):
    help = "Refresh adapter(s) by re-fetching their OpenAPI spec"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--system",
            type=str,
            help="Alias of a single system to refresh",
        )
        group.add_argument(
            "--all",
            action="store_true",
            dest="refresh_all",
            help="Refresh all systems that have meta.openapi_spec_url",
        )
        parser.add_argument(
            "--spec-url",
            type=str,
            default=None,
            help="Override the stored spec URL (only with --system)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and diff without writing to the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        spec_url = options["spec_url"]

        if options["refresh_all"]:
            if spec_url:
                raise CommandError("--spec-url cannot be used with --all")
            systems = list(
                System.objects.filter(meta__openapi_spec_url__isnull=False).exclude(meta__openapi_spec_url="")
            )
            if not systems:
                self.stderr.write(self.style.WARNING("No systems have meta.openapi_spec_url configured."))
                return
        else:
            alias = options["system"]
            try:
                systems = [System.objects.get(alias=alias)]
            except System.DoesNotExist:
                raise CommandError(f"System with alias '{alias}' not found.")

        ok = 0
        errs = 0

        for system in systems:
            self._refresh_one(system, spec_url=spec_url, dry_run=dry_run)
            ok += 1

        if len(systems) > 1:
            summary = f"Refreshed {ok} system(s)"
            if errs:
                summary += f", {errs} error(s)"
            self.stdout.write(self.style.SUCCESS(summary))

    def _refresh_one(self, system, *, spec_url, dry_run):
        url = spec_url or (system.meta or {}).get("openapi_spec_url", "")
        self.stdout.write(f"Refreshing: {system.alias}")
        self.stdout.write(f"  Spec URL: {url}")

        try:
            result = refresh_adapter(system, spec_url=spec_url, dry_run=dry_run)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"  Error: {e}"))
            return

        if not result.spec_changed:
            self.stdout.write(self.style.SUCCESS("  No changes (spec unchanged)"))
            return

        short_old = result.old_digest[:12] if result.old_digest else "(none)"
        short_new = result.new_digest[:12]
        self.stdout.write(f"  Digest: {short_old} → {short_new}")
        self.stdout.write(
            f"  + {len(result.new_actions)} new, "
            f"~ {len(result.updated_actions)} updated, "
            f"= {len(result.unchanged_actions)} unchanged, "
            f"- {len(result.removed_actions)} removed from spec"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("  Mode: DRY RUN"))
        else:
            self.stdout.write(self.style.SUCCESS("  Saved."))

        if result.errors:
            for err in result.errors:
                self.stderr.write(self.style.ERROR(f"  ! {err}"))
