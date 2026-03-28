"""add pro_reference_id and pro_landmarks to analyses

Revision ID: c7e3a1b2d849
Revises: a3c1e7d2f905
Create Date: 2026-03-27 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e3a1b2d849'
down_revision: Union[str, Sequence[str], None] = 'a3c1e7d2f905'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pro_reference_id FK and pro_landmarks JSON to analyses."""
    op.add_column(
        'analyses',
        sa.Column('pro_reference_id', sa.Uuid(), nullable=True),
    )
    op.add_column(
        'analyses',
        sa.Column('pro_landmarks', sa.JSON(), nullable=True),
    )
    # Add FK constraint only on databases that support ALTER TABLE ADD CONSTRAINT.
    # SQLite (used in tests) does not; the ORM model handles FK semantics in code.
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.create_foreign_key(
            'fk_analyses_pro_reference_id',
            'analyses',
            'pro_references',
            ['pro_reference_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    """Remove pro_reference_id and pro_landmarks from analyses."""
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.drop_constraint('fk_analyses_pro_reference_id', 'analyses', type_='foreignkey')
    op.drop_column('analyses', 'pro_landmarks')
    op.drop_column('analyses', 'pro_reference_id')
