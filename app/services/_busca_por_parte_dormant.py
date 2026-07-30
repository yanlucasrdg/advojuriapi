"""
Lógica de busca por CNPJ/nome — DESATIVADA, mantida aqui pronta pra
reativar, não deletada.

Motivo da desativação (ver app/api/v1/routes/busca.py para o detalhe):
confirmado empiricamente que a API Pública do DataJud não expõe nome de
parte em nenhum processo verificado (20/20 amostras, TRF3 + TJSP). O
fuzzy match em `partes.nome` que essa função faz é logicamente incapaz de
encontrar qualquer resultado, porque o campo não existe na fonte.

Como reativar, se um dia fizer sentido (ex: integrar um provedor pago que
tenha dado de parte, tipo bureau de dados cadastrais ou um agregador
comercial de jurisprudência):
1. Trocar `adapter.buscar_por_nome(...)` abaixo pela chamada real pra
   essa nova fonte (o resto do fluxo — resolver CNPJ via BrasilAPI,
   fan-out por tribunal, cobrança, log — continua válido como está).
2. Mover essa função de volta pra dentro da rota em
   app/api/v1/routes/busca.py, substituindo o HTTPException 501.
3. Reativar os testes em tests/test_busca.py que validam
   ResultadoBusca/normalizar_processo_datajud (esses nunca foram
   removidos — continuam passando, só não são mais exercitados pela rota).
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api import consultas
from app.core.config import get_settings
from app.core.hashing import hash_termo_busca
from app.schemas.busca import BuscaResponse, ConfiancaMatch, ResultadoBusca, TipoBusca
from app.services.cnpj_resolver import (
    CnpjInvalidoError,
    CnpjNaoEncontradoError,
    CnpjResolverError,
    resolver_razao_social,
)
from app.services.datajud_adapter import DataJudAdapter, DataJudError, normalizar_processo_datajud

logger = logging.getLogger(__name__)
settings = get_settings()


class BuscaErro(Exception):
    """Erro genérico pra sinalizar pro chamador (a rota) que status HTTP usar.
    Existe só porque esta função não é mais uma rota FastAPI diretamente —
    não pode levantar HTTPException aqui sem acoplar ao Starlette."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def buscar_por_cnpj_ou_nome(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tipo: TipoBusca,
    termo: str,
    tribunais: list[str] | None = None,
) -> BuscaResponse:
    tribunais_alvo = tribunais or settings.TRIBUNAIS_BUSCA_PADRAO
    custo = settings.PRECO_BUSCA_PARTE_CENTAVOS
    termo_hash = hash_termo_busca(termo)

    await consultas.garantir_saldo(db, tenant_id, custo)

    termo_resolvido = None
    nome_busca = termo
    aviso = None

    if tipo == TipoBusca.CNPJ:
        try:
            info = await resolver_razao_social(termo)
        except CnpjNaoEncontradoError as exc:
            raise BuscaErro(404, "CNPJ não encontrado na Receita Federal") from exc
        except CnpjInvalidoError as exc:
            raise BuscaErro(400, str(exc)) from exc
        except CnpjResolverError as exc:
            logger.warning("Resolução de CNPJ falhou: %s", exc)
            raise BuscaErro(502, "Falha ao resolver o CNPJ na base pública da Receita Federal") from exc

        nome_busca = info["razao_social"]
        termo_resolvido = nome_busca
        aviso = (
            "CNPJ resolvido para razão social via dados públicos da Receita Federal, "
            "e então pesquisado por nome no DataJud."
        )

    resultados: list[ResultadoBusca] = []
    tribunais_com_falha: list[str] = []
    adapter = DataJudAdapter()
    try:
        for tribunal in tribunais_alvo:
            try:
                brutos = await adapter.buscar_por_nome(
                    nome_busca, tribunal, tamanho=settings.LIMITE_RESULTADOS_BUSCA_NOME
                )
            except DataJudError as exc:
                logger.warning("Busca por nome falhou no tribunal %s: %s", tribunal, exc)
                tribunais_com_falha.append(tribunal)
                continue
            except Exception:
                logger.exception("Erro inesperado na busca por nome no tribunal %s", tribunal)
                tribunais_com_falha.append(tribunal)
                continue

            for bruto in brutos:
                dados = normalizar_processo_datajud(bruto, tribunal)
                resultados.append(ResultadoBusca(processo=dados, confianca_match=ConfiancaMatch.PROVAVEL))
    finally:
        await adapter.close()

    if len(tribunais_com_falha) == len(tribunais_alvo):
        raise BuscaErro(502, "Nenhum tribunal respondeu à busca (falha na fonte de dados). Nada foi cobrado.")

    await consultas.cobrar(db, tenant_id, custo, descricao=f"Busca por {tipo.value}")
    consultas.registrar_consulta(
        db,
        tenant_id,
        tipo_busca=tipo.value,
        termo_hash=termo_hash,
        custo_centavos=custo,
        resultado_encontrado=len(resultados) > 0,
        origem_cache=False,
    )
    await db.commit()

    if tribunais_com_falha:
        aviso_parcial = (
            "Resultado parcial: não foi possível consultar "
            f"{', '.join(tribunais_com_falha)}. Repita a busca para cobrir esses tribunais."
        )
        aviso = f"{aviso} {aviso_parcial}" if aviso else aviso_parcial

    return BuscaResponse(
        tipo_busca=tipo,
        termo_resolvido=termo_resolvido,
        tribunais_pesquisados=[t for t in tribunais_alvo if t not in tribunais_com_falha],
        tribunais_com_falha=tribunais_com_falha,
        resultados=resultados,
        aviso=aviso,
    )
