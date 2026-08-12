"""Email delivery for the password-reset flow (H2).

DEC-3 (email/SMTP provider, from docs/ROADMAP.md) is still open, so the
default transport is a console log: the reset link is emitted at INFO level
and the request still succeeds, which lets the whole flow be built and
verified before a provider is chosen. When DEC-3 lands, this module grows a
real transport (SMTP or a transactional API) behind the same
:func:`deliver_reset_link` interface — the auth endpoints do not change.

This is request-path light work (a log line today); bulk notification
delivery (welcome emails, sync mailings) stays in the batch path.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def deliver_reset_link(email: str, link: str) -> None:
    """Deliver a one-time password-reset link to the given address.

    Current transport (DEC-3 pending): log the link at INFO. Production
    must not rely on this — replace with a real transport when SMTP is
    configured.
    """
    logger.info("PASSWORD_RESET for %s: %s", email, link)