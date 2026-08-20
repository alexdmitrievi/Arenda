revision: str = "007_trade_execution_hardening"
down_revision: str | None = "006_mvp_hardening"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # execution hardening: client order id survives a crash between the
    # DB-write and the exchange call; stop/tp order ids let the sync loop
    # detect exchange-side fills of the protective orders; stop/tp prices
    # on the trade make reconciliation independent of the signal row
    op.add_column("trades", sa.Column("client_order_id", sa.String(64), nullable=True))
    op.add_column("trades", sa.Column("stop_order_id", sa.String(64), nullable=True))
    op.add_column("trades", sa.Column("tp_order_id", sa.String(64), nullable=True))
    op.add_column("trades", sa.Column("stop_loss", sa.Numeric(18, 8), nullable=True))
    op.add_column("trades", sa.Column("take_profit", sa.Numeric(18, 8), nullable=True))


def downgrade() -> None:
    op.drop_column("trades", "take_profit")
    op.drop_column("trades", "stop_loss")
    op.drop_column("trades", "tp_order_id")
    op.drop_column("trades", "stop_order_id")
    op.drop_column("trades", "client_order_id")
