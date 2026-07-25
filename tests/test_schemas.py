"""
Testes dos schemas Pydantic sem cobertura (`saldo` e `monitoramento`).

São contratos da API pública: conversão centavos->reais, validação de
recarga positiva e serialização a partir de ORM (`from_attributes`).
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.monitoramento import (
    MonitoramentoCreate,
    MonitoramentoCriadoResponse,
    MonitoramentoResponse,
)
from app.schemas.saldo import RecargaRequest, RecargaResponse, SaldoResponse


def test_saldo_from_centavos_converte_para_reais():
    saldo = SaldoResponse.from_centavos(5000)
    assert saldo.saldo_centavos == 5000
    assert saldo.saldo_reais == 50.0


def test_saldo_from_centavos_arredonda_duas_casas():
    saldo = SaldoResponse.from_centavos(12345)
    assert saldo.saldo_reais == 123.45


def test_saldo_from_centavos_zero():
    saldo = SaldoResponse.from_centavos(0)
    assert saldo.saldo_centavos == 0
    assert saldo.saldo_reais == 0.0


def test_recarga_request_aceita_valor_positivo():
    assert RecargaRequest(valor_centavos=100).valor_centavos == 100


@pytest.mark.parametrize("valor", [0, -1, -5000])
def test_recarga_request_rejeita_valor_nao_positivo(valor):
    with pytest.raises(ValidationError):
        RecargaRequest(valor_centavos=valor)


def test_recarga_response_campos():
    resp = RecargaResponse(transacao_id="tx-1", saldo_apos_centavos=9000, status="pendente")
    assert resp.transacao_id == "tx-1"
    assert resp.saldo_apos_centavos == 9000
    assert resp.status == "pendente"


def test_monitoramento_create_exige_campos_obrigatorios():
    with pytest.raises(ValidationError):
        MonitoramentoCreate(numero_cnj="123")  # falta tribunal e webhook_url


def test_monitoramento_response_from_attributes():
    orm_like = SimpleNamespace(
        id=uuid.uuid4(),
        processo_id=uuid.uuid4(),
        webhook_url="https://exemplo.com/hook",
        ativo=True,
        ultima_verificacao_em=None,
        criado_em=datetime.now(timezone.utc),
    )
    resp = MonitoramentoResponse.model_validate(orm_like)
    assert resp.webhook_url == "https://exemplo.com/hook"
    assert resp.ativo is True
    assert resp.ultima_verificacao_em is None


def test_monitoramento_criado_inclui_webhook_secret():
    orm_like = SimpleNamespace(
        id=uuid.uuid4(),
        processo_id=uuid.uuid4(),
        webhook_url="https://exemplo.com/hook",
        ativo=True,
        ultima_verificacao_em=datetime.now(timezone.utc),
        criado_em=datetime.now(timezone.utc),
        webhook_secret="segredo-mostrado-uma-vez",
    )
    resp = MonitoramentoCriadoResponse.model_validate(orm_like)
    assert resp.webhook_secret == "segredo-mostrado-uma-vez"
