from django.db import migrations


ASSISTANCE_STAFF_GROUPS = (
    "mswd",
    "assistance_reviewer",
    "assistance_approver",
    "assistance_fulfillment",
)


def create_assistance_staff_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ASSISTANCE_STAFF_GROUPS:
        Group.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("assistance", "0003_alter_citizenrequest_status"),
    ]

    operations = [
        migrations.RunPython(
            create_assistance_staff_groups,
            migrations.RunPython.noop,
        ),
    ]
