"""H7: write-back for the governance config (``roles_config.py``).

Implements ROADMAP H7 Option A — the Python config file stays the source of
truth and the admin UI edits it through ``PUT /admin/governance``: the file
is rewritten atomically (temp file + ``os.replace``) and then reloaded with
``importlib.reload`` so running handlers pick up the change without a
restart.

Because ``importlib.reload`` re-executes the module in the *same* module
object, closures/globals stay shared: a ``from app.auth.roles_config import
can`` binding made earlier still reads the freshly reloaded data.

The renderer is pure (``render_config``) so it can be unit-tested without
touching the real file; ``write_config`` performs the atomic write + reload
and accepts an injectable ``config_path`` / ``module`` for tests.
"""

from __future__ import annotations

import importlib
import os
import pprint
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "roles_config.py"

# The only capabilities that may be toggled in the UI. ``can()`` is generic,
# so this set is the whitelist an admin may enable for a role; grow it when
# new capabilities are introduced.
KNOWN_CAPABILITIES: set[str] = {"onboard_clients"}

DEPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_HEADER = '''\
"""Config-driven source of truth for roles, departments, and permissions.

Admin-editable (Phase H7) via ``PUT /admin/governance``: the UI rewrites
this file atomically and reloads it, so do not hand-edit it while the
server is running. This module is the single source of truth that
``app/auth/rbac.py`` enforcement is derived from.
"""

from __future__ import annotations

'''

_CAN_SRC = '''

def can(role: str, capability: str) -> bool:
    """Whether a role has an action-level capability.

    Admins/super_admins always satisfy any capability check; otherwise the
    capability must be listed for the role. This is the single lookup used
    by the onboarding endpoint so a future CRM-driven workflow can stay
    config-driven.
    """
    if role in ADMIN_ROLES:
        return True
    return capability in ROLE_CAPABILITIES.get(role, [])


# Human-facing labels + descriptions for the admin governance views.
ROLES: list[dict] = {roles}

# Departments that exist across the system. Free-string today; this is the
# display list for the admin Departments view.
DEPARTMENTS: list[dict] = {departments}


def role_access(role: str) -> list[str] | None:
    """Return accessible departments for a role, or None if all."""
    depts = ROLE_DEPARTMENTS.get(role)
    if depts is None:
        return None
    return depts if depts else None
'''


def render_config(
    *,
    roles: list[dict],
    departments: list[dict],
    role_hierarchy: list[str],
    default_department: str,
) -> str:
    """Render the full ``roles_config.py`` source for the given governance data.

    ``roles`` entries carry ``name`` / ``label`` / ``description`` /
    ``access`` (either ``"all"`` or a list of department names) /
    ``capabilities``. ``departments`` entries carry ``name`` / ``label`` /
    ``description``.
    """
    role_departments = {
        r["name"]: [] if r["access"] == "all" else list(r["access"])
        for r in roles
    }
    role_capabilities = {r["name"]: list(r.get("capabilities", [])) for r in roles}

    body = _HEADER + (
        "# Role -> departments they can access. [] means \"all departments\".\n"
        "# app/auth/rbac.py reads these constants at call time, so edits here\n"
        "# (applied via this file's atomic write + reload) take effect\n"
        "# immediately in enforcement.\n"
        "ROLE_DEPARTMENTS: dict[str, list[str]] = "
        + pprint.pformat(role_departments, width=88, sort_dicts=False)
        + "\n\n"
        "# Roles that bypass department filtering entirely (rbac.is_admin).\n"
        "ADMIN_ROLES: set[str] = "
        + pprint.pformat({"super_admin", "admin"})
        + "\n\n"
        "# Role hierarchy, lowest -> highest (permissions.require_role).\n"
        "ROLE_HIERARCHY: list[str] = "
        + pprint.pformat(role_hierarchy, width=88)
        + "\n\n"
        f"DEFAULT_DEPARTMENT: str = {default_department!r}\n"
        "\n"
        "# Action-level capabilities per role (Phase Session 9, decision #2).\n"
        "# Additive on top of department access. An empty list means the role\n"
        "# has no special capabilities beyond its department scope.\n"
        "ROLE_CAPABILITIES: dict[str, list[str]] = "
        + pprint.pformat(role_capabilities, width=88, sort_dicts=False)
        + _CAN_SRC.format(roles=pprint.pformat(roles, width=88, sort_dicts=False),
                          departments=pprint.pformat(departments, width=88, sort_dicts=False))
    )
    return body


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (same-dir temp + replace)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_config(
    *,
    roles: list[dict],
    departments: list[dict],
    role_hierarchy: list[str],
    default_department: str,
    config_path: str | Path | None = None,
    module=None,
) -> None:
    """Render, atomically write, and reload the governance config.

    ``config_path`` and ``module`` are injectable for tests; in production
    they default to the real ``roles_config.py`` and its module, so a reload
    makes the running app pick up the change immediately.
    """
    path = Path(config_path) if config_path is not None else CONFIG_PATH
    content = render_config(
        roles=roles,
        departments=departments,
        role_hierarchy=role_hierarchy,
        default_department=default_department,
    )
    _atomic_write(path, content)

    if module is None:
        import app.auth.roles_config as module
    importlib.reload(module)
