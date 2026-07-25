"""
Testes de `app.services.cnpj_resolver`.

A normalização já era testada em `test_busca.py`; aqui cobrimos o caminho
que fazia rede (`resolver_razao_social`), isolando o httpx com um
`MockTransport` — sem bater na BrasilAPI de verdade. Cobre: sucesso,
CNPJ inexistente (404), CNPJ com formato inválido e falha de transporte.
"""

import httpx
import pytest

from app.services import cnpj_resolver
from app.services.cnpj_resolver import (
    CnpjNaoEncontradoError,
    CnpjResolverError,
    resolver_razao_social,
)


def _mock_client(handler, monkeypatch):
    """Faz httpx.AsyncClient usar o MockTransport dado, preservando kwargs."""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


@pytest.mark.parametrize("cnpj", ["11.222.333/0001-81", "11222333000181"])
async def test_resolver_razao_social_sucesso(cnpj, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/11222333000181")
        return httpx.Response(
            200,
            json={
                "razao_social": "ACME LTDA",
                "nome_fantasia": "ACME",
                "descricao_situacao_cadastral": "ATIVA",
            },
        )

    _mock_client(handler, monkeypatch)

    resultado = await resolver_razao_social(cnpj)
    assert resultado == {
        "razao_social": "ACME LTDA",
        "nome_fantasia": "ACME",
        "situacao": "ATIVA",
    }


async def test_resolver_razao_social_nome_fantasia_vazio_vira_none(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"razao_social": "SO RAZAO SOCIAL", "nome_fantasia": ""},
        )

    _mock_client(handler, monkeypatch)

    resultado = await resolver_razao_social("11222333000181")
    assert resultado["nome_fantasia"] is None
    assert resultado["situacao"] is None


async def test_resolver_razao_social_404_levanta_nao_encontrado(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "CNPJ não encontrado"})

    _mock_client(handler, monkeypatch)

    with pytest.raises(CnpjNaoEncontradoError):
        await resolver_razao_social("11222333000181")


async def test_resolver_razao_social_cnpj_invalido_nao_faz_rede(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("não deveria chamar a rede para CNPJ inválido")

    _mock_client(handler, monkeypatch)

    with pytest.raises(CnpjResolverError):
        await resolver_razao_social("123")


async def test_resolver_razao_social_erro_de_transporte_vira_resolver_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexão recusada")

    _mock_client(handler, monkeypatch)

    with pytest.raises(CnpjResolverError):
        await resolver_razao_social("11222333000181")


async def test_resolver_razao_social_status_5xx_propaga(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"erro": "interno"})

    _mock_client(handler, monkeypatch)

    with pytest.raises(httpx.HTTPStatusError):
        await resolver_razao_social("11222333000181")


def test_modulo_expoe_base_url_da_brasilapi():
    assert cnpj_resolver.BRASILAPI_BASE_URL.startswith("https://")
