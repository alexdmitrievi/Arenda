revision: str = "003_add_subscriptions_payments"
down_revision: str | None = "002_extend_users"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan", postgresql.ENUM("demo", "trader", "investor_pro", "prop_firm_master", "enterprise", name="subscription_plan"), default="demo"),
        sa.Column("status", postgresql.ENUM("active", "expired", "cancelled", "pending", "trial", name="subscription_status"), default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), default=False),
        sa.Column("yookassa_payment_method_id", sa.String(255), nullable=True),
        sa.Column("trial_used", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subscriptions.id"), nullable=True),
        sa.Column("yookassa_payment_id", sa.String(255), unique=True, nullable=True),
        sa.Column("idempotency_key", sa.String(255), unique=True, nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), default="RUB"),
        sa.Column("vat_rate", sa.Integer(), default=4),
        sa.Column("status", postgresql.ENUM("pending", "succeeded", "canceled", "refunded", name="payment_status"), default="pending"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("plan", postgresql.ENUM("demo", "trader", "investor_pro", "prop_firm_master", "enterprise", name="subscription_plan"), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("invoice_number", sa.String(64), unique=True, nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("company_inn", sa.String(12), nullable=False),
        sa.Column("company_kpp", sa.String(9), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("vat_rate", sa.Integer(), default=4),
        sa.Column("vat_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("invoices")
    op.drop_table("payments")
    op.drop_table("subscriptions")
    op.execute("DROP TYPE IF EXISTS payment_status")
    op.execute("DROP TYPE IF EXISTS subscription_status")
    op.execute("DROP TYPE IF EXISTS subscription_plan")
