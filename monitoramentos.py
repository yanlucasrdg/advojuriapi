"""
Lógica pura do worker de monitoramento — sem I/O, sem Celery, sem DB.
Separada de propósito para ser testável direto, sem precisar subir
worker, broker ou banco.
"""

import hashlib
import hmac
import json


def assinar_payload(payload_bytes: bytes, secret: str) -> str:
    """
    Assinatura HMAC-SHA256 do corpo do webhook, no mesmo padrão que
    Stripe/GitHub usam. O cliente valida recalculando o HMAC com o
    `webhook_secret` recebido na criação do monitoramento e comparando
    (comparação em tempo constante) com o header X-AdvoJuri-Signature.
    """
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def verificar_assinatura(payload_bytes: bytes, secret: str, assinatura_recebida: str) -> bool:
    assinatura_esperada = assinar_payload(payload_bytes, secret)
    return hmac.compare_digest(assinatura_esperada, assinatura_recebida)


def montar_payload_webhook(numero_cnj: str, tribunal: str, movimento: dict) -> bytes:
    corpo = {
        "evento": "movimento_novo",
        "numero_cnj": numero_cnj,
        "tribunal": tribunal,
        "movimento": {
            "data_movimento": str(movimento["data_movimento"]),
            "descricao": movimento["descricao"],
            "codigo_cnj": movimento.get("codigo_cnj"),
        },
    }
    # separators sem espaço: o mesmo bytes exato é usado pra assinar E pra
    # enviar — se um serializar diferente do outro, a assinatura não bate
    # nem no lado certo (bug bobo, mas comum: assinar um dict e no envio
    # deixar o json.dumps default recolocar espaços).
    return json.dumps(corpo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def identificar_movimentos_novos(hashes_existentes: set[str], movimentos_normalizados: list[dict]) -> list[dict]:
    """
    Retorna os movimentos de `movimentos_normalizados` cujo hash_dedup
    ainda não está em `hashes_existentes`. Pura por design: dado o mesmo
    input, sempre o mesmo output — fácil de testar sem tocar em DataJud
    ou banco de dados de verdade.
    """
    return [m for m in movimentos_normalizados if m["hash_dedup"] not in hashes_existentes]
