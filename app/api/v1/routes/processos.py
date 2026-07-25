import hashlib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant
from app.core.config import get_settings
from app.db.session import get_db
from app.models.consulta_log import ConsultaLog
from app.models.processo import Movimento, Parte, Processo
from app.models.tenant import Tenant
from app.schemas.processo import ProcessoResponse
from app.services import billing, cache
from app.services.datajud_adapter import DataJudAdapter, DataJudError, normalizar_processo_datajud

router = APIRouter(prefix="/processos", tags=["processos"])
settings = get_settings()


def _hash_termo(termo: str) -> str:
    return hashlib.sha256(termo.strip().lower().encode("utf-8")).hexdigest()


@router.get("/{numero_cnj}", response_model=ProcessoResponse)
async def consultar_processo(
    numero_cnj: str,
    tribunal: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Consulta um processo pelo número CNJ.

    `tribunal` é obrigatório porque o DataJud indexa cada tribunal
    separadamente — não existe busca cross-tribunal num único request,
    então precisamos saber onde procurar antes de gastar o request.
    """
    custo = settings.PRECO_CONSULTA_PROCESSO_CENTAVOS
    termo_hash = _hash_termo(numero_cnj)

    # 1. Tenta cache primeiro — nem olha pro saldo se já temos o dado fresco,
    #    exceto que ainda cobra: o cliente está comprando "a resposta", não
    #    "o trabalho de ir buscar", então o preço é o mesmo esteja em cache ou não.
    processo_cacheado = await cache.buscar_processo_em_cache(db, numero_cnj)

    if processo_cacheado and cache.cache_esta_fresco(processo_cacheado):
        try:
            await billing.debitar(
                db, tenant.id, custo, referencia_id=str(processo_cacheado.id), descricao="Consulta (cache)"
            )
        except billing.SaldoInsuficienteError:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Saldo insuficiente")

        db.add(
            ConsultaLog(
                tenant_id=tenant.id,
                tipo_busca="numero_cnj",
                termo_busca_hash=termo_hash,
                custo_centavos=custo,
                resultado_encontrado=True,
                origem_cache=True,
            )
        )
        await db.commit()
        return processo_cacheado

    # 2. Cache miss (ou expirado) — checa saldo ANTES de bater na fonte externa.
    #    Não queremos gastar rate-limit do DataJud numa consulta que o
    #    cliente não vai conseguir pagar.
    saldo_atual = await billing.obter_saldo_atual(db, tenant.id)
    if saldo_atual < custo:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Saldo insuficiente")

    adapter = DataJudAdapter()
    try:
        bruto = await adapter.buscar_por_numero_cnj(numero_cnj, tribunal)
    except DataJudError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Falha ao consultar a fonte de dados (DataJud)"
        )
    finally:
        await adapter.close()

    if bruto is None:
        db.add(
            ConsultaLog(
                tenant_id=tenant.id,
                tipo_busca="numero_cnj",
                termo_busca_hash=termo_hash,
                custo_centavos=0,  # não cobra consulta sem resultado
                resultado_encontrado=False,
                origem_cache=False,
            )
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processo não encontrado")

    dados_normalizados = normalizar_processo_datajud(bruto, tribunal)

    # 3. Grava/atualiza no cache local + debita + loga — tudo na mesma transação.
    if processo_cacheado:
        processo = processo_cacheado
        for campo, valor in dados_normalizados.items():
            if campo not in ("partes", "movimentos"):
                setattr(processo, campo, valor)
        processo.partes.clear()
        processo.movimentos.clear()
    else:
        processo = Processo(**{k: v for k, v in dados_normalizados.items() if k not in ("partes", "movimentos")})
        db.add(processo)
        await db.flush()  # garante processo.id antes de criar as FKs abaixo

    for p in dados_normalizados["partes"]:
        db.add(Parte(processo_id=processo.id, **p))
    for m in dados_normalizados["movimentos"]:
        db.add(Movimento(processo_id=processo.id, **m))

    try:
        await billing.debitar(db, tenant.id, custo, referencia_id=str(processo.id), descricao="Consulta (DataJud)")
    except billing.SaldoInsuficienteError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Saldo insuficiente")

    db.add(
        ConsultaLog(
            tenant_id=tenant.id,
            tipo_busca="numero_cnj",
            termo_busca_hash=termo_hash,
            custo_centavos=custo,
            resultado_encontrado=True,
            origem_cache=False,
        )
    )
    await db.commit()
    await db.refresh(processo, attribute_names=["partes", "movimentos"])
    return processo
