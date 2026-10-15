from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [("load_analysis", "0005_existing_budget_policies")]

    operations = [
        migrations.AddField(
            model_name="loadreceipt",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
            preserve_default=False,
        ),
    ]
