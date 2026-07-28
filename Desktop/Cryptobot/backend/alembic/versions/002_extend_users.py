revision: str = "002_extend_users"
down_revision: str | None = "001_create_users"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users", sa.Column("email_verification_token", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("email_verification_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("referred_by", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "referred_by")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "email_verification_sent_at")
    op.drop_column("users", "email_verification_token")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "password_hash")
