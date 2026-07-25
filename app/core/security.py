"""
Geração e verificação de API keys.

Padrão da chave exposta ao cliente: ajr_live_<32 chars aleatórios>
Só o hash (sha256) é persistido no banco — a chave em texto puro
existe apenas no momento da criação, mostrada uma única vez ao usuário.
Isso é o mesmo padrão do Stripe/GitHub: se perder, gera outra, nunca recupera a antiga.
"""

import hashlib
import secrets

from app.core.config import get_settings

settings = get_settings()


def gerar_api_key(ambiente: str = "live") -> tuple[str, str]:
    """
    Retorna (chave_texto_puro, chave_hash).
    chave_texto_puro é mostrada ao usuário UMA vez.
    chave_hash é o que persiste no banco.
    """
    prefixo = settings.API_KEY_PREFIX_LIVE if ambiente == "live" else settings.API_KEY_PREFIX_TEST
    corpo = secrets.token_urlsafe(24)
    chave_texto_puro = f"{prefixo}{corpo}"
    chave_hash = hash_api_key(chave_texto_puro)
    return chave_texto_puro, chave_hash


def hash_api_key(chave_texto_puro: str) -> str:
    return hashlib.sha256(chave_texto_puro.encode("utf-8")).hexdigest()


def extrair_ambiente(chave_texto_puro: str) -> str:
    if chave_texto_puro.startswith(settings.API_KEY_PREFIX_LIVE):
        return "live"
    if chave_texto_puro.startswith(settings.API_KEY_PREFIX_TEST):
        return "test"
    raise ValueError("Formato de API key inválido")


def gerar_webhook_secret() -> str:
    """Segredo usado para assinar (HMAC-SHA256) o payload dos webhooks de monitoramento."""
    return secrets.token_hex(32)
