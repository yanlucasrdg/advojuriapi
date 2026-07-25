from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_api_key
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.tenant import Tenant

# HTTPBearer (em vez de um APIKeyHeader genérico) faz o Swagger UI tratar
# isso como autenticação Bearer de verdade: o campo "Authorize" do /docs
# passa a aceitar só a chave, sem precisar digitar "Bearer " na mão —
# o próprio Swagger adiciona o prefixo antes de mandar o header.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_tenant(
    credenciais: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    if credenciais is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header Authorization ausente. Use: Authorization: Bearer sua_chave",
        )

    chave_hash = hash_api_key(credenciais.credentials)

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