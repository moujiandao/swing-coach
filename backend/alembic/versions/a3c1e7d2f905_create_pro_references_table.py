"""create pro_references table

Revision ID: a3c1e7d2f905
Revises: fb5f0496c976
Create Date: 2026-03-27 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c1e7d2f905'
down_revision: Union[str, Sequence[str], None] = 'fb5f0496c976'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'pro_references',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('player_name', sa.String(length=255), nullable=False),
        sa.Column('player_slug', sa.String(length=255), nullable=False),
        sa.Column(
            'stroke_type',
            sa.Enum(
                'forehand', 'backhand_one', 'backhand_two',
                'serve_flat', 'serve_kick', 'serve_slice', 'volley',
                name='stroketype',
            ),
            nullable=False,
        ),
        sa.Column('video_s3_key', sa.String(length=512), nullable=True),
        sa.Column('thumbnail_s3_key', sa.String(length=512), nullable=True),
        sa.Column('npz_path', sa.String(length=1024), nullable=True),
        sa.Column(
            'status',
            sa.Enum('pending', 'processing', 'ready', 'failed', name='proreferencestatus'),
            nullable=False,
        ),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('frame_count', sa.Integer(), nullable=True),
        sa.Column('fps', sa.Float(), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('is_builtin', sa.Boolean(), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_slug'),
    )
    op.create_index('ix_pro_references_player_slug', 'pro_references', ['player_slug'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_pro_references_player_slug', table_name='pro_references')
    op.drop_table('pro_references')
