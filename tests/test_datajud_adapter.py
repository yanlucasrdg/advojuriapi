"""
Testes de `app.services.datajud_adapter`.

`normalizar_processo_datajud` já tinha cobertura parcial em `test_busca.py`;
aqui completamos com casos de borda da normalização e cobrimos a classe
`DataJudAdapter` (buscar por número CNJ e por nome), isolando o httpx com
`MockTransport` para não bater na API real do CNJ.
"""

import httpx
import pytest

from app.services.datajud_adapter import (
    ALIAS_TRIBUNAL,
    DataJudAdapter,
    DataJudError,
    normalizar_processo_datajud,
)


def _adapter_com_handler(handler) -> DataJudAdapter:
    adapter = DataJudAdapter()
    # Troca o client real por um com transporte mockado, preservando base_url
    # e headers de Authorization construídos no __init__.
    base_url = adapter._client.base_url
    headers = adapter._client.headers
    adapter._client = httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        transport=httpx.MockTransport(handler),
    )
    return adapter


# ----------------------- DataJudAdapter.buscar_por_numero_cnj -----------------


async def test_buscar_por_numero_cnj_retorna_source_do_primeiro_hit():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api_publica_trf3/_search"
        return httpx.Response(
            200, json={"hits": {"hits": [{"_source": {"numeroProcesso": "123"}}]}}
        )

    adapter = _adapter_com_handler(handler)
    try:
        resultado = await adapter.buscar_por_numero_cnj("5005023-96.2023", "TRF3")
    finally:
        await adapter.close()

    assert resultado == {"numeroProcesso": "123"}


async def test_buscar_por_numero_cnj_normaliza_numero_na_query():
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        capturado["query"] = json.loads(request.content)
        return httpx.Response(200, json={"hits": {"hits": []}})

    adapter = _adapter_com_handler(handler)
    try:
        await adapter.buscar_por_numero_cnj("5005023-96.2023", "TRF3")
    finally:
        await adapter.close()

    numero_enviado = capturado["query"]["query"]["match"]["numeroProcesso"]
    assert numero_enviado == "5005023962023"


async def test_buscar_por_numero_cnj_sem_hits_retorna_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hits": {"hits": []}})

    adapter = _adapter_com_handler(handler)
    try:
        assert await adapter.buscar_por_numero_cnj("123", "TJSP") is None
    finally:
        await adapter.close()


async def test_buscar_por_numero_cnj_tribunal_nao_mapeado_levanta_erro():
    adapter = _adapter_com_handler(lambda req: httpx.Response(200, json={}))
    try:
        with pytest.raises(DataJudError):
            await adapter.buscar_por_numero_cnj("123", "TRIBUNAL_INEXISTENTE")
    finally:
        await adapter.close()


async def test_buscar_por_numero_cnj_propaga_erro_http():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"erro": "elasticsearch down"})

    adapter = _adapter_com_handler(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.buscar_por_numero_cnj("123", "TJSP")
    finally:
        await adapter.close()


# --------------------------- DataJudAdapter.buscar_por_nome -------------------


async def test_buscar_por_nome_retorna_lista_de_sources():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"hits": {"hits": [{"_source": {"a": 1}}, {"_source": {"a": 2}}]}},
        )

    adapter = _adapter_com_handler(handler)
    try:
        resultado = await adapter.buscar_por_nome("Fulano", "TJSP")
    finally:
        await adapter.close()

    assert resultado == [{"a": 1}, {"a": 2}]


async def test_buscar_por_nome_passa_tamanho_e_fuzziness():
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        capturado["query"] = json.loads(request.content)
        return httpx.Response(200, json={"hits": {"hits": []}})

    adapter = _adapter_com_handler(handler)
    try:
        await adapter.buscar_por_nome("Fulano de Tal", "TJSP", tamanho=7)
    finally:
        await adapter.close()

    assert capturado["query"]["size"] == 7
    match = capturado["query"]["query"]["match"]["partes.nome"]
    assert match["query"] == "Fulano de Tal"
    assert match["fuzziness"] == "AUTO"


async def test_buscar_por_nome_tribunal_nao_mapeado_levanta_erro():
    adapter = _adapter_com_handler(lambda req: httpx.Response(200, json={}))
    try:
        with pytest.raises(DataJudError):
            await adapter.buscar_por_nome("Fulano", "XXX")
    finally:
        await adapter.close()


def test_alias_tribunal_normaliza_caixa():
    # buscar_* usa tribunal.upper(); garante que as chaves do mapa são upper.
    assert all(k == k.upper() for k in ALIAS_TRIBUNAL)


# --------------------------- normalizar_processo_datajud ---------------------


def test_normalizar_processo_datajud_campos_vazios_viram_defaults():
    resultado = normalizar_processo_datajud({}, "tjsp")

    assert resultado["numero_cnj"] == ""
    assert resultado["tribunal"] == "TJSP"  # upper aplicado
    assert resultado["classe"] is None
    assert resultado["assunto"] is None
    assert resultado["orgao_julgador"] is None
    assert resultado["valor_acao"] is None
    assert resultado["segredo_justica"] is False
    assert resultado["fonte"] == "datajud"
    assert resultado["partes"] == []
    assert resultado["movimentos"] == []


def test_normalizar_processo_datajud_segredo_justica_quando_sigilo_positivo():
    resultado = normalizar_processo_datajud({"nivelSigilo": 2}, "TJSP")
    assert resultado["segredo_justica"] is True


def test_normalizar_processo_datajud_junta_assuntos_com_virgula():
    bruto = {"assuntos": [{"nome": "Assunto A"}, {"nome": "Assunto B"}]}
    resultado = normalizar_processo_datajud(bruto, "TJSP")
    assert resultado["assunto"] == "Assunto A, Assunto B"


def test_normalizar_processo_datajud_movimentos_tem_hash_dedup_deterministico():
    bruto = {
        "movimentos": [
            {"nome": "Distribuição", "dataHora": "2023-05-10T10:00:00", "codigo": 26}
        ]
    }
    r1 = normalizar_processo_datajud(bruto, "TJSP")
    r2 = normalizar_processo_datajud(bruto, "TJSP")

    mov = r1["movimentos"][0]
    assert mov["descricao"] == "Distribuição"
    assert mov["codigo_cnj"] == "26"
    assert len(mov["hash_dedup"]) == 64
    # mesmo input -> mesmo hash (dedup estável entre varreduras)
    assert mov["hash_dedup"] == r2["movimentos"][0]["hash_dedup"]


def test_normalizar_processo_datajud_movimentos_diferentes_hashes_distintos():
    bruto = {
        "movimentos": [
            {"nome": "Mov A", "dataHora": "2023-01-01T00:00:00"},
            {"nome": "Mov B", "dataHora": "2023-01-02T00:00:00"},
        ]
    }
    movimentos = normalizar_processo_datajud(bruto, "TJSP")["movimentos"]
    assert movimentos[0]["hash_dedup"] != movimentos[1]["hash_dedup"]


def test_normalizar_processo_datajud_partes_nao_expoem_documento():
    bruto = {"partes": [{"nome": "Fulano", "tipoPessoa": "fisica", "polo": "ativo"}]}
    parte = normalizar_processo_datajud(bruto, "TJSP")["partes"][0]
    assert parte == {
        "nome": "Fulano",
        "documento": None,
        "tipo_pessoa": "fisica",
        "polo": "ativo",
    }
