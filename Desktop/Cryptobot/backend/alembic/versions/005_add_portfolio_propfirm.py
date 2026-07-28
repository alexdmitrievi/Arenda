revision: str = "005_add_portfolio_propfirm"
down_revision: str | None = "004_add_trading_models"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", postgresql.ENUM("conservative", "defi", "aggressive", "custom", name="portfolio_type"), default="custom"),
        sa.Column("allocation", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("rebalance_threshold_pct", sa.Numeric(5, 2), default=5.00),
        sa.Column("rebalance_frequency", postgresql.ENUM("monthly", "quarterly", "manual", name="rebalance_frequency"), default="manual"),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "dca_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolios.id"), nullable=True),
        sa.Column("asset", sa.String(32), nullable=False),
        sa.Column("amount_per_period", sa.Numeric(18, 2), nullable=False),
        sa.Column("frequency", postgresql.ENUM("daily", "weekly", "monthly", name="dca_frequency"), default="weekly"),
        sa.Column("atr_multiplier", sa.Numeric(5, 2), default=2.00),
        sa.Column("active_steps", postgresql.JSONB, nullable=True),
        sa.Column("next_execution_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "prop_firm_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("firm", sa.String(64), nullable=False),
        sa.Column("account_size", sa.Numeric(18, 2), nullable=False),
        sa.Column("rules", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("progress", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", postgresql.ENUM("active", "passed", "failed", "paused", name="challenge_status"), default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("prop_firm_challenges")
    op.drop_table("dca_plans")
    op.drop_table("portfolios")
    op.execute("DROP TYPE IF EXISTS challenge_status")
    op.execute("DROP TYPE IF EXISTS dca_frequency")
    op.execute("DROP TYPE IF EXISTS rebalance_frequency")
    op.execute("DROP TYPE IF EXISTS portfolio_type")
