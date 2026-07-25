import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant
from app.core.config import get_settings
from app.db.session import get_db
from app.models.tenant import Tenant
from app.schemas.saldo import RecargaRequest, RecargaResponse, SaldoResponse
from app.services import billing

router = APIRouter(prefix="/saldo", tags=["saldo"])
settings = get_settings()


@router.get("", response_model=SaldoResponse)
async def obter_saldo(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    centavos = await billing.obter_saldo_atual(db, tenant.id)
    return SaldoResponse.from_centavos(centavos)


@router.post("/recarga", response_model=RecargaResponse)
async def iniciar_recarga(
    payload: RecargaRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    MVP: credita direto (sem gateway de pagamento real integrado ainda).
    Em produção, isso deve ser um webhook de confirmação do gateway
    (Stripe/Pagar.me/Mercado Pago) — NUNCA creditar saldo direto a partir
    de uma chamada não autenticada pelo gateway, ou qualquer cliente
    autenticado poderia "recarregar" saldo de graça chamando este endpoint.
    Deixar explícito: este endpoint precisa ser substituído antes de produção.
    Por isso ele é bloqueado quando ENV=production — creditar saldo direto a
    partir de uma chamada do próprio cliente autenticado permitiria que
    qualquer um se "recarregasse" de graça. Em produção, o crédito só deve
    vir de um webhook assinado do gateway de pagamento.
    """
    if settings.ENV == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Recarga direta desabilitada em produção. O crédito de saldo "
                "só é feito via confirmação assinada do gateway de pagamento."
            ),
        )

    referencia = str(uuid.uuid4())
    transacao = await billing.creditar(
        db, tenant.id, payload.valor_centavos, referencia_id=referencia, descricao="Recarga (MVP sem gateway)"
    )
    await db.commit()
    return RecargaResponse(
        transacao_id=str(transacao.id),
        saldo_apos_centavos=transacao.saldo_apos_centavos,
        status="confirmada",
    )
