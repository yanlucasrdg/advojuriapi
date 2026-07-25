import enum
import uuid

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class TipoTransacao(str, enum.Enum):
    RECARGA = "recarga"
    CONSULTA = "consulta"
    ESTORNO = "estorno"
    AJUSTE_MANUAL = "ajuste_manual"


class LedgerTransacao(Base, UUIDMixin, TimestampMixin):
    """
    Ledger append-only. NUNCA fazer UPDATE numa linha existente.
    O saldo atual do tenant é sempre `saldo_apos_centavos` da última linha
    (ORDER BY criado_em DESC LIMIT 1), nunca uma coluna de saldo mutável solta
    — isso evita race condition em débito concorrente e dá auditoria completa de graça.
    """

    __tablename__ = "ledger_transacoes"
    __table_args__ = (
        Index("ix_ledger_tenant_criado", "tenant_id", "criado_em"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[TipoTransacao] = mapped_column(
        Enum(
            TipoTransacao,
            name="tipo_transacao",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    valor_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)  # negativo em consulta, positivo em recarga
    saldo_apos_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    referencia_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # id da consulta ou id do pagamento
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
