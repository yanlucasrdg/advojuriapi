import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Processo(Base, UUIDMixin, TimestampMixin):
    """
    Cache normalizado de processos. Populado a partir de adapters
    (hoje: DataJud). O campo `fonte` permite adicionar outras origens
    depois sem quebrar o contrato da API pública.
    """

    __tablename__ = "processos"

    numero_cnj: Mapped[str] = mapped_column(String(25), nullable=False, unique=True, index=True)
    tribunal: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    classe: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assunto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    orgao_julgador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valor_acao: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_ajuizamento: Mapped[date | None] = mapped_column(Date, nullable=True)
    segredo_justica: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fonte: Mapped[str] = mapped_column(String(30), nullable=False, default="datajud")
    atualizado_em: Mapped[datetime] = mapped_column(nullable=False)

    partes: Mapped[list["Parte"]] = relationship(back_populates="processo", cascade="all, delete-orphan")
    movimentos: Mapped[list["Movimento"]] = relationship(back_populates="processo", cascade="all, delete-orphan")


class Parte(Base, UUIDMixin):
    __tablename__ = "partes"

    processo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    documento: Mapped[str | None] = mapped_column(String(20), nullable=True)  # nem sempre disponível via DataJud
    tipo_pessoa: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "fisica" | "juridica"
    polo: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "ativo" | "passivo" | "outros"

    processo: Mapped["Processo"] = relationship(back_populates="partes")


class Movimento(Base, UUIDMixin):
    __tablename__ = "movimentos"

    processo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data_movimento: Mapped[datetime] = mapped_column(nullable=False)
    descricao: Mapped[str] = mapped_column(String(500), nullable=False)
    codigo_cnj: Mapped[str | None] = mapped_column(String(20), nullable=True)  # tabela processual unificada CNJ
    hash_dedup: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # evita duplicar em re-sync

    processo: Mapped["Processo"] = relationship(back_populates="movimentos")
