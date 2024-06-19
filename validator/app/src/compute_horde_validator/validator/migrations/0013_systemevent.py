# Generated by Django 4.2.13 on 2024-06-17 04:03

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("validator", "0012_adminjobrequest_status_message"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemEvent",
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
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("WEIGHT_SETTING_SUCCESS", "Weight Setting Success"),
                            ("WEIGHT_SETTING_FAILURE", "Weight Setting Failure"),
                            (
                                "MINER_FAILED_SYNTHETIC_JOB",
                                "Miner Failed Synthetic Job",
                            ),
                        ],
                        max_length=255,
                    ),
                ),
                (
                    "subtype",
                    models.CharField(
                        choices=[
                            ("SUCCESS", "Success"),
                            (
                                "SUBTENSOR_CONNECTIVITY_ERROR",
                                "Subtensor Connectivity Error",
                            ),
                            ("GENERIC_ERROR", "Generic Error"),
                            ("WRITING_TO_CHAIN_TIMEOUT", "Writing To Chain Timeout"),
                            ("WRITING_TO_CHAIN_FAILED", "Writing To Chain Failed"),
                            (
                                "WRITING_TO_CHAIN_GENERIC_ERROR",
                                "Writing To Chain Generic Error",
                            ),
                        ],
                        max_length=255,
                    ),
                ),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                (
                    "long_description",
                    models.TextField(
                        blank=True,
                        help_text="Verbose description of the event, not sent to the stats collector",
                    ),
                ),
                ("data", models.JSONField(blank=True)),
                ("sent", models.BooleanField(default=False)),
            ],
        ),
    ]
