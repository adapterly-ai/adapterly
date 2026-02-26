"""
Add a partial unique index to ensure only one active account per user.

This prevents the data integrity bug where a user can end up with
multiple AccountUser rows having is_current_active=True.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_deviceauthorization"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX accounts_accountuser_one_active_per_user
                ON accounts_accountuser (user_id)
                WHERE is_current_active = true;
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS accounts_accountuser_one_active_per_user;
            """,
        ),
    ]
