"""adiciona webhook_secret em monitoramentos

Revision ID: 8a1f2c4d9e10
Revises: 4500b86937aa
Create Date: 2026-07-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8a1f2c4d9e10"
down_revision: Union[str, None] = "4500b86937aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default temporário só para preencher linhas existentes;
    # removido logo depois porque o valor real deve vir sempre da aplicação
    # (gerado por segredo aleatório na criação do monitoramento), nunca
    # de um default fixo compartilhado por todas as linhas.
    op.add_column(
        "monitoramentos",
        sa.Column("webhook_secret", sa.String(64), nullable=False, server_default="TROCAR_ANTES_DE_USAR"),
    )
    op.alter_column("monitoramentos", "webhook_secret", server_default=None)


def downgrade() -> None:
    op.drop_column("monitoramentos", "webhook_secret")
