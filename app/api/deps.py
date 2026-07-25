from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_api_key
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.tenant import Tenant

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


def _extrair_bearer(valor_header: str | None) -> str:
    if not valor_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header Authorization ausente. Use: Authorization: Bearer sua_chave",
        )
    partes = valor_header.split(" ", 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato inválido. Use: Authorization: Bearer sua_chave",
        )
    return partes[1]


async def get_current_tenant(
    authorization: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    chave_texto_puro = _extrair_bearer(authorization)
    chave_hash = hash_api_key(chave_texto_puro)

    stmt = select(ApiKey).where(ApiKey.chave_hash == chave_hash)
    resultado = await db.execute(stmt)
    api_key = resultado.scalar_one_or_none()

    if api_key is None or not api_key.ativa:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida ou revogada")

    stmt_tenant = select(Tenant).where(Tenant.id == api_key.tenant_id)
    resultado_tenant = await db.execute(stmt_tenant)
    tenant = resultado_tenant.scalar_one_or_none()

    if tenant is None or not tenant.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta inativa ou suspensa")

    return tenant
