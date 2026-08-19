revision: str = "006_mvp_hardening"
down_revision: str | None = "005_add_portfolio_propfirm"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # trade lifecycle: PENDING rows exist between DB-write and exchange confirmation
    op.execute("ALTER TYPE trade_status ADD VALUE IF NOT EXISTS 'pending' BEFORE 'open'")

    op.add_column("trades", sa.Column("order_id", sa.String(64), nullable=True))
    op.add_column("trades", sa.Column("fee", sa.Numeric(18, 8), nullable=True))

    op.create_index("ix_signals_symbol_created_at", "signals", ["symbol", "created_at"])
    op.create_index("ix_signals_created_at_confidence", "signals", ["created_at", "confidence"])
    op.create_index("ix_trades_user_id_status", "trades", ["user_id", "status"])
    op.create_index("ix_trades_signal_id_user_id", "trades", ["signal_id", "user_id"])
    op.create_index("ix_subscriptions_user_id_status", "subscriptions", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_subscriptions_user_id_status", table_name="subscriptions")
    op.drop_index("ix_trades_signal_id_user_id", table_name="trades")
    op.drop_index("ix_trades_user_id_status", table_name="trades")
    op.drop_index("ix_signals_created_at_confidence", table_name="signals")
    op.drop_index("ix_signals_symbol_created_at", table_name="signals")
    op.drop_column("trades", "fee")
    op.drop_column("trades", "order_id")
    # PostgreSQL cannot drop a value from an enum type — 'pending' stays
