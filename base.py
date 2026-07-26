"""
Passos que todo endpoint de consulta cobrada repete: checar saldo antes de
gastar rate-limit da fonte externa, debitar traduzindo saldo insuficiente
para 402, e registrar a consulta no log de auditoria.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consulta_log import ConsultaLog
from app.services import billing

DETALHE_SALDO_INSUFICIENTE = "Saldo insuficiente"


def _erro_saldo_insuficiente() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=DETALHE_SALDO_INSUFICIENTE
    )


async def garantir_saldo(db: AsyncSession, tenant_id: uuid.UUID, custo: int) -> None:
    """Checagem antecipada, antes de qualquer trabalho custoso (DataJud, fan-out)."""
    if await billing.obter_saldo_atual(db, tenant_id) < custo:
        raise _erro_saldo_insuficiente()


async def cobrar(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    custo: int,
    descricao: str,
    referencia_id: str | None = None,
) -> None:
    """Débito sem commit: o commit fica com o endpoint, para que débito e
    gravação do resultado caiam na mesma transação."""
    try:
        await billing.debitar(db, tenant_id, custo, referencia_id=referencia_id, descricao=descricao)
    except billing.SaldoInsuficienteError:
        await db.rollback()
        raise _erro_saldo_insuficiente()


def registrar_consulta(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tipo_busca: str,
    termo_hash: str,
    custo_centavos: int,
    resultado_encontrado: bool,
    origem_cache: bool,
) -> None:
    db.add(
        ConsultaLog(
            tenant_id=tenant_id,
            tipo_busca=tipo_busca,
            termo_busca_hash=termo_hash,
            custo_centavos=custo_centavos,
            resultado_encontrado=resultado_encontrado,
            origem_cache=origem_cache,
        )
    )
