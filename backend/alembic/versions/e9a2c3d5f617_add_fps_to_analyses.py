"""add fps to analyses

Revision ID: e9a2c3d5f617
Revises: d4f8b2e1a736
Create Date: 2026-03-28 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9a2c3d5f617'
down_revision: Union[str, Sequence[str], None] = 'd4f8b2e1a736'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add fps column to analyses table."""
    op.add_column('analyses', sa.Column('fps', sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove fps column from analyses table."""
    op.drop_column('analyses', 'fps')
