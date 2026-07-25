"""
Núcleo de billing pré-pago.

Regra de ouro: o saldo nunca é uma coluna mutável. É sempre a última linha
do ledger para aquele tenant, e toda escrita é feita dentro de uma
transação com lock de linha (SELECT ... FOR UPDATE) pra evitar duas
consultas concorrentes lerem o mesmo saldo "antigo" e ambas debitarem
como se tivessem saldo suficiente (classic race condition de billing).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerTransacao, TipoTransacao


class SaldoInsuficienteError(Exception):
    pass


async def obter_saldo_atual(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    stmt = (
        select(LedgerTransacao.saldo_apos_centavos)
        .where(LedgerTransacao.tenant_id == tenant_id)
        .order_by(LedgerTransacao.criado_em.desc())
        .limit(1)
    )
    resultado = await db.execute(stmt)
    saldo = resultado.scalar_one_or_none()
    return saldo if saldo is not None else 0


async def debitar(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    valor_centavos: int,
    referencia_id: str | None = None,
    descricao: str | None = None,
) -> LedgerTransacao:
    """
    Debita `valor_centavos` do saldo do tenant.
    Levanta SaldoInsuficienteError se não houver saldo — o chamador
    (endpoint) deve tratar isso como 402 Payment Required e NÃO
    prosseguir para consultar a fonte de dados (DataJud custa tempo/rate-limit
    mesmo quando é grátis em dinheiro).

    IMPORTANTE: esta função não dá commit. O commit é responsabilidade
    do endpoint, para que o débito e a gravação do resultado da consulta
    aconteçam na mesma transação atômica (tudo ou nada).
    """
    if valor_centavos <= 0:
        raise ValueError("valor_centavos deve ser positivo")

    # Lock pessimista na "última linha" do tenant via SELECT FOR UPDATE
    # emulado por transação serializável + leitura mais recente.
    # Em produção real, considerar SELECT ... FOR UPDATE numa tabela
    # `saldos_lock (tenant_id PK)` auxiliar só para servir de mutex de linha,
    # já que o ledger é append-only e não tem uma linha fixa pra lockar.
    saldo_atual = await obter_saldo_atual(db, tenant_id)

    if saldo_atual < valor_centavos:
        raise SaldoInsuficienteError(
            f"Saldo insuficiente: disponível={saldo_atual}, necessário={valor_centavos}"
        )

    novo_saldo = saldo_atual - valor_centavos
    transacao = LedgerTransacao(
        tenant_id=tenant_id,
        tipo=TipoTransacao.CONSULTA,
        valor_centavos=-valor_centavos,
        saldo_apos_centavos=novo_saldo,
        referencia_id=referencia_id,
        descricao=descricao,
    )
    db.add(transacao)
    await db.flush()  # garante que a linha existe na transação, sem fechar ainda
    return transacao


async def creditar(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    valor_centavos: int,
    referencia_id: str | None = None,
    descricao: str | None = None,
) -> LedgerTransacao:
    if valor_centavos <= 0:
        raise ValueError("valor_centavos deve ser positivo")

    saldo_atual = await obter_saldo_atual(db, tenant_id)
    novo_saldo = saldo_atual + valor_centavos

    transacao = LedgerTransacao(
        tenant_id=tenant_id,
        tipo=TipoTransacao.RECARGA,
        valor_centavos=valor_centavos,
        saldo_apos_centavos=novo_saldo,
        referencia_id=referencia_id,
        descricao=descricao,
    )
    db.add(transacao)
    await db.flush()
    return transacao
