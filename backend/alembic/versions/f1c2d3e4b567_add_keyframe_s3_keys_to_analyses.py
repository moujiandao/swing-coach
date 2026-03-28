"""add keyframe_s3_keys to analyses

Revision ID: f1c2d3e4b567
Revises: e9a2c3d5f617
Create Date: 2026-03-28 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1c2d3e4b567'
down_revision: Union[str, Sequence[str], None] = 'e9a2c3d5f617'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add keyframe_s3_keys JSON column to analyses table."""
    op.add_column('analyses', sa.Column('keyframe_s3_keys', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove keyframe_s3_keys column from analyses table."""
    op.drop_column('analyses', 'keyframe_s3_keys')
