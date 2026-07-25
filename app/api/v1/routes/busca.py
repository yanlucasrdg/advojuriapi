import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant
from app.core.config import get_settings
from app.db.session import get_db
from app.models.consulta_log import ConsultaLog
from app.models.tenant import Tenant
from app.schemas.busca import BuscaResponse, ConfiancaMatch, ResultadoBusca, TipoBusca
from app.services import billing
from app.services.cnpj_resolver import CnpjNaoEncontradoError, CnpjResolverError, resolver_razao_social
from app.services.datajud_adapter import DataJudAdapter, DataJudError, normalizar_processo_datajud

router = APIRouter(prefix="/busca", tags=["busca"])
settings = get_settings()


def _hash_termo(termo: str) -> str:
    return hashlib.sha256(termo.strip().lower().encode("utf-8")).hexdigest()


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
    termo_hash = _hash_termo(termo)

    # Checa saldo antes de qualquer fan-out custoso.
    saldo_atual = await billing.obter_saldo_atual(db, tenant.id)
    if saldo_atual < custo:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Saldo insuficiente")

    termo_resolvido = None
    nome_busca = termo
    aviso = None

    if tipo == TipoBusca.CNPJ:
        try:
            info = await resolver_razao_social(termo)
        except CnpjNaoEncontradoError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CNPJ não encontrado na Receita Federal")
        except CnpjResolverError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        nome_busca = info["razao_social"]
        termo_resolvido = nome_busca
        aviso = (
            "CNPJ resolvido para razão social via dados públicos da Receita Federal, "
            "e então pesquisado por nome no DataJud. Resultado é por aproximação de "
            "nome, não garantia de match exato por CNPJ (o DataJud não indexa CNPJ "
            "da parte diretamente)."
        )

    # Fan-out nos tribunais alvo. Cada chamada é independente — uma falha
    # isolada num tribunal não derruba a busca inteira, só some do resultado.
    resultados: list[ResultadoBusca] = []
    adapter = DataJudAdapter()
    try:
        for tribunal in tribunais_alvo:
            try:
                brutos = await adapter.buscar_por_nome(
                    nome_busca, tribunal, tamanho=settings.LIMITE_RESULTADOS_BUSCA_NOME
                )
            except DataJudError:
                continue  # tribunal não mapeado — pula, não derruba a busca inteira
            except Exception:
                continue  # timeout/erro de rede pontual no tribunal — idem

            for bruto in brutos:
                dados = normalizar_processo_datajud(bruto, tribunal)
                resultados.append(
                    ResultadoBusca(processo=dados, confianca_match=ConfiancaMatch.PROVAVEL)
                )
    finally:
        await adapter.close()

    # Cobra pela busca (mesmo com zero resultados — o trabalho de pesquisar
    # em N tribunais foi feito; diferente de /processos, aqui não há "match
    # exato" que justifique isentar consulta sem resultado).
    try:
        await billing.debitar(db, tenant.id, custo, descricao=f"Busca por {tipo.value}")
    except billing.SaldoInsuficienteError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Saldo insuficiente")

    db.add(
        ConsultaLog(
            tenant_id=tenant.id,
            tipo_busca=tipo.value,
            termo_busca_hash=termo_hash,
            custo_centavos=custo,
            resultado_encontrado=len(resultados) > 0,
            origem_cache=False,
        )
    )
    await db.commit()

    return BuscaResponse(
        tipo_busca=tipo,
        termo_resolvido=termo_resolvido,
        tribunais_pesquisados=tribunais_alvo,
        resultados=resultados,
        aviso=aviso,
    )
