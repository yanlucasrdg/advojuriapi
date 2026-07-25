"""
Testes de geração e verificação de API keys (`app.core.security`).

O módulo estava sem cobertura, apesar de conter regra de segurança sensível:
formato/prefixo da chave, que só o hash SHA-256 é persistido (nunca o texto
puro), e a detecção de ambiente (live/test) a partir do prefixo.
"""

import hashlib

import pytest

from app.core import security
from app.core.config import get_settings

settings = get_settings()


def test_gerar_api_key_live_usa_prefixo_live():
    chave, chave_hash = security.gerar_api_key("live")
    assert chave.startswith(settings.API_KEY_PREFIX_LIVE)
    assert chave_hash == security.hash_api_key(chave)


def test_gerar_api_key_test_usa_prefixo_test():
    chave, _ = security.gerar_api_key("test")
    assert chave.startswith(settings.API_KEY_PREFIX_TEST)


def test_gerar_api_key_ambiente_desconhecido_cai_em_test():
    # Qualquer valor diferente de "live" usa o prefixo de teste (fail-safe:
    # nunca emitir uma chave "live" por engano de digitação do ambiente).
    chave, _ = security.gerar_api_key("qualquer-coisa")
    assert chave.startswith(settings.API_KEY_PREFIX_TEST)


def test_gerar_api_key_nao_persiste_texto_puro():
    # O que vai pro banco é o hash, e ele NÃO deve permitir recuperar a chave.
    chave, chave_hash = security.gerar_api_key("live")
    assert chave_hash != chave
    assert chave not in chave_hash


def test_gerar_api_key_e_aleatoria():
    chave1, _ = security.gerar_api_key("live")
    chave2, _ = security.gerar_api_key("live")
    assert chave1 != chave2


def test_hash_api_key_e_sha256_deterministico():
    chave = "ajr_live_exemplo"
    esperado = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    assert security.hash_api_key(chave) == esperado
    assert security.hash_api_key(chave) == security.hash_api_key(chave)


def test_hash_api_key_muda_com_entrada_diferente():
    assert security.hash_api_key("ajr_live_a") != security.hash_api_key("ajr_live_b")


def test_extrair_ambiente_reconhece_live_e_test():
    chave_live = f"{settings.API_KEY_PREFIX_LIVE}abc"
    chave_test = f"{settings.API_KEY_PREFIX_TEST}abc"
    assert security.extrair_ambiente(chave_live) == "live"
    assert security.extrair_ambiente(chave_test) == "test"


def test_extrair_ambiente_rejeita_formato_invalido():
    with pytest.raises(ValueError):
        security.extrair_ambiente("chave_sem_prefixo_conhecido")


def test_gerar_webhook_secret_e_hex_de_64_chars():
    segredo = security.gerar_webhook_secret()
    assert len(segredo) == 64
    int(segredo, 16)  # levanta ValueError se não for hex válido


def test_gerar_webhook_secret_e_aleatorio():
    assert security.gerar_webhook_secret() != security.gerar_webhook_secret()
