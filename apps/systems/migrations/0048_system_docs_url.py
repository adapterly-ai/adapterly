from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("systems", "0047_remove_unverified_adapters"),
    ]

    operations = [
        migrations.AddField(
            model_name="system",
            name="docs_url",
            field=models.URLField(blank=True, help_text="API documentation URL"),
        ),
    ]
