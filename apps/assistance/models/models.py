from django.db import models
from django.conf import settings
from django.db.models import Q
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
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("under_review", "Under Review"),
        ("approved", "Approved"),
        ("denied", "Denied"),
    ]

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

    status = models.CharField(max_length=20, default="pending")
    remarks = models.TextField(blank=True)
    summary = models.TextField(blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_locked = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
    	return f"{self.tracking_code} - {self.full_name}"


class RequestDocument(models.Model):
    """
    At most one *active* row per (request, document_type); soft-removed rows stay
    for audit while keeping storage until superseded by a new upload.
    """

    DOCUMENT_TYPE_CHOICES = [
        ("birth_cert", "Birth Certificate"),
        ("indigency", "Certificate of Indigency"),
        ("school_id", "School ID"),
        ("grade_card", "Report Card / Grade Card"),
        ("cert_of_enrollment", "Certificate of Enrollment/Registration"),
        ("others", "Other Supporting Document"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("clearer_copy", "Needs Clearer Copy"),
        ("wrong_file", "Wrong File"),
        ("incomplete", "Incomplete"),
        ("missing_stamp", "Missing Stamp"),
        ("expired", "Expired"),
    ]

    request = models.ForeignKey(
        CitizenRequest,
        on_delete=models.CASCADE,
        related_name="documents"
    )

    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES, default="others")
    file = models.FileField(upload_to="tracepoint/documents/")
    status = models.CharField(max_length=20, default="pending")
    remarks = models.TextField(blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_removed = models.BooleanField(default=False, db_index=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    replacement_count = models.PositiveIntegerField(
        default=0,
        help_text="How many times a stored file was superseded by a new upload (citizen replace/re-upload).",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("request", "document_type"),
                condition=Q(is_removed=False),
                name="assistance_requestdocument_active_unique_type",
            ),
        ]

    def __str__(self):
        return f"{self.request.tracking_code} - {self.document_type}"

    @property
    def was_replaced_by_citizen(self) -> bool:
        return self.replacement_count > 0

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
