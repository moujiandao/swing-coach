"""add stroke types buggy_whip_forehand and slice

Revision ID: h3e4f6g7b890
Revises: g2d3e5f6a789
Create Date: 2026-04-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'h3e4f6g7b890'
down_revision: Union[str, Sequence[str], None] = 'g2d3e5f6a789'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add buggy_whip_forehand and slice to the stroketype enum.

    PostgreSQL requires ALTER TYPE ... ADD VALUE for native enums.
    SQLite uses CHECK constraints and does not support ALTER TYPE, so we
    skip the operation on non-PG dialects (SQLAlchemy recreates the table
    via batch mode when needed).
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE stroketype ADD VALUE IF NOT EXISTS 'buggy_whip_forehand'")
        op.execute("ALTER TYPE stroketype ADD VALUE IF NOT EXISTS 'slice'")


def downgrade() -> None:
    """PostgreSQL does not support removing values from an enum type.

    To fully reverse this migration you would need to recreate the enum
    and migrate all columns that reference it. For an MVP this is not
    worth the complexity, so downgrade is a no-op.
    """
    pass
