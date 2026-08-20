"""Response validation — redundant safety-net check (CLAUDE.md rule #1).

The PRIMARY enforcement is in search/hybrid_orchestrator.py WHERE clause.
This module re-checks permissions and version flags as a safety net.

Confidence-based routing is handled by
``response/confidence_thresholds.py`` (``route_by_confidence``) — it sets
``package.routing`` to ``"answer"``, ``"partial"``, or ``"no_answer"``;
validation must NOT treat low confidence as a hard failure, otherwise
every "no answer found" query returns HTTP 500 instead of a graceful
``no_answer`` response.
"""

from __future__ import annotations

from app.auth.rbac import is_admin, resolve_user_departments
from app.response.package_builder import ResponsePackage


def validate_package(
    package: ResponsePackage,
    user: dict | None,
    min_confidence: float = 50.0,
    assigned_client_ids: list[int] | None = None,
    ) -> tuple[bool, str]:
    """Validate a response package against RBAC and version rules.

    Returns (valid, reason). If invalid, the package should not be returned
    to the user.

    ``assigned_client_ids`` (optional, staff only) is the set of clients
    assigned to the user — used to re-check the client-assignment leg of
    the SQL scope as a safety net. When omitted, the staff leg only
    re-checks the department clause (defense-in-depth incompleteness, but
    the SQL WHERE clause remains the primary enforcement).

    Confidence is **not** checked here — that is the job of
    ``route_by_confidence``, which decides ``package.routing``.
    Low-confidence results are valid responses that the caller routes to
    ``"no_answer"`` or ``"partial"``, not server errors.
    """
    # RBAC check — safety net (primary enforcement is in the SQL WHERE clause)
    if user is not None and not is_admin(user):
        if user.get("audience") == "client":
            client_id = user.get("client_id")
            for excerpt in package.excerpts:
                scoped = excerpt.source.client_id
                # A company-wide document (client_id IS NULL) is visible to
                # every client. Only a doc scoped to a *different* client is
                # a violation — treating NULL as one would turn a harmless
                # company-wide doc into a 500.
                if scoped is not None and scoped != client_id:
                    return False, (
                        f"RBAC violation: chunk {excerpt.source.chunk_id} belongs to "
                        f"client {scoped}, not {client_id}"
                    )
        else:
            user_depts = set(resolve_user_departments(user))
            for excerpt in package.excerpts:
                if excerpt.source.department and excerpt.source.department not in user_depts:
                    return False, f"RBAC violation: chunk from department '{excerpt.source.department}' not visible to user"
                scoped = excerpt.source.client_id
                if (
                    scoped is not None
                    and assigned_client_ids is not None
                    and scoped not in assigned_client_ids
                ):
                    return False, (
                        f"RBAC violation: chunk {excerpt.source.chunk_id} belongs to "
                        f"client {scoped}, not assigned to user"
                    )

    # Version and approval check — safety net
    for excerpt in package.excerpts:
        if not excerpt.source.is_approved:
            return False, (
                f"Response safety violation: chunk {excerpt.source.chunk_id} "
                "is not approved"
            )
        if excerpt.source.document_version < 1:
            return False, (
                f"Response safety violation: document {excerpt.source.document_id} "
                f"has invalid version {excerpt.source.document_version}"
            )

    return True, "OK"
