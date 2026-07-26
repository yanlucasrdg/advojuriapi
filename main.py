"""schema inicial

Revision ID: 4500b86937aa
Revises:
Create Date: 2026-07-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4500b86937aa"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("documento", sa.String(20), nullable=True),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chave_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("chave_prefixo_visivel", sa.String(20), nullable=False),
        sa.Column("ambiente", sa.String(10), nullable=False),
        sa.Column("revogada_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_chave_hash", "api_keys", ["chave_hash"])

    tipo_transacao = postgresql.ENUM(
        "recarga", "consulta", "estorno", "ajuste_manual", name="tipo_transacao"
    )
    tipo_transacao.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ledger_transacoes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tipo", tipo_transacao, nullable=False),
        sa.Column("valor_centavos", sa.BigInteger, nullable=False),
        sa.Column("saldo_apos_centavos", sa.BigInteger, nullable=False),
        sa.Column("referencia_id", sa.String(64), nullable=True),
        sa.Column("descricao", sa.String(255), nullable=True),
    )
    op.create_index("ix_ledger_tenant_criado", "ledger_transacoes", ["tenant_id", "criado_em"])

    op.create_table(
        "processos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("numero_cnj", sa.String(25), nullable=False, unique=True),
        sa.Column("tribunal", sa.String(20), nullable=False),
        sa.Column("classe", sa.String(255), nullable=True),
        sa.Column("assunto", sa.String(255), nullable=True),
        sa.Column("orgao_julgador", sa.String(255), nullable=True),
        sa.Column("valor_acao", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_ajuizamento", sa.Date, nullable=True),
        sa.Column("segredo_justica", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("fonte", sa.String(30), nullable=False, server_default="datajud"),
        sa.Column("atualizado_em", sa.DateTime, nullable=False),
    )
    op.create_index("ix_processos_numero_cnj", "processos", ["numero_cnj"])
    op.create_index("ix_processos_tribunal", "processos", ["tribunal"])

    op.create_table(
        "partes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("processo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("processos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("documento", sa.String(20), nullable=True),
        sa.Column("tipo_pessoa", sa.String(10), nullable=True),
        sa.Column("polo", sa.String(20), nullable=True),
    )
    op.create_index("ix_partes_processo_id", "partes", ["processo_id"])

    op.create_table(
        "movimentos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("processo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("processos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_movimento", sa.DateTime, nullable=False),
        sa.Column("descricao", sa.String(500), nullable=False),
        sa.Column("codigo_cnj", sa.String(20), nullable=True),
        sa.Column("hash_dedup", sa.String(64), nullable=False),
    )
    op.create_index("ix_movimentos_processo_id", "movimentos", ["processo_id"])
    op.create_index("ix_movimentos_hash_dedup", "movimentos", ["hash_dedup"])

    op.create_table(
        "monitoramentos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("processo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("processos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("webhook_url", sa.String(500), nullable=False),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("ultima_verificacao_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_monitoramentos_tenant_id", "monitoramentos", ["tenant_id"])
    op.create_index("ix_monitoramentos_processo_id", "monitoramentos", ["processo_id"])

    op.create_table(
        "alertas_enviados",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("monitoramento_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("monitoramentos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("movimento_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status_entrega", sa.String(20), nullable=False, server_default="pendente"),
        sa.Column("tentativas", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_alertas_monitoramento_id", "alertas_enviados", ["monitoramento_id"])

    op.create_table(
        "consultas_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tipo_busca", sa.String(30), nullable=False),
        sa.Column("termo_busca_hash", sa.String(64), nullable=False),
        sa.Column("custo_centavos", sa.Integer, nullable=False),
        sa.Column("resultado_encontrado", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("origem_cache", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_consultas_log_tenant_id", "consultas_log", ["tenant_id"])
    op.create_index("ix_consultas_log_termo_hash", "consultas_log", ["termo_busca_hash"])


def downgrade() -> None:
    op.drop_table("consultas_log")
    op.drop_table("alertas_enviados")
    op.drop_table("monitoramentos")
    op.drop_table("movimentos")
    op.drop_table("partes")
    op.drop_table("processos")
    op.drop_table("ledger_transacoes")
    postgresql.ENUM(name="tipo_transacao").drop(op.get_bind(), checkfirst=True)
    op.drop_table("api_keys")
    op.drop_table("tenants")
