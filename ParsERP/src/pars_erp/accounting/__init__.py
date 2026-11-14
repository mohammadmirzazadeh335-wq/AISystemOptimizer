"""Pure accounting domain vocabulary (no Qt, no SQLAlchemy imports)."""

from pars_erp.accounting.constants import (  # noqa: F401
    ACCOUNT_LEVELS,
    ACCOUNT_TYPES,
    ALLOWED_TRANSITIONS,
    DETAIL_KINDS,
    JOURNAL_STATUSES,
    LEVEL_TITLES_FA,
    NATURES,
    SECTION_TITLES_FA,
    STATUS_DRAFT,
    STATUS_TITLES_FA,
    TYPE_TITLES_FA,
)

__all__ = [
    "ACCOUNT_LEVELS",
    "ACCOUNT_TYPES",
    "ALLOWED_TRANSITIONS",
    "DETAIL_KINDS",
    "JOURNAL_STATUSES",
    "LEVEL_TITLES_FA",
    "NATURES",
    "SECTION_TITLES_FA",
    "STATUS_DRAFT",
    "STATUS_TITLES_FA",
    "TYPE_TITLES_FA",
]
