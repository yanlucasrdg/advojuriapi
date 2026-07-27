import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cnj import normalizar_numero_cnj
from app.api import consultas
from app.api.deps import get_current_tenant
from app.core.config import get_settings
from app.core.hashing import hash_termo_busca
from app.db.session import get_db
from app.models.processo import Movimento, Parte, Processo
from app.models.tenant import Tenant
from app.schemas.processo import ProcessoResponse
from app.services import cache
from app.services.datajud_adapter import (
    DataJudAdapter,
    DataJudError,
    TribunalNaoMapeadoError,
    normalizar_processo_datajud,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/processos", tags=["processos"])
settings = get_settings()


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

    # Normaliza uma vez só, no início, e usa essa versão em tudo daqui pra
    # frente. O DataJud devolve numeroProcesso sem pontuação (é o que fica
    # gravado no banco), mas o cliente pode mandar o número na URL com ou
    # sem pontuação — se não normalizar aqui, a busca no cache nunca bate
    # com o que já está salvo, todo request vira um "novo" processo, e a
    # segunda consulta em diante quebra com UniqueViolationError na hora
    # de inserir (bug real, encontrado ao testar a segunda chamada em
    # produção — a primeira sempre "funcionava" porque inseria do zero).
    numero_cnj = normalizar_numero_cnj(numero_cnj)
    termo_hash = hash_termo_busca(numero_cnj)

    # 1. Tenta cache primeiro — nem olha pro saldo se já temos o dado fresco,
    #    exceto que ainda cobra: o cliente está comprando "a resposta", não
    #    "o trabalho de ir buscar", então o preço é o mesmo esteja em cache ou não.
    processo_cacheado = await cache.buscar_processo_em_cache(db, numero_cnj)

    if processo_cacheado and cache.cache_esta_fresco(processo_cacheado):
        await consultas.cobrar(
            db, tenant.id, custo, referencia_id=str(processo_cacheado.id), descricao="Consulta (cache)"
        )
        consultas.registrar_consulta(
            db,
            tenant.id,
            tipo_busca="numero_cnj",
            termo_hash=termo_hash,
            custo_centavos=custo,
            resultado_encontrado=True,
            origem_cache=True,
        )
        await db.commit()
        return processo_cacheado

    # 2. Cache miss (ou expirado) — checa saldo ANTES de bater na fonte externa.
    #    Não queremos gastar rate-limit do DataJud numa consulta que o
    #    cliente não vai conseguir pagar.
    await consultas.garantir_saldo(db, tenant.id, custo)

    adapter = DataJudAdapter()
    try:
        bruto = await adapter.buscar_por_numero_cnj(numero_cnj, tribunal)
    except TribunalNaoMapeadoError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DataJudError as exc:
        logger.warning("Consulta ao DataJud falhou para %s/%s: %s", tribunal, numero_cnj, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Falha ao consultar a fonte de dados (DataJud)"
        ) from exc
    except Exception as exc:
        # Erro nosso, não do DataJud: registrar com stack trace em vez de
        # devolver um 502 genérico que apaga o rastro do bug.
        logger.exception("Erro inesperado ao consultar o DataJud para %s/%s", tribunal, numero_cnj)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Falha ao consultar a fonte de dados (DataJud)"
        ) from exc
    finally:
        await adapter.close()

    if bruto is None:
        consultas.registrar_consulta(
            db,
            tenant.id,
            tipo_busca="numero_cnj",
            termo_hash=termo_hash,
            custo_centavos=0,  # não cobra consulta sem resultado
            resultado_encontrado=False,
            origem_cache=False,
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

    await consultas.cobrar(db, tenant.id, custo, referencia_id=str(processo.id), descricao="Consulta (DataJud)")

    consultas.registrar_consulta(
        db,
        tenant.id,
        tipo_busca="numero_cnj",
        termo_hash=termo_hash,
        custo_centavos=custo,
        resultado_encontrado=True,
        origem_cache=False,
    )
    await db.commit()
    await db.refresh(processo, attribute_names=["partes", "movimentos"])
    return processo
