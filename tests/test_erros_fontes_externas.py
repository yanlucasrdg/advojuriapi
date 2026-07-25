"""
Testes das falhas das fontes externas (DataJud e BrasilAPI).

O ponto aqui não é o caminho feliz: é garantir que nenhuma exceção de
`httpx` vaze dos adapters. Se vazar, a rota não consegue distinguir
"pedido inválido" (4xx) de "fonte externa quebrada" (502), e o cliente
acaba recebendo 500 — ou pior, um resultado vazio que parece "nada consta".
"""

import httpx
import pytest

from app.services import cnpj_resolver, datajud_adapter
from app.services.cnpj_resolver import (
    CnpjInvalidoError,
    CnpjNaoEncontradoError,
    CnpjResolverIndisponivelError,
    resolver_razao_social,
)
from app.services.datajud_adapter import (
    DataJudAdapter,
    DataJudError,
    DataJudIndisponivelError,
    DataJudRespostaInvalidaError,
    TribunalNaoMapeadoError,
    normalizar_processo_datajud,
)


def _adapter_com_transporte(handler) -> DataJudAdapter:
    adapter = DataJudAdapter()
    adapter._client = httpx.AsyncClient(
        base_url=datajud_adapter.settings.DATAJUD_BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    return adapter


async def test_tribunal_desconhecido_e_erro_do_chamador():
    adapter = _adapter_com_transporte(lambda request: httpx.Response(200, json={}))
    try:
        with pytest.raises(TribunalNaoMapeadoError):
            await adapter.buscar_por_numero_cnj("123", "TJXX")
    finally:
        await adapter.close()


@pytest.mark.parametrize("status_code", [401, 429, 500, 503])
async def test_status_de_erro_do_datajud_vira_datajud_indisponivel(status_code):
    adapter = _adapter_com_transporte(lambda request: httpx.Response(status_code, text="erro"))
    try:
        with pytest.raises(DataJudIndisponivelError):
            await adapter.buscar_por_numero_cnj("123", "TJSP")
    finally:
        await adapter.close()


async def test_timeout_do_datajud_vira_datajud_indisponivel():
    def handler(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    adapter = _adapter_com_transporte(handler)
    try:
        with pytest.raises(DataJudIndisponivelError):
            await adapter.buscar_por_nome("Fulano", "TJSP")
    finally:
        await adapter.close()


async def test_corpo_nao_json_vira_resposta_invalida():
    adapter = _adapter_com_transporte(lambda request: httpx.Response(200, text="<html>manutenção</html>"))
    try:
        with pytest.raises(DataJudRespostaInvalidaError):
            await adapter.buscar_por_numero_cnj("123", "TJSP")
    finally:
        await adapter.close()


async def test_hit_sem_source_nao_estoura_keyerror():
    corpo = {"hits": {"hits": [{"_id": "1"}, {"_id": "2", "_source": {"numeroProcesso": "123"}}]}}
    adapter = _adapter_com_transporte(lambda request: httpx.Response(200, json=corpo))
    try:
        resultados = await adapter.buscar_por_nome("Fulano", "TJSP")
    finally:
        await adapter.close()

    assert resultados == [{"numeroProcesso": "123"}]


async def test_sem_hits_retorna_none_e_nao_erro():
    adapter = _adapter_com_transporte(lambda request: httpx.Response(200, json={"hits": {"hits": []}}))
    try:
        assert await adapter.buscar_por_numero_cnj("123", "TJSP") is None
    finally:
        await adapter.close()


def test_erros_do_adapter_derivam_de_datajud_error():
    # As rotas capturam DataJudError; um erro novo fora dessa hierarquia
    # escaparia como 500 genérico.
    for erro in (TribunalNaoMapeadoError, DataJudIndisponivelError, DataJudRespostaInvalidaError):
        assert issubclass(erro, DataJudError)


def test_nivel_sigilo_nulo_nao_estoura():
    dados = normalizar_processo_datajud({"numeroProcesso": "123", "nivelSigilo": None}, "TJSP")
    assert dados["segredo_justica"] is False


def _patch_brasilapi(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(cnpj_resolver.httpx, "AsyncClient", client_factory)


async def test_cnpj_malformado_e_erro_do_chamador():
    with pytest.raises(CnpjInvalidoError):
        await resolver_razao_social("123")


async def test_cnpj_inexistente(monkeypatch):
    _patch_brasilapi(monkeypatch, lambda request: httpx.Response(404, json={"message": "não encontrado"}))
    with pytest.raises(CnpjNaoEncontradoError):
        await resolver_razao_social("11.222.333/0001-81")


@pytest.mark.parametrize(
    "resposta",
    [
        httpx.Response(500, text="erro"),
        httpx.Response(429, json={"message": "rate limit"}),
        httpx.Response(200, text="<html>manutenção</html>"),
        httpx.Response(200, json={"nome_fantasia": "Sem razão social"}),
    ],
)
async def test_falha_da_brasilapi_nao_vaza_httpx(monkeypatch, resposta):
    _patch_brasilapi(monkeypatch, lambda request: resposta)
    with pytest.raises(CnpjResolverIndisponivelError):
        await resolver_razao_social("11.222.333/0001-81")


async def test_cnpj_resolvido_com_sucesso(monkeypatch):
    corpo = {
        "razao_social": "EMPRESA TESTE LTDA",
        "nome_fantasia": "",
        "descricao_situacao_cadastral": "ATIVA",
    }
    _patch_brasilapi(monkeypatch, lambda request: httpx.Response(200, json=corpo))

    info = await resolver_razao_social("11.222.333/0001-81")

    assert info == {"razao_social": "EMPRESA TESTE LTDA", "nome_fantasia": None, "situacao": "ATIVA"}
