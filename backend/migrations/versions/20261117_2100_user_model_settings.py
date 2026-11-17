"""user model settings

Revision ID: 4d2a7c91be05
Revises: fa850313b768
"""

import sqlalchemy as sa
from alembic import op

revision = "4d2a7c91be05"
down_revision = "fa850313b768"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 用户自己的模型 Key 只存密文与尾号；模型名为空时回退到默认配置
    op.add_column("users", sa.Column("model_api_key_encrypted", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("model_api_key_hint", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("planner_model", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("text_to_image_model", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("image_edit_model", sa.String(length=128), nullable=True))


def downgrade() -> None:
    for column in (
        "image_edit_model",
        "text_to_image_model",
        "planner_model",
        "model_api_key_hint",
        "model_api_key_encrypted",
    ):
        op.drop_column("users", column)
