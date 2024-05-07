# Generated by Django 4.2.10 on 2024-05-07 16:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("miner", "0004_validatorblacklist"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="validatorblacklist",
            options={
                "verbose_name": "Blacklisted Validator",
                "verbose_name_plural": "Blacklisted Validators",
            },
        ),
        migrations.AddField(
            model_name="acceptedjob",
            name="score",
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name="acceptedjob",
            name="time_took",
            field=models.DurationField(null=True),
        ),
        migrations.CreateModel(
            name="JobReceipt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("validator_signature", models.CharField(max_length=256)),
                ("miner_signature", models.CharField(max_length=256)),
                ("job_uuid", models.UUIDField()),
                ("miner_hotkey", models.CharField(max_length=256)),
                ("validator_hotkey", models.CharField(max_length=256)),
                ("time_started", models.DateTimeField()),
                ("time_took", models.DurationField()),
                ("score", models.FloatField()),
                ("synced_with_storage", models.BooleanField(default=False)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="miner.acceptedjob",
                    ),
                ),
            ],
        ),
    ]
