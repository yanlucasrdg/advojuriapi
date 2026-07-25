from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import gerar_api_key
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.tenant import Tenant

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    nome: str
    email: EmailStr


class SignupResponse(BaseModel):
    tenant_id: str
    api_key: str  # texto puro, mostrado UMA vez


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)):
    """
    Endpoint público de cadastro. Cria o tenant e já emite a primeira
    API key (ambiente "live", já que não existe conceito de sandbox
    fake nesta versão — CUIDADO, isso significa que qualquer consulta
    feita com essa chave debita saldo real).

    NÃO tem verificação de e-mail nem captcha — isso é aceitável para
    uma fase de pitch/demo com poucos usuários controlados, mas é uma
    porta aberta para abuso (qualquer um pode criar tenants em loop)
    antes de ir a público. Ver README para a lista de pendências.
    """
    stmt = select(Tenant).where(Tenant.email == payload.email)
    resultado = await db.execute(stmt)
    if resultado.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado")

    tenant = Tenant(nome=payload.nome, email=payload.email)
    db.add(tenant)
    await db.flush()

    chave_texto_puro, chave_hash = gerar_api_key("live")
    db.add(
        ApiKey(
            tenant_id=tenant.id,
            chave_hash=chave_hash,
            chave_prefixo_visivel=chave_texto_puro[:16] + "...",
            ambiente="live",
        )
    )
    await db.commit()

    return SignupResponse(tenant_id=str(tenant.id), api_key=chave_texto_puro)
