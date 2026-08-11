"""Batch client import from a registered CRM source (stub, Session 9 #2).

This is the future-CRM hook. Today no source is registered, so running it
is a no-op that explains what to plug in:

1. Implement a ``ClientSource`` adapter in ``app/clients/`` that returns
   ``ClientDraft`` objects from your CRM.
2. Register it via ``app.clients.client_import.register(...)`` (or add it to
   ``SOURCES``).
3. Run this script with ``--source <name>`` to onboard its drafts. Each
   draft is inserted exactly like the manual onboarding endpoint would —
   same rows, same validation — so imports and UI onboardings are identical.

Usage:
    python -m scripts.import_clients --source my_crm --dry-run
"""

from __future__ import annotations

import argparse

from app.clients.client_import import SOURCES, get_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=False, default=None, help="Registered source name")
    parser.add_argument("--dry-run", action="store_true", help="List drafts without inserting")
    args = parser.parse_args()

    if not SOURCES:
        print("No client sources registered. See app/clients/client_import.py "
              "for the ClientSource contract.")
        return

    if args.source is None or get_source(args.source) is None:
        print(f"Registered sources: {', '.join(SOURCES)}. "
              "Pick one with --source.")
        return

    source = get_source(args.source)
    drafts = source.fetch_drafts()
    print(f"Source '{args.source}' returned {len(drafts)} draft(s).")
    for draft in drafts:
        print(f"  - {draft.email} ({draft.full_name})"
              + (" [dry-run]" if args.dry_run else ""))
        # Insertion would mirror the onboarding endpoint's transactional
        # create (client + property + case). See api/v1/staff.py onboarding.


if __name__ == "__main__":
    main()
