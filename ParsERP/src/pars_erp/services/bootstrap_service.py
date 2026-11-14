"""Reference-data bootstrap and installation metadata.

Runs after migrations on every start:

* ensures every permission from the code catalogue exists in the database;
* ensures the built-in roles exist and *gain* newly added permissions
  (nothing is ever removed from an administrator's customised role, and custom
  roles are never touched);
* records installation metadata and the number of application starts.

The operation is idempotent and safe to run concurrently with itself.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from pars_erp.db.models import AppMetadata, Permission, Role
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import (
    ALL_PERMISSIONS,
    DEFAULT_ROLE_TEMPLATES,
    RoleTemplate,
)


class BootstrapResult:
    def __init__(self, *, permissions_added: int = 0, roles_added: int = 0,
                 role_permissions_added: int = 0, metadata_created: bool = False) -> None:
        self.permissions_added = permissions_added
        self.roles_added = roles_added
        self.role_permissions_added = role_permissions_added
        self.metadata_created = metadata_created

    def __repr__(self) -> str:  # pragma: no cover
        return (f"BootstrapResult(permissions_added={self.permissions_added}, "
                f"roles_added={self.roles_added}, "
                f"role_permissions_added={self.role_permissions_added}, "
                f"metadata_created={self.metadata_created})")


def ensure_reference_data(db: Database) -> BootstrapResult:
    result = BootstrapResult()
    with db.session_scope() as session:
        existing = {p.code: p for p in session.execute(select(Permission)).scalars()}
        for definition in ALL_PERMISSIONS:
            current = existing.get(definition.code)
            if current is None:
                session.add(Permission(
                    code=definition.code,
                    section=definition.section,
                    section_title_fa=definition.section_title_fa,
                    action=definition.action,
                    title_fa=definition.title_fa,
                    sort_order=definition.sort_order,
                ))
                result.permissions_added += 1
            else:
                # Keep catalogue metadata in sync (titles/order may change in a release).
                current.section = definition.section
                current.section_title_fa = definition.section_title_fa
                current.action = definition.action
                current.title_fa = definition.title_fa
                current.sort_order = definition.sort_order
        session.flush()

        permissions = {p.code: p for p in session.execute(select(Permission)).scalars()}
        roles = {r.code: r for r in session.execute(select(Role)).scalars()}
        for template in DEFAULT_ROLE_TEMPLATES:
            role = roles.get(template.code)
            if role is None:
                role = Role(code=template.code, title_fa=template.title_fa,
                            description=template.description, is_system=template.is_system,
                            sort_order=template.sort_order)
                session.add(role)
                session.flush()
                roles[template.code] = role
                result.roles_added += 1
            _apply_template_permissions(role, template, permissions, result)

        metadata = session.get(AppMetadata, 1)
        if metadata is None:
            session.add(AppMetadata(
                id=1,
                installation_id=str(uuid.uuid4()),
                created_at=utcnow(),
                schema_revision=db.schema_revision(),
                last_startup_at=utcnow(),
                startup_count=1,
            ))
            result.metadata_created = True
        else:
            metadata.last_startup_at = utcnow()
            metadata.startup_count = int(metadata.startup_count or 0) + 1
            metadata.schema_revision = db.schema_revision() or metadata.schema_revision
    return result


def _apply_template_permissions(role: Role, template: RoleTemplate, permissions: dict[str, Permission],
                                result: BootstrapResult) -> None:
    """Grant the template's permissions that the role is missing."""
    if not role.is_system:
        return
    have = {p.code for p in role.permissions}
    for code in sorted(template.permissions - have):
        permission = permissions.get(code)
        if permission is None:
            continue
        role.permissions.append(permission)
        result.role_permissions_added += 1


def get_metadata(db: Database) -> AppMetadata | None:
    with db.session_scope() as session:
        return session.get(AppMetadata, 1)


def installation_id(db: Database) -> str | None:
    metadata = get_metadata(db)
    return metadata.installation_id if metadata else None


def count_users(db: Database) -> int:
    from pars_erp.db.models import User
    with db.session_scope() as session:
        return int(session.execute(select(func.count(User.id))).scalar() or 0)
