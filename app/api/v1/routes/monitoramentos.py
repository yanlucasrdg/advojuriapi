import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_tenant
from app.core.cnj import normalizar_numero_cnj
from app.core.security import gerar_webhook_secret
from app.core.ssrf import WebhookUrlInseguraError, validar_url_webhook
from app.db.session import get_db
from app.models.monitoramento import Monitoramento
from app.models.processo import Processo
from app.models.tenant import Tenant
from app.schemas.monitoramento import MonitoramentoCreate, MonitoramentoCriadoResponse, MonitoramentoResponse

router = APIRouter(prefix="/monitoramentos", tags=["monitoramentos"])


@router.post("", response_model=MonitoramentoCriadoResponse, status_code=status.HTTP_201_CREATED)
async def criar_monitoramento(
    payload: MonitoramentoCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Cria um monitoramento. O processo precisa já existir no nosso cache
    (ou seja, ter sido consultado ao menos uma vez via /v1/processos) —
    não criamos monitoramento "às cegas" para número que nunca validamos
    contra o DataJud, porque não saberíamos nem se o processo existe.
    """
    # A validação resolve DNS (bloqueante): fora do event loop.
    try:
        await run_in_threadpool(validar_url_webhook, payload.webhook_url)
    except WebhookUrlInseguraError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Ver app/core/cnj.py — o valor salvo vem do DataJud sem pontuação,
    # a busca precisa usar o mesmo formato, senão nunca bate com o que já
    # está no cache (mesmo bug já corrigido antes em /v1/processos,
    # reaparecendo aqui por ser uma rota separada que nunca recebeu o
    # mesmo fix — motivo pelo qual isso agora é uma função compartilhada,
    # não mais lógica duplicada em cada rota).
    numero_cnj_normalizado = normalizar_numero_cnj(payload.numero_cnj)
    stmt = select(Processo).where(Processo.numero_cnj == numero_cnj_normalizado)
    resultado = await db.execute(stmt)
    processo = resultado.scalar_one_or_none()

    if processo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processo não encontrado no cache. Consulte via GET /v1/processos/{numero_cnj} primeiro.",
        )

    webhook_secret = gerar_webhook_secret()
    monitoramento = Monitoramento(
        tenant_id=tenant.id,
        processo_id=processo.id,
        webhook_url=payload.webhook_url,
        webhook_secret=webhook_secret,
        ativo=True,
    )
    db.add(monitoramento)
    await db.commit()
    await db.refresh(monitoramento)

    resposta = MonitoramentoCriadoResponse.model_validate(monitoramento)
    resposta.webhook_secret = webhook_secret
    return resposta


@router.get("", response_model=list[MonitoramentoResponse])
async def listar_monitoramentos(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Monitoramento).where(Monitoramento.tenant_id == tenant.id)
    resultado = await db.execute(stmt)
    return resultado.scalars().all()


@router.delete("/{monitoramento_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancelar_monitoramento(
    monitoramento_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Monitoramento).where(
        Monitoramento.id == monitoramento_id, Monitoramento.tenant_id == tenant.id
    )
    resultado = await db.execute(stmt)
    monitoramento = resultado.scalar_one_or_none()

    if monitoramento is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoramento não encontrado")

    # Soft delete (ativo=False) em vez de DROP: mantém o histórico de
    # alertas_enviados íntegro para auditoria, e o worker simplesmente
    # ignora monitoramentos inativos na próxima varredura.
    monitoramento.ativo = False
    await db.commit()
