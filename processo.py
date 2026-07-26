from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.processo import Processo

settings = get_settings()


async def buscar_processo_em_cache(db: AsyncSession, numero_cnj: str) -> Processo | None:
    stmt = (
        select(Processo)
        .where(Processo.numero_cnj == numero_cnj)
        .options(selectinload(Processo.partes), selectinload(Processo.movimentos))
    )
    resultado = await db.execute(stmt)
    return resultado.scalar_one_or_none()


def cache_esta_fresco(processo: Processo) -> bool:
    """
    Movimentos mudam mais rápido que cadastro (classe/assunto/partes raramente
    mudam depois de distribuído). Usamos um TTL mais curto para considerar
    o cache "fresco o bastante pra não rebater na fonte".
    """
    agora = datetime.now(timezone.utc)
    limite = processo.atualizado_em + timedelta(hours=settings.CACHE_TTL_MOVIMENTOS_HORAS)
    return agora < limite
