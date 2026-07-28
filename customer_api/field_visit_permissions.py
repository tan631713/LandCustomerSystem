"""Central role-to-capability mapping for field-visit operations."""

from __future__ import annotations


FIELD_VISIT_VIEW = "field_visit_view"
FIELD_VISIT_CREATE = "field_visit_create"
FIELD_VISIT_UPDATE = "field_visit_update"
FIELD_VISIT_OPTIMIZE = "field_visit_optimize"
FIELD_VISIT_COMPLETE = "field_visit_complete"
FIELD_VISIT_ATTACHMENT_UPLOAD = "field_visit_attachment_upload"
FIELD_VISIT_ATTACHMENT_DELETE_OWN = "field_visit_attachment_delete_own"
FIELD_VISIT_ATTACHMENT_DELETE_ALL = "field_visit_attachment_delete_all"
FIELD_VISIT_ADMIN = "field_visit_admin"

ROLE_CAPABILITIES = {
    "viewer": frozenset({FIELD_VISIT_VIEW}),
    "editor": frozenset(
        {
            FIELD_VISIT_VIEW,
            FIELD_VISIT_CREATE,
            FIELD_VISIT_UPDATE,
            FIELD_VISIT_OPTIMIZE,
            FIELD_VISIT_COMPLETE,
            FIELD_VISIT_ATTACHMENT_UPLOAD,
            FIELD_VISIT_ATTACHMENT_DELETE_OWN,
        }
    ),
    "admin": frozenset(
        {
            FIELD_VISIT_VIEW,
            FIELD_VISIT_CREATE,
            FIELD_VISIT_UPDATE,
            FIELD_VISIT_OPTIMIZE,
            FIELD_VISIT_COMPLETE,
            FIELD_VISIT_ATTACHMENT_UPLOAD,
            FIELD_VISIT_ATTACHMENT_DELETE_OWN,
            FIELD_VISIT_ATTACHMENT_DELETE_ALL,
            FIELD_VISIT_ADMIN,
        }
    ),
}


class FieldVisitPermissionDenied(PermissionError):
    """Raised when a server-side field-visit capability check fails."""


def field_visit_capabilities(role: str) -> frozenset[str]:
    return ROLE_CAPABILITIES.get(str(role or "").strip().lower(), frozenset())


def can_delete_field_visit_attachment(user, created_by) -> bool:
    capabilities = field_visit_capabilities(user.role)
    if FIELD_VISIT_ATTACHMENT_DELETE_ALL in capabilities:
        return True
    if FIELD_VISIT_ATTACHMENT_DELETE_OWN not in capabilities or created_by is None:
        return False
    try:
        return int(created_by) == int(user.id)
    except (TypeError, ValueError):
        return False


def require_field_visit_capability(user, capability: str) -> None:
    if capability not in field_visit_capabilities(user.role):
        raise FieldVisitPermissionDenied(
            f"role {user.role!r} does not have field-visit capability {capability!r}"
        )
