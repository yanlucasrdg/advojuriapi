import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import consultas
from app.api.deps import get_current_tenant
from app.core.config import get_settings
from app.core.hashing import hash_termo_busca
from app.db.session import get_db
from app.models.tenant import Tenant
from app.schemas.busca import BuscaResponse, ConfiancaMatch, ResultadoBusca, TipoBusca
from app.services.cnpj_resolver import (
    CnpjInvalidoError,
    CnpjNaoEncontradoError,
    CnpjResolverError,
    resolver_razao_social,
)
from app.services.datajud_adapter import (
    DataJudAdapter,
    DataJudError,
    normalizar_processo_datajud,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/busca", tags=["busca"])
settings = get_settings()


@router.get("", response_model=BuscaResponse)
async def buscar(
    tipo: TipoBusca,
    termo: str = Query(..., description="CPF, CNPJ ou nome, conforme o tipo"),
    tribunais: list[str] | None = Query(
        default=None, description="Lista de tribunais a pesquisar. Default: lista curada em config."
    ),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Busca por CNPJ ou nome (fuzzy). CPF não é suportado — ver aviso abaixo.

    Diferente de /v1/processos/{numero_cnj}, esta busca não tem garantia de
    match exato: retorna candidatos com `confianca_match`, porque o DataJud
    não faz busca cross-tribunal nem indexa CPF/CNPJ da parte diretamente.
    """
    if tipo == TipoBusca.CPF:
        # Não fingimos suporte: não existe base pública/gratuita de CPF -> nome
        # no Brasil (dado protegido por LGPD, diferente do CNPJ que é aberto
        # na Receita Federal). Um provedor comercial de dados cadastrais
        # (bureau de crédito, etc.) seria necessário aqui, com sua própria
        # base legal de tratamento — isso é uma decisão de produto/jurídica,
        # não uma implementação pendente.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Busca direta por CPF não é suportada: não existe base pública "
                "que mapeie CPF a nome no Brasil. Use tipo=nome com o nome "
                "completo da pessoa, ciente de que o resultado é por "
                "aproximação de nome, não um match garantido por CPF."
            ),
        )

    tribunais_alvo = tribunais or settings.TRIBUNAIS_BUSCA_PADRAO
    custo = settings.PRECO_BUSCA_PARTE_CENTAVOS
    termo_hash = hash_termo_busca(termo)

    # Checa saldo antes de qualquer fan-out custoso.
    await consultas.garantir_saldo(db, tenant.id, custo)

    termo_resolvido = None
    nome_busca = termo
    aviso = None

    if tipo == TipoBusca.CNPJ:
        try:
            info = await resolver_razao_social(termo)
        except CnpjNaoEncontradoError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="CNPJ não encontrado na Receita Federal"
            ) from exc
        except CnpjInvalidoError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except CnpjResolverError as exc:
            # Falha da BrasilAPI, não do cliente: 502, e sem cobrar a busca.
            logger.warning("Resolução de CNPJ falhou: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Falha ao resolver o CNPJ na base pública da Receita Federal",
            ) from exc

        nome_busca = info["razao_social"]
        termo_resolvido = nome_busca
        aviso = (
            "CNPJ resolvido para razão social via dados públicos da Receita Federal, "
            "e então pesquisado por nome no DataJud. Resultado é por aproximação de "
            "nome, não garantia de match exato por CNPJ (o DataJud não indexa CNPJ "
            "da parte diretamente)."
        )

    # Fan-out nos tribunais alvo. Cada chamada é independente — uma falha
    # isolada num tribunal não derruba a busca inteira, mas também não pode
    # sumir em silêncio: o tribunal que falhou vai logado e devolvido em
    # `tribunais_com_falha`, senão "zero resultados" fica indistinguível de
    # "a fonte estava fora do ar" — e o cliente paga pelos dois igual.
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
                resultados.append(
                    ResultadoBusca(processo=dados, confianca_match=ConfiancaMatch.PROVAVEL)
                )
    finally:
        await adapter.close()

    if len(tribunais_com_falha) == len(tribunais_alvo):
        # Nenhum tribunal respondeu: não existe busca a cobrar, e devolver
        # 200 com lista vazia mentiria dizendo "nada consta".
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Nenhum tribunal respondeu à busca (falha na fonte de dados). Nada foi cobrado.",
        )

    # Cobra pela busca (mesmo com zero resultados — o trabalho de pesquisar
    # em N tribunais foi feito; diferente de /processos, aqui não há "match
    # exato" que justifique isentar consulta sem resultado).
    await consultas.cobrar(db, tenant.id, custo, descricao=f"Busca por {tipo.value}")

    consultas.registrar_consulta(
        db,
        tenant.id,
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
