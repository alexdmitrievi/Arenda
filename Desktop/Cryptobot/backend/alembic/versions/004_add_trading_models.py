revision: str = "004_add_trading_models"
down_revision: str | None = "003_add_subscriptions_payments"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", postgresql.ENUM("smc", "grid", "dca", "trend", name="strategy_type"), nullable=False),
        sa.Column("params", postgresql.JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean(), default=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("direction", postgresql.ENUM("buy", "sell", name="trade_side"), nullable=False),
        sa.Column("entry", sa.Numeric(18, 8), nullable=False),
        sa.Column("stop_loss", sa.Numeric(18, 8), nullable=False),
        sa.Column("take_profit", postgresql.JSONB, nullable=True),
        sa.Column("confidence", sa.Integer(), default=50),
        sa.Column("signal_metadata", postgresql.JSONB, nullable=True),
        sa.Column("executed", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", postgresql.ENUM("buy", "sell", name="trade_side"), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id"), nullable=True),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("entry_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("size", sa.Numeric(18, 8), nullable=False),
        sa.Column("pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column("pnl_pct", sa.Numeric(10, 2), nullable=True),
        sa.Column("status", postgresql.ENUM("open", "closed", "cancelled", name="trade_status"), default="open"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", postgresql.ENUM("buy", "sell", name="trade_side"), nullable=False),
        sa.Column("size", sa.Numeric(18, 8), nullable=False),
        sa.Column("avg_entry", sa.Numeric(18, 8), nullable=False),
        sa.Column("current_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column("unrealized_pnl_pct", sa.Numeric(10, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("signals")
    op.drop_table("strategies")
    op.execute("DROP TYPE IF EXISTS trade_status")
    op.execute("DROP TYPE IF EXISTS trade_side")
    op.execute("DROP TYPE IF EXISTS strategy_type")
