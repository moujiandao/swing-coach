"""add description to pro_references

Revision ID: i4f5g7h8c901
Revises: h3e4f6g7b890
Create Date: 2026-04-02 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i4f5g7h8c901'
down_revision: Union[str, Sequence[str], None] = 'h3e4f6g7b890'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable description TEXT column to pro_references."""
    with op.batch_alter_table('pro_references') as batch_op:
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove description column from pro_references."""
    with op.batch_alter_table('pro_references') as batch_op:
        batch_op.drop_column('description')
