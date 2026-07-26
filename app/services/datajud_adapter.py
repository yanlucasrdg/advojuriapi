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

import hashlib
import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.hashing import sha256_hex

logger = logging.getLogger(__name__)
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
    """Base de todos os erros do adapter. Nunca deixamos httpx.* vazar daqui:
    o chamador precisa distinguir "pedido inválido" de "fonte externa quebrada"
    sem conhecer a biblioteca HTTP que usamos por baixo."""


class TribunalNaoMapeadoError(DataJudError):
    """Erro do chamador: tribunal fora de ALIAS_TRIBUNAL. Vira 400."""


class DataJudIndisponivelError(DataJudError):
    """Falha de rede, timeout ou status de erro vindo do DataJud. Vira 502."""


class DataJudRespostaInvalidaError(DataJudError):
    """DataJud respondeu 200 com um corpo que não bate com o schema esperado. Vira 502."""


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
        try:
            await self._client.aclose()
        except Exception:
            # Fechar o client nunca deve mascarar o erro (ou o resultado) da
            # chamada que acabou de acontecer no bloco try do chamador.
            logger.warning("Falha ao fechar o client HTTP do DataJud", exc_info=True)

    @staticmethod
    def _resolver_alias(tribunal: str) -> str:
        alias = ALIAS_TRIBUNAL.get(tribunal.upper())
        if alias is None:
            raise TribunalNaoMapeadoError(f"Tribunal '{tribunal}' não mapeado em ALIAS_TRIBUNAL")
        return alias

    async def _search(self, alias: str, query: dict[str, Any]) -> dict[str, Any]:
        """Executa a query e traduz qualquer falha de transporte/protocolo
        para a hierarquia DataJudError."""
        try:
            resposta = await self._client.post(f"/{alias}/_search", json=query)
            resposta.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "DataJud respondeu %s para o índice %s: %s",
                exc.response.status_code, alias, exc.response.text[:500],
            )
            raise DataJudIndisponivelError(
                f"DataJud retornou HTTP {exc.response.status_code} para o índice '{alias}'"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Falha de rede ao consultar o DataJud (%s): %s", alias, exc)
            raise DataJudIndisponivelError(f"Falha ao consultar o DataJud ('{alias}'): {exc}") from exc

        try:
            corpo = resposta.json()
        except ValueError as exc:
            logger.warning("DataJud devolveu corpo não-JSON para o índice %s", alias)
            raise DataJudRespostaInvalidaError(f"Resposta do DataJud não é JSON válido ('{alias}')") from exc

        if not isinstance(corpo, dict):
            raise DataJudRespostaInvalidaError(f"Resposta do DataJud não é um objeto JSON ('{alias}')")
        return corpo

    @staticmethod
    def _extrair_hits(corpo: dict[str, Any], alias: str) -> list[dict[str, Any]]:
        hits = (corpo.get("hits") or {}).get("hits")
        if hits is None:
            return []
        if not isinstance(hits, list):
            raise DataJudRespostaInvalidaError(f"Campo 'hits.hits' inesperado na resposta do DataJud ('{alias}')")

        fontes: list[dict[str, Any]] = []
        for hit in hits:
            fonte = hit.get("_source") if isinstance(hit, dict) else None
            if not isinstance(fonte, dict):
                # Um hit malformado não invalida os demais, mas também não pode
                # sumir sem registro — é sinal de mudança de schema no CNJ.
                logger.warning("Hit sem '_source' utilizável na resposta do DataJud (%s)", alias)
                continue
            fontes.append(fonte)
        return fontes

    async def __aenter__(self) -> "DataJudAdapter":
        return self

    async def __aexit__(self, *_exc_info) -> None:
        await self.close()

    async def buscar_por_numero_cnj(self, numero_cnj: str, tribunal: str) -> dict[str, Any] | None:
        """
        Busca um processo pelo número CNJ dentro do índice de um tribunal específico.
        O tribunal precisa ser conhecido de antemão porque cada tribunal é um índice
        separado — não existe busca cross-tribunal num único request.
        """
        alias = self._resolver_alias(tribunal)

        query = {
            "query": {
                "match": {
                    "numeroProcesso": numero_cnj.replace(".", "").replace("-", "")
                }
            }
        }

        corpo = await self._search(alias, query)
        hits = self._extrair_hits(corpo, alias)
        return hits[0] if hits else None

    async def buscar_por_nome(self, nome: str, tribunal: str, tamanho: int = 20) -> list[dict[str, Any]]:
        """
        Busca por nome de parte (fuzzy match). Ver aviso de limitação no topo
        do arquivo — isto NÃO é equivalente a buscar por CPF/CNPJ.
        """
        alias = self._resolver_alias(tribunal)

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

        corpo = await self._search(alias, query)
        return self._extrair_hits(corpo, alias)


def _parse_data_datajud(valor: str | None) -> datetime | None:
    """
    Parseia datas/horas vindas do DataJud.

    Formato observado em produção (dado real, não fixture escrita à mão):
    string compacta 'YYYYMMDDHHMMSS' sem separador nenhum, ex:
    '20230714163257' = 2023-07-14 16:32:57. Isso só foi descoberto depois
    do primeiro request real contra o DataJud em produção — os testes
    locais usavam fixtures em ISO 8601 (suposição errada de como o CNJ
    formata isso, nunca validada contra uma resposta de verdade).

    Mantém fallback para ISO 8601 como segunda tentativa, caso o formato
    varie entre tribunais ou o CNJ mude o schema no futuro — em vez de
    assumir que o formato compacto é a única verdade possível.
    """
    if not valor:
        return None
    valor = valor.strip()

    if valor.isdigit() and len(valor) == 14:
        try:
            return datetime.strptime(valor, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Não foi possível parsear data do DataJud: %r", valor)
        return None


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
        data_movimento_dt = _parse_data_datajud(data_str)
        if data_movimento_dt is None:
            # data_movimento é NOT NULL no banco — um movimento sem data
            # parseável não pode virar linha inválida; melhor perder esse
            # movimento específico (com log) do que quebrar a consulta
            # inteira ou gravar lixo.
            logger.warning("Movimento sem data parseável, ignorado: %r", mov)
            continue
        dedup_source = f"{data_str}|{descricao}"
        movimentos.append(
            {
                "data_movimento": data_movimento_dt,
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

    data_ajuizamento_dt = _parse_data_datajud(bruto.get("dataAjuizamento"))

    return {
        "numero_cnj": bruto.get("numeroProcesso", ""),
        "tribunal": tribunal.upper(),
        "classe": (bruto.get("classe") or {}).get("nome"),
        "assunto": ", ".join(a.get("nome", "") for a in bruto.get("assuntos", []) or []) or None,
        "orgao_julgador": (bruto.get("orgaoJulgador") or {}).get("nome"),
        "valor_acao": None,  # nem sempre presente no DataJud; depende do tribunal
        "data_ajuizamento": data_ajuizamento_dt.date() if data_ajuizamento_dt else None,
        "segredo_justica": (bruto.get("nivelSigilo") or 0) > 0,
        "fonte": "datajud",
        "atualizado_em": datetime.now(timezone.utc),
        "partes": partes,
        "movimentos": movimentos,
    }
