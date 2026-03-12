from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Account
from apps.mcp.models import AgentProfile, Project
from apps.oauth.models import OAuthApplication


class Command(BaseCommand):
    help = "Create an OAuth2 application and display the credentials (secret shown once)."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Application name")
        parser.add_argument("--account-id", type=int, required=True, help="Account ID to bind tokens to")
        parser.add_argument("--redirect-uri", required=True, help="OAuth2 callback URL")
        parser.add_argument("--mode", default="safe", choices=["safe", "power"], help="Default token mode")
        parser.add_argument("--profile-id", type=int, default=None, help="AgentProfile ID for tokens")
        parser.add_argument("--project-id", type=int, default=None, help="Project ID to bind tokens to")

    def handle(self, **options):
        try:
            account = Account.objects.get(pk=options["account_id"])
        except Account.DoesNotExist:
            raise CommandError(f"Account {options['account_id']} not found.")

        profile = None
        if options["profile_id"]:
            try:
                profile = AgentProfile.objects.get(pk=options["profile_id"], account=account)
            except AgentProfile.DoesNotExist:
                raise CommandError(f"AgentProfile {options['profile_id']} not found for account {account}.")

        project = None
        if options["project_id"]:
            try:
                project = Project.objects.get(pk=options["project_id"], account=account)
            except Project.DoesNotExist:
                raise CommandError(f"Project {options['project_id']} not found for account {account}.")

        client_id, client_secret, prefix, secret_hash = OAuthApplication.generate_credentials()

        app = OAuthApplication.objects.create(
            account=account,
            name=options["name"],
            client_id=client_id,
            client_secret_hash=secret_hash,
            client_secret_prefix=prefix,
            redirect_uri=options["redirect_uri"],
            mode=options["mode"],
            profile=profile,
            project=project,
        )

        self.stdout.write(self.style.SUCCESS("\nOAuth Application created!\n"))
        self.stdout.write(f"  Name:          {app.name}")
        self.stdout.write(f"  Account:       {account.name} (id={account.pk})")
        self.stdout.write(f"  Client ID:     {client_id}")
        self.stdout.write(f"  Client Secret: {client_secret}")
        self.stdout.write(f"  Redirect URI:  {app.redirect_uri}")
        self.stdout.write(f"  Mode:          {app.mode}")
        if profile:
            self.stdout.write(f"  Profile:       {profile.name} (id={profile.pk})")
        if project:
            self.stdout.write(f"  Project:       {project.name} (id={project.pk})")
        self.stdout.write(self.style.WARNING("\n  Save the Client Secret now — it cannot be retrieved later.\n"))
