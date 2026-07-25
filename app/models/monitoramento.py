import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Monitoramento(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "monitoramentos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    processo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    webhook_url: Mapped[str] = mapped_column(String(500), nullable=False)
    webhook_secret: Mapped[str] = mapped_column(String(64), nullable=False)  # HMAC signing, gerado na criação
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ultima_verificacao_em: Mapped[datetime | None] = mapped_column(nullable=True)

    alertas: Mapped[list["AlertaEnviado"]] = relationship(back_populates="monitoramento")


class AlertaEnviado(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "alertas_enviados"

    monitoramento_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitoramentos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    movimento_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status_entrega: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente")  # pendente|entregue|falhou
    tentativas: Mapped[int] = mapped_column(default=0, nullable=False)

    monitoramento: Mapped["Monitoramento"] = relationship(back_populates="alertas")
