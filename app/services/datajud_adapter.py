"""
Adapter da API Pública do DataJud (CNJ).

Referência oficial: https://datajud-wiki.cnj.jus.br/api-publica/
Endpoint por tribunal: https://api-publica.datajud.cnj.jus.br/api_publica_{alias}/_search
Autenticação: header "Authorization: APIKey <chave>" (chave pública, rotacionada
pelo CNJ periodicamente — não é uma credencial nossa, é a chave pública de acesso
oferecida pelo CNJ a qualquer desenvolvedor cadastrado em datajud.cnj.jus.br).

É uma API Elasticsearch por baixo: cada tribunal é um índice separado, e a
consulta é uma query DSL do Elasticsearch, não parâmetros REST simples.

LIMITAÇÃO CRÍTICA — NÃO IGNORAR:
O DataJud indexa nome das partes, mas NÃO indexa CPF/CNPJ como campo de busca
direto. "Buscar processo por CPF/CNPJ" (como promete a landing page) não é
suportado nativamente aqui. As opções reais são:
  1. Buscar por nome (fuzzy) e aceitar que o resultado é uma lista de candidatos,
     não um match exato garantido por CPF.
  2. Integrar uma segunda fonte que faça esse cruzamento (ex: um provedor de
     dados cadastrais que mapeie CPF -> nome, e então buscar por nome no DataJud).
  3. Deixar claro pro cliente que "busca por CPF" tem uma taxa de
     falso-positivo/negativo inerente à normalização de nomes.
Isso precisa ser resolvido no produto (schema `TipoBusca`) antes de vender
a funcionalidade como está na landing page hoje.
"""

from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.hashing import sha256_hex

settings = get_settings()

# Mapa parcial tribunal -> alias do índice DataJud.
# Lista completa (90+ tribunais) está no Anexo II do tutorial oficial do CNJ;
# isso deve ser carregado de uma tabela/arquivo de config, não hardcoded em produção.
ALIAS_TRIBUNAL: dict[str, str] = {
    "TRF1": "api_publica_trf1",
    "TRF2": "api_publica_trf2",
    "TRF3": "api_publica_trf3",
    "TRF4": "api_publica_trf4",
    "TRF5": "api_publica_trf5",
    "TRF6": "api_publica_trf6",
    "TST": "api_publica_tst",
    "TSE": "api_publica_tse",
    "STJ": "api_publica_stj",
    "TJSP": "api_publica_tjsp",
    "TJRJ": "api_publica_tjrj",
    "TJMG": "api_publica_tjmg",
    "TJCE": "api_publica_tjce",
    # ... completar com os demais TJs/TRTs/TREs a partir da lista oficial do CNJ
}


class DataJudError(Exception):
    pass


class DataJudAdapter:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.DATAJUD_BASE_URL,
            headers={
                "Authorization": f"APIKey {settings.DATAJUD_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "DataJudAdapter":
        return self

    async def __aexit__(self, *_exc_info) -> None:
        await self.close()

    async def _buscar_hits(self, tribunal: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Cada tribunal é um índice Elasticsearch separado: resolve o alias
        do índice, dispara a query DSL e devolve os `_source` dos hits."""
        alias = ALIAS_TRIBUNAL.get(tribunal.upper())
        if alias is None:
            raise DataJudError(f"Tribunal '{tribunal}' não mapeado em ALIAS_TRIBUNAL")

        resposta = await self._client.post(f"/{alias}/_search", json=query)
        resposta.raise_for_status()

        hits = resposta.json().get("hits", {}).get("hits", [])
        return [hit["_source"] for hit in hits]

    async def buscar_por_numero_cnj(self, numero_cnj: str, tribunal: str) -> dict[str, Any] | None:
        """
        Busca um processo pelo número CNJ dentro do índice de um tribunal específico.
        O tribunal precisa ser conhecido de antemão porque cada tribunal é um índice
        separado — não existe busca cross-tribunal num único request.
        """
        query = {
            "query": {
                "match": {
                    "numeroProcesso": numero_cnj.replace(".", "").replace("-", "")
                }
            }
        }

        hits = await self._buscar_hits(tribunal, query)
        return hits[0] if hits else None

    async def buscar_por_nome(self, nome: str, tribunal: str, tamanho: int = 20) -> list[dict[str, Any]]:
        """
        Busca por nome de parte (fuzzy match). Ver aviso de limitação no topo
        do arquivo — isto NÃO é equivalente a buscar por CPF/CNPJ.
        """
        query = {
            "size": tamanho,
            "query": {
                "match": {
                    "partes.nome": {
                        "query": nome,
                        "fuzziness": "AUTO",
                    }
                }
            },
        }

        return await self._buscar_hits(tribunal, query)


def normalizar_processo_datajud(bruto: dict[str, Any], tribunal: str) -> dict[str, Any]:
    """
    Converte o payload cru do DataJud (schema do CNJ) para o formato
    interno normalizado que a nossa API pública expõe. Mantém a API
    pública estável mesmo que o DataJud mude o schema deles.
    """
    movimentos_brutos = bruto.get("movimentos", []) or []
    movimentos = []
    for mov in movimentos_brutos:
        descricao = mov.get("nome", "")
        data_str = mov.get("dataHora", "")
        dedup_source = f"{data_str}|{descricao}"
        movimentos.append(
            {
                "data_movimento": data_str,
                "descricao": descricao,
                "codigo_cnj": str(mov.get("codigo", "")) or None,
                "hash_dedup": sha256_hex(dedup_source),
            }
        )

    partes_brutas = bruto.get("partes", []) or []
    partes = [
        {
            "nome": p.get("nome", ""),
            "documento": None,  # DataJud não expõe CPF/CNPJ da parte na maioria dos casos
            "tipo_pessoa": p.get("tipoPessoa"),
            "polo": p.get("polo"),
        }
        for p in partes_brutas
    ]

    return {
        "numero_cnj": bruto.get("numeroProcesso", ""),
        "tribunal": tribunal.upper(),
        "classe": (bruto.get("classe") or {}).get("nome"),
        "assunto": ", ".join(a.get("nome", "") for a in bruto.get("assuntos", []) or []) or None,
        "orgao_julgador": (bruto.get("orgaoJulgador") or {}).get("nome"),
        "valor_acao": None,  # nem sempre presente no DataJud; depende do tribunal
        "data_ajuizamento": bruto.get("dataAjuizamento"),
        "segredo_justica": bruto.get("nivelSigilo", 0) > 0,
        "fonte": "datajud",
        "atualizado_em": datetime.now(timezone.utc),
        "partes": partes,
        "movimentos": movimentos,
    }
