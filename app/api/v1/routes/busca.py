from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant
from app.db.session import get_db
from app.models.tenant import Tenant
from app.schemas.busca import BuscaResponse, TipoBusca

router = APIRouter(prefix="/busca", tags=["busca"])


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
    DESATIVADO — ver app/services/_busca_por_parte_dormant.py para o motivo
    e o código completo, mantido pronto pra reativar.

    Resumo: confirmado empiricamente (20/20 processos verificados via
    console, TRF3 + TJSP) que a API Pública do DataJud não expõe nome de
    parte em nenhum processo, de nenhum tribunal testado — não é sigilo
    pontual, é ausência estrutural do campo no schema público. A
    documentação do CNJ já sugeria isso ("capas processuais e
    movimentações", sem menção a partes), mas só ficou inequívoco depois
    de inspecionar respostas reais.

    Isso significa que busca por CNPJ/nome, do jeito que foi desenhada
    (fuzzy match em partes.nome), é logicamente impossível com essa fonte
    — não é um bug de query, de tribunal faltando, ou de formatação. Não
    tem correção de código pra isso. Continuar oferecendo esse endpoint
    fingindo que funciona (retornando 200 com lista sempre vazia) seria
    pior que desativar: cobraria o cliente por um resultado que nunca
    pode vir a existir.
    """
    if tipo == TipoBusca.CPF:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Busca por CPF não é suportada: não existe base pública que "
                "mapeie CPF a nome no Brasil (dado protegido por LGPD)."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Busca por CNPJ/nome está temporariamente desativada: a API "
            "Pública do DataJud não expõe nome de parte em nenhum processo "
            "(confirmado em produção, não é limitação de query nossa). "
            "Use GET /v1/processos/{numero_cnj} para consulta por número "
            "exato, que funciona normalmente."
        ),
    )
