"""Session security and external-payment uniqueness.

Duplicate confirmed references intentionally stop migration; resolve them through reversal,
never delete financial records automatically.
"""
import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("backup_runs", sa.Column("files_name", sa.String(200), nullable=False, server_default=""))
    op.add_column("backup_runs", sa.Column("files_sha256", sa.String(64), nullable=False, server_default=""))
    op.alter_column("backup_runs", "files_name", server_default=None)
    op.alter_column("backup_runs", "files_sha256", server_default=None)
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.create_index("uq_payment_external_confirmed", "payments", ["external_ref"], unique=True,
                    postgresql_where=sa.text("external_ref <> '' AND status = 'confirmed'"),
                    sqlite_where=sa.text("external_ref <> '' AND status = 'confirmed'"))


def downgrade():
    op.drop_column("backup_runs", "files_sha256")
    op.drop_column("backup_runs", "files_name")
    op.drop_index("uq_payment_external_confirmed", table_name="payments")
    op.drop_column("users", "totp_last_step")
