import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ApiKey(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "api_keys"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chave_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    chave_prefixo_visivel: Mapped[str] = mapped_column(String(20), nullable=False)  # ex: "ajr_live_a1b2..." truncado, pra exibir no dashboard
    ambiente: Mapped[str] = mapped_column(String(10), nullable=False)  # "live" | "test"
    revogada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def ativa(self) -> bool:
        return self.revogada_em is None
