# Branch and PR Workflow

This repository uses a feature-branch workflow to keep the main branch stable and deployable.

## Branching rules
- Create one branch per feature or workstream.
- Keep each branch focused on a single deliverable.
- Rebase or merge from main regularly to avoid drift.
- Do not merge directly to main without a reviewed PR.

## Suggested branches
- feature/backend-api-structure
- feature/document-ingestion
- feature/search-ranking
- feature/frontend-search-ui
- feature/deployment-infra

## PR checklist
- Feature is implemented and tested.
- Relevant tests pass locally.
- Main remains stable after merge.
- PR description clearly explains the change and verification.

## Merge policy
- Merge only through reviewed Pull Requests.
- Delete feature branches after the PR is merged.
