"""CRM client-import hook (Session 9, decision #2).

A documented extension point for pulling clients from a future CRM without
touching the onboarding UI or the ``/staff/clients`` endpoint.

Today onboarding is manual: admins and staff with the ``onboard_clients``
capability create clients in the UI. When a real CRM exists, implement a
``ClientSource`` adapter and register it here; the ingestion loop stays the
same. The manual onboarding endpoint reuses the same ``ClientDraft`` shape,
so a source and the UI produce identical rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class ClientDraft:
    """A client to onboard — the shared shape between manual + CRM import.

    Fields mirror the ``clients`` / ``properties`` / ``cases`` tables so an
    adapter can be written against this contract without knowing the schema.
    """
    email: str
    password: str
    full_name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    property_type: str | None = None
    case_number: str | None = None
    loan_amount: float | None = None
    case_status: str = "active"
    notes: list[str] = field(default_factory=list)


class ClientSource(Protocol):
    """Contract for any future CRM / import connector.

    Implementations (e.g. ``HubspotClientSource``, ``SalesforceClientSource``)
    fetch candidate clients and yield ``ClientDraft`` objects. Registration
    happens in ``SOURCES`` below; the batch import script
    (``scripts/import_clients.py``) drives whichever source is configured.
    """

    name: str

    def fetch_drafts(self) -> list[ClientDraft]:
        """Return clients pending onboarding from this source."""
        ...


# Registered import sources. Add a new adapter here to expose it to
# ``scripts/import_clients.py`` — no other wiring is required.
SOURCES: dict[str, ClientSource] = {}


def register(source: ClientSource) -> None:
    """Register a ClientSource so the import script can discover it."""
    SOURCES[source.name] = source
    logger.info("Registered client source '%s'", source.name)


def get_source(name: str) -> ClientSource | None:
    """Look up a registered source by name."""
    return SOURCES.get(name)
