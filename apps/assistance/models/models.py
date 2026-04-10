from django.db import models
from django.conf import settings
from django_ckeditor_5.fields import CKEditor5Field


class AssistanceProgram(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = CKEditor5Field("Description", config_name="default")
    requirements = CKEditor5Field("Requirements", config_name="default")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
    	return self.name


class CitizenProfile(models.Model):
    full_name = models.CharField(max_length=255)
    email = models.EmailField(db_index=True)
    phone = models.CharField(max_length=20, db_index=True)

    total_requests = models.PositiveIntegerField(default=0)
    last_request_at = models.DateTimeField(null=True, blank=True)

    RISK_LEVEL_CHOICES = [
    	("normal", "Normal"),
    	("frequent", "Frequent Requester"),
    	("priority", "Priority Assistance"),
    	("flagged", "Flagged for Review"),
    ]
    risk_level = models.CharField(
        max_length=20,
        choices=RISK_LEVEL_CHOICES,
        default="normal",
        help_text="Future classification: normal, frequent, priority, flagged"
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.full_name} ({self.total_requests})"


class CitizenRequest(models.Model):
    tracking_code = models.CharField(max_length=24, unique=True, db_index=True)
    secure_edit_token = models.CharField(max_length=64, unique=True)

    program = models.ForeignKey(
        AssistanceProgram,
        on_delete=models.PROTECT,
        related_name="requests"
    )

    full_name = models.CharField(max_length=255)
    email = models.EmailField(db_index=True)
    phone = models.CharField(max_length=20, db_index=True)

    citizen = models.ForeignKey(
        "CitizenProfile",
        on_delete=models.PROTECT,
        related_name="requests",
        null=True,
        blank=True
    )

    status = models.CharField(max_length=20, default="submitted")
    remarks = models.TextField(blank=True)
    summary = models.TextField(blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_locked = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
    	return f"{self.tracking_code} - {self.full_name}"


class RequestDocument(models.Model):
    request = models.ForeignKey(
        CitizenRequest,
        on_delete=models.CASCADE,
        related_name="documents"
    )

    document_type = models.CharField(max_length=50)
    file = models.FileField(upload_to="tracepoint/documents/")
    status = models.CharField(max_length=20, default="pending")
    remarks = models.TextField(blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
    	return f"{self.request.tracking_code} - {self.document_type}"
    	

class RequestTimeline(models.Model):
    request = models.ForeignKey(
        CitizenRequest,
        on_delete=models.CASCADE,
        related_name="timeline"
    )

    event_type = models.CharField(max_length=50)
    message = models.TextField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
    	return f"{self.request.tracking_code} - {self.event_type}"


