"""add overlay fields to analyses (Task 4.1)

Revision ID: d4f8b2e1a736
Revises: c7e3a1b2d849
Create Date: 2026-03-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f8b2e1a736'
down_revision: Union[str, Sequence[str], None] = 'c7e3a1b2d849'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add phase alignment overlay fields to analyses."""
    op.add_column('analyses', sa.Column('aligned_pro_landmarks', sa.JSON(), nullable=True))
    op.add_column('analyses', sa.Column('frame_mapping', sa.JSON(), nullable=True))
    op.add_column('analyses', sa.Column('frame_deviations', sa.JSON(), nullable=True))
    op.add_column('analyses', sa.Column('phase_boundaries', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove phase alignment overlay fields from analyses."""
    op.drop_column('analyses', 'phase_boundaries')
    op.drop_column('analyses', 'frame_deviations')
    op.drop_column('analyses', 'frame_mapping')
    op.drop_column('analyses', 'aligned_pro_landmarks')
