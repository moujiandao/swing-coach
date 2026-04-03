"""add racquet_data to analyses

Revision ID: j5g6h8i9d012
Revises: i4f5g7h8c901
Create Date: 2026-04-03 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j5g6h8i9d012'
down_revision: Union[str, Sequence[str], None] = 'i4f5g7h8c901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add racquet_data and pro_racquet_data JSON columns to analyses table."""
    op.add_column('analyses', sa.Column('racquet_data', sa.JSON(), nullable=True))
    op.add_column('analyses', sa.Column('pro_racquet_data', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove racquet data columns from analyses table."""
    op.drop_column('analyses', 'pro_racquet_data')
    op.drop_column('analyses', 'racquet_data')
