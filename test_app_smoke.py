from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Tenant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tenants"

    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    documento: Mapped[str | None] = mapped_column(String(20), nullable=True)  # CPF/CNPJ do titular da conta
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
