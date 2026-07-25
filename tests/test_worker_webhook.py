from app.worker.webhook import (
    assinar_payload,
    identificar_movimentos_novos,
    montar_payload_webhook,
    verificar_assinatura,
)


def test_assinatura_e_deterministica():
    payload = b'{"a":1}'
    secret = "segredo-teste"
    assert assinar_payload(payload, secret) == assinar_payload(payload, secret)


def test_assinatura_muda_com_secret_diferente():
    payload = b'{"a":1}'
    assert assinar_payload(payload, "secret1") != assinar_payload(payload, "secret2")


def test_verificar_assinatura_aceita_valida_e_rejeita_invalida():
    payload = b'{"a":1}'
    secret = "segredo-teste"
    assinatura = assinar_payload(payload, secret)

    assert verificar_assinatura(payload, secret, assinatura) is True
    assert verificar_assinatura(payload, secret, "assinatura-forjada") is False
    assert verificar_assinatura(payload, "secret-errado", assinatura) is False


def test_montar_payload_e_assinatura_usam_o_mesmo_serializado():
    """
    Regressão específica: se montar_payload_webhook e o que de fato é
    enviado no POST divergirem em serialização (espaços, ordem de chaves),
    a assinatura calculada não bate mais com o corpo recebido do outro
    lado — o cliente rejeitaria um webhook legítimo. Este teste garante
    que assinar o resultado de montar_payload_webhook é estável.
    """
    movimento = {"data_movimento": "2023-05-10T10:00:00", "descricao": "Distribuição", "codigo_cnj": 26}
    payload1 = montar_payload_webhook("500...", "TRF3", movimento)
    payload2 = montar_payload_webhook("500...", "TRF3", movimento)

    assert payload1 == payload2
    assert assinar_payload(payload1, "s") == assinar_payload(payload2, "s")


def test_identificar_movimentos_novos_ignora_ja_existentes():
    existentes = {"hash1", "hash2"}
    normalizados = [
        {"hash_dedup": "hash1", "descricao": "já existe"},
        {"hash_dedup": "hash3", "descricao": "novo"},
    ]

    novos = identificar_movimentos_novos(existentes, normalizados)

    assert len(novos) == 1
    assert novos[0]["hash_dedup"] == "hash3"


def test_identificar_movimentos_novos_lista_vazia_quando_nada_mudou():
    existentes = {"hash1", "hash2"}
    normalizados = [{"hash_dedup": "hash1", "descricao": "já existe"}]

    assert identificar_movimentos_novos(existentes, normalizados) == []


def test_identificar_movimentos_novos_primeira_verificacao_tudo_e_novo():
    existentes: set[str] = set()
    normalizados = [{"hash_dedup": "hash1"}, {"hash_dedup": "hash2"}]

    novos = identificar_movimentos_novos(existentes, normalizados)

    assert len(novos) == 2
