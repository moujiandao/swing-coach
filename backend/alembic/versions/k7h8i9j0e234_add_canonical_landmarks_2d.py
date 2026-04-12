"""add canonical_landmarks_2d to analyses

Revision ID: k7h8i9j0e234
Revises: j5g6h8i9d012
Create Date: 2026-04-12 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k7h8i9j0e234'
down_revision: Union[str, Sequence[str], None] = 'j5g6h8i9d012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add canonical_landmarks_2d JSON column for angle-normalized overlay."""
    op.add_column('analyses', sa.Column('canonical_landmarks_2d', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove canonical_landmarks_2d column."""
    op.drop_column('analyses', 'canonical_landmarks_2d')
