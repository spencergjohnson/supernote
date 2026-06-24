"""Add deleted_root_id to f_user_file for recursive folder delete grouping

Revision ID: a1b2c3d4e5f6
Revises: 0543a383957b
Create Date: 2026-06-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "0543a383957b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add deleted_root_id column + index to f_user_file."""
    op.add_column(
        "f_user_file",
        sa.Column("deleted_root_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        op.f("ix_f_user_file_deleted_root_id"),
        "f_user_file",
        ["deleted_root_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove deleted_root_id column and index from f_user_file."""
    op.drop_index(op.f("ix_f_user_file_deleted_root_id"), table_name="f_user_file")
    op.drop_column("f_user_file", "deleted_root_id")
