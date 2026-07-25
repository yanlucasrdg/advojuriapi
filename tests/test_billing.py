"""
Testes do núcleo de billing. Usa um engine sqlite in-memory como stand-in
rápido para validar a LÓGICA (débito, crédito, saldo insuficiente).
Isso NÃO substitui testar contra Postgres real antes de produção —
tipos como UUID e Enum se comportam diferente entre dialetos — mas
pega regressões de lógica de negócio rápido, sem precisar de infra.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.tenant import Tenant
from app.services import billing


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    t = Tenant(id=uuid.uuid4(), nome="Escritório Teste", email="teste@example.com", ativo=True)
    db_session.add(t)
    await db_session.commit()
    return t


@pytest.mark.asyncio
async def test_saldo_inicial_e_zero(db_session, tenant):
    saldo = await billing.obter_saldo_atual(db_session, tenant.id)
    assert saldo == 0


@pytest.mark.asyncio
async def test_creditar_aumenta_saldo(db_session, tenant):
    await billing.creditar(db_session, tenant.id, 5000, descricao="recarga teste")
    await db_session.commit()
    saldo = await billing.obter_saldo_atual(db_session, tenant.id)
    assert saldo == 5000


@pytest.mark.asyncio
async def test_debitar_reduz_saldo(db_session, tenant):
    await billing.creditar(db_session, tenant.id, 1000)
    await db_session.commit()

    await billing.debitar(db_session, tenant.id, 15, descricao="consulta teste")
    await db_session.commit()

    saldo = await billing.obter_saldo_atual(db_session, tenant.id)
    assert saldo == 985


@pytest.mark.asyncio
async def test_debitar_sem_saldo_levanta_erro(db_session, tenant):
    with pytest.raises(billing.SaldoInsuficienteError):
        await billing.debitar(db_session, tenant.id, 15)


@pytest.mark.asyncio
async def test_debitar_valor_exato_do_saldo_funciona(db_session, tenant):
    await billing.creditar(db_session, tenant.id, 15)
    await db_session.commit()

    await billing.debitar(db_session, tenant.id, 15)
    await db_session.commit()

    saldo = await billing.obter_saldo_atual(db_session, tenant.id)
    assert saldo == 0


@pytest.mark.asyncio
async def test_ledger_e_auditavel_apos_multiplas_operacoes(db_session, tenant):
    await billing.creditar(db_session, tenant.id, 10000, descricao="recarga 1")
    await db_session.commit()
    await billing.debitar(db_session, tenant.id, 15, descricao="consulta 1")
    await db_session.commit()
    await billing.debitar(db_session, tenant.id, 25, descricao="consulta 2")
    await db_session.commit()

    saldo_final = await billing.obter_saldo_atual(db_session, tenant.id)
    assert saldo_final == 10000 - 15 - 25
