"""
Resolve CNPJ -> razão social usando a BrasilAPI, que espelha dados
públicos da Receita Federal (CNPJ é aberto por natureza; CPF não é).

Por que não ir direto na Receita Federal: o dataset aberto da Receita é
um dump em CSV de ~20GB atualizado mensalmente, inviável de consultar
em tempo real request-a-request. A BrasilAPI já resolve esse trabalho
de ETL e serve via REST simples — é a peça certa para MVP.

IMPORTANTE (ver termos de uso da BrasilAPI, https://brasilapi.com.br/):
é um serviço comunitário mantido por voluntários, sem SLA formal e com
pedido explícito para não fazer scraping em loop/full-scan. Isso é
adequado para volume de "usuário final consultando um CNPJ por vez",
não para pré-popular um banco inteiro. Se o volume de consultas por CNPJ
crescer muito, a evolução correta é baixar o dump aberto da Receita
Federal periodicamente e servir localmente, não aumentar a carga na
BrasilAPI.
"""

import httpx

BRASILAPI_BASE_URL = "https://brasilapi.com.br/api/cnpj/v1"


class CnpjNaoEncontradoError(Exception):
    pass


class CnpjResolverError(Exception):
    pass


def normalizar_cnpj(cnpj: str) -> str:
    return "".join(c for c in cnpj if c.isdigit())


async def resolver_razao_social(cnpj: str) -> dict:
    """
    Retorna {"razao_social": str, "nome_fantasia": str | None, "situacao": str}.
    Levanta CnpjNaoEncontradoError se o CNPJ não existir na base da Receita.
    """
    cnpj_limpo = normalizar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        raise CnpjResolverError(f"CNPJ inválido: '{cnpj}' (esperado 14 dígitos)")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resposta = await client.get(f"{BRASILAPI_BASE_URL}/{cnpj_limpo}")
        except httpx.HTTPError as exc:
            raise CnpjResolverError(f"Falha ao consultar BrasilAPI: {exc}")

    if resposta.status_code == 404:
        raise CnpjNaoEncontradoError(f"CNPJ {cnpj} não encontrado na base da Receita Federal")
    resposta.raise_for_status()

    dados = resposta.json()
    return {
        "razao_social": dados.get("razao_social", ""),
        "nome_fantasia": dados.get("nome_fantasia") or None,
        "situacao": dados.get("descricao_situacao_cadastral"),
    }
