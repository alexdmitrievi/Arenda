revision: str = "001_create_users"
down_revision: str | None = None
branch_labels = None
depends_on = None

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("telegram_id", sa.BigInteger(), unique=True, index=True, nullable=True),
        sa.Column("username", sa.String(128), nullable=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("role", postgresql.ENUM("user", "admin", name="user_role"), default="user"),
        sa.Column("exchange_keys_encrypted", postgresql.JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS user_role")
