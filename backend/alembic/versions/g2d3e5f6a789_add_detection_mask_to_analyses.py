"""add detection_mask to analyses

Revision ID: g2d3e5f6a789
Revises: f1c2d3e4b567
Create Date: 2026-04-02 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g2d3e5f6a789'
down_revision: Union[str, Sequence[str], None] = 'f1c2d3e4b567'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add detection_mask JSON column to analyses table."""
    op.add_column('analyses', sa.Column('detection_mask', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove detection_mask column from analyses table."""
    op.drop_column('analyses', 'detection_mask')
