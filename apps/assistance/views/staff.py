from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.assistance.models import RequestDocument
from apps.assistance.services.document_service import DocumentService, DocumentServiceError

STAFF_DOCUMENT_REVIEW_PERMISSION = "assistance.change_requestdocument"
STAFF_DOCUMENT_REVIEW_GROUPS = frozenset(
    {
        "Assistance Staff",
        "Document Reviewers",
        "MSWD Staff",
    }
)


def _ajax_staff_response(status: str, message: str, *, http_status: int = 200):
    return JsonResponse(
        {"status": status, "message": message},
        status=http_status,
    )


def _user_can_review_documents(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if not user.is_staff:
        return False
    if user.has_perm(STAFF_DOCUMENT_REVIEW_PERMISSION):
        return True
    return user.groups.filter(name__in=STAFF_DOCUMENT_REVIEW_GROUPS).exists()


def _authorize_document_review(user) -> None:
    if not _user_can_review_documents(user):
        raise PermissionDenied("You do not have permission to review documents.")


@login_required
@require_POST
def mswd_update_document_ajax(request, document_id):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_staff_response("error", "Invalid request.")

    try:
        _authorize_document_review(request.user)
        DocumentService.update_review_status(
            document_id=document_id,
            status=request.POST.get("status", ""),
            remarks=request.POST.get("remarks", ""),
            actor=request.user,
        )
    except PermissionDenied as e:
        return _ajax_staff_response("danger", str(e), http_status=403)
    except ValidationError as e:
        message = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
        return _ajax_staff_response("error", message)
    except RequestDocument.DoesNotExist:
        return _ajax_staff_response("error", "Document not found.", http_status=404)
    except DocumentServiceError as e:
        return _ajax_staff_response("error", str(e))
    except Exception:
        return _ajax_staff_response("danger", "Unable to update document.")

    return _ajax_staff_response("success", "Document updated successfully.")
