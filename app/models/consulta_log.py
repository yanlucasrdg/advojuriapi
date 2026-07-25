import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ConsultaLog(Base, UUIDMixin, TimestampMixin):
    """
    Log de auditoria de billing. `termo_busca_hash` guarda o hash do termo
    pesquisado (CPF/nome/numero), não o valor em texto claro — precisamos
    auditar volume e custo, não reter indefinidamente o dado pessoal buscado.
    Se for necessário investigar um caso específico, o hash é reproduzível
    a partir do termo original (mesma função de hash), então dá pra
    correlacionar sob demanda sem manter uma cópia solta.
    """

    __tablename__ = "consultas_log"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_busca: Mapped[str] = mapped_column(String(30), nullable=False)  # numero_cnj|cpf|cnpj|nome|oab
    termo_busca_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    custo_centavos: Mapped[int] = mapped_column(Integer, nullable=False)
    resultado_encontrado: Mapped[bool] = mapped_column(nullable=False, default=False)
    origem_cache: Mapped[bool] = mapped_column(nullable=False, default=False)  # veio do cache ou bateu no DataJud?
