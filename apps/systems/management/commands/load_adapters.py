"""
Management command to load adapter definitions from YAML files.

Usage:
    python manage.py load_adapters                        # load all adapters
    python manage.py load_adapters --industry construction # load one industry
    python manage.py load_adapters --list                  # list available files
    python manage.py load_adapters --dry-run               # validate without writing
"""

from django.core.management.base import BaseCommand

from apps.systems.adapter_loader import (
    ADAPTERS_DIR,
    discover_adapter_files,
    load_adapter_file,
)


class Command(BaseCommand):
    help = "Load adapter definitions from YAML files in adapters/"

    def add_arguments(self, parser):
        parser.add_argument(
            "--industry",
            type=str,
            default=None,
            help="Only load adapters for this industry (e.g. construction)",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_only",
            help="List available adapter files without loading",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate YAML files without writing to the database",
        )

    def handle(self, *args, **options):
        industry = options["industry"]
        list_only = options["list_only"]
        dry_run = options["dry_run"]

        files = discover_adapter_files(industry=industry)

        if not files:
            self.stderr.write(
                self.style.WARNING(f"No adapter files found in {ADAPTERS_DIR}" + (f"/{industry}" if industry else ""))
            )
            return

        if list_only:
            self.stdout.write(f"Adapter files ({len(files)}):")
            for path in files:
                rel = path.relative_to(ADAPTERS_DIR)
                self.stdout.write(f"  {rel}")
            return

        loaded = 0
        errors = 0

        for path in files:
            rel = path.relative_to(ADAPTERS_DIR)
            try:
                system = load_adapter_file(path, dry_run=dry_run)
                if dry_run:
                    self.stdout.write(self.style.SUCCESS(f"  OK  {rel}"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"  OK  {rel} -> {system.display_name}"))
                loaded += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  ERR {rel}: {e}"))
                errors += 1

        # Summary
        mode = "Validated" if dry_run else "Loaded"
        summary = f"{mode} {loaded} adapter(s)"
        if errors:
            summary += f", {errors} error(s)"

        if errors:
            self.stderr.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
